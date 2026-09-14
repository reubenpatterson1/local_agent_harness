# ltx-movie: distance–identity — stop the `Style:` suffix from pulling every shot into a portrait

Status: ready for implementation. Written against `bin/ltx-movie` and
`tests/test_ltx_movie_offline.py` at branch `ltx2-mlx-video-pipeline`, commit `1e710bc` plus
the uncommitted Step 1 + Step 2 working-tree changes. Verified baseline at authoring time:
`python3 tests/test_ltx_movie_offline.py` → `rc=0`, `OK 290/290`.

This is **Step 3**. It supersedes two constraints written in
`docs/superpowers/specs/2026-09-13-ltx-movie-composition-tightening-fix.md` (Step 2); the
supersessions are named explicitly in §2.3. Read Step 2 first — this document assumes its
`SEED_IMAGE_PREFACE` / `SEED_IMAGE_POSTFACE` / `_style_echo_warnings` are already on disk.

The executor makes **no** design decisions. Every string, threshold, token, file path, check
name and mutation is fixed below. If something here is ambiguous, stop and ask — do not choose.

---

## 1. Problem and success criteria

### 1.1 What Step 2 left behind

Step 1 fixed identity: Panel 1 emits a `Style:` line, and `bin/ltx-story-images`
(`_style_text` / `_compose_prompt`, lines 130-157) appends that line **verbatim to the end of
every panel's image prompt**. Step 2 fixed composition: later `Image:` fields became 45-70
words of composition only, with appearance words removed.

Both wins are real, and they now fight each other. The `Style:` line, as Step 2's preface
specifies it, contains

> the recurring subjects and their fixed appearance (wardrobe, colours, markings,
> distinguishing features), the materials and textures, the colour palette, the lighting
> character, and the rendering style, medium and lens character

so it carries face- and hair-level attributes — in the reference run, literally
`young woman with tightly curled auburn-red hair, warm light-brown skin with scattered
freckles, brown eyes, glossy pink lips, …`. Phase 2 appends that to the prompt for **every**
panel, mechanically, including the extreme wide shots.

The result is a prompt that contradicts itself:

```
extreme wide shot, camera at knee height, the curly-haired woman small in the centre of the
frame walking away down a quiet residential street at dusk, low houses either side
+ young woman with tightly curled auburn-red hair, warm light-brown skin with scattered
  freckles, brown eyes, glossy pink lips, …
```

A text-to-image model cannot render freckles, eye colour and lip colour on a subject that is
forty pixels tall. It resolves the contradiction the only way it can: it moves the camera in.
Step 2 cleaned the panel's own text and the suffix re-dirtied it. **The composition defect is
therefore only half-fixed: the story.md is now correct and the rendered prompt is not.**

### 1.2 Root cause, stated once

`Style:` is defined as "everything identical in every panel". Subject appearance is identical
in every panel — but it is **not renderable** in every panel. Identity is distance-dependent
and the `Style:` suffix is distance-blind. Anything distance-dependent must live in the
panel's own `Image:` field, where the panel's shot type is also stated, so the two are written
together and cannot disagree.

### 1.3 The fix, in three parts

1. **A content boundary on `Style:`** — it carries the *global look only*: colour palette,
   lighting character, the materials and surface textures of the setting, and the rendering
   style / medium / lens character. It names no person and no subject attribute. Budget drops
   from 40-70 to 30-55 words, because the subject words that used to fill it are gone and a
   too-large budget is an invitation to pad it back with them.
2. **A three-band inline-identity convention** — each later panel's `Image:` field writes the
   subject's identity itself, at exactly the level of detail its own shot type can resolve:
   far band **at most 8** identity words, mid band **10-20**, near band **18-30**. The mid and
   near budgets are ranges with a floor, not ceilings: with appearance gone from `Style:`, a
   near-band panel that writes no identity words renders a different person (§9.2
   `near_under`). The identity words come out of the existing 45-70 word budget, not on top of
   it.
3. **`_style_content_warnings`** — a new advisory (never fatal) check that flags a `Style:`
   line containing any of 109 subject-attribute tokens, so a non-compliant line is visible in
   Phase 1's output and in `movie.log` before any GPU time is spent.

### 1.4 Success criteria (binding unless marked NON-BINDING)

- **SC1** `python3 tests/test_ltx_movie_offline.py` exits 0 and prints **`OK 309/309`**. That
  is the current 290 plus exactly 19 new `check(...)` rows (§7.4 L38 = 9, §7.5 L39 = 10), with
  **no** pre-existing row deleted and exactly the six rows in §7.1 changed in place.
- **SC2** `python3 tests/test_ltx_story_images.py`, `python3 tests/test_ltx_story_video.py`,
  `python3 tests/test_ltx_chain.py`, `python3 tests/test_ltx_mlx_render.py` each exit 0,
  unedited.
- **SC3** Every one of the 20 mutations in §7.7 makes the named check(s) FAIL when applied,
  and the suite returns to `OK 309/309` when reverted. A mutation that does not turn a check
  red is a defective test, not a passing mutation — report it and stop.
- **SC4** On the §8 A3 rerun, Phase 1 prints **zero** `Warning: panel 1: Style: names` lines —
  i.e. the authored `Style:` line contains none of the 109 banned tokens.
- **SC5** On that same rerun, Phase 1 prints **zero** `Warning: panel N: Image: restates`
  lines. This is Step 2's machine win and it must not regress.
- **SC6** On that same rerun, every panel 2..N `Image:` field is 45-70 words. Tolerance: at
  most one panel outside the band, none above 85 words.
- **SC7** On that same rerun, band compliance holds **two-sidedly**, measured by §8 A3.3's
  script. Let `n` be the count of §6.1 banned tokens in a panel's `Image:` field:
  - far band (`extreme wide shot`, `wide shot`): `n ≤ 7`, **and** the field contains none of
    `freckle, freckles, freckled, eye, eyes, lip, lips, cheek, cheeks, chin, jaw, jawline,
    nose, teeth, complexion, pores`.
  - mid band (`medium shot`, `medium close-up`): `4 ≤ n ≤ 12`.
  - near band (`close-up`, `extreme close-up`): `n ≥ 6`, no ceiling.

  The **floors are as load-bearing as the ceilings** and are not a formality: §9.2's
  `near_under` generation shows a near-band panel with `n = 3` renders a correctly-framed
  close-up of a *visibly different person*. Thresholds derived from the six real generations
  in §9.2, which score 5 / 6 / 12 (compliant far/mid/near) against 11 (`far_over`, breaks
  composition) and 3 (`near_under`, breaks identity).
- **SC8** Human eyeball on the rerun's stills, both halves, judged together:
  (a) a panel whose `Image:` says *wide shot* / *extreme wide shot* renders as an actual wide
  shot, and (b) the subject is still recognisably the person in `~/Downloads/red.jpg` in the
  mid- and near-band panels. **If (a) passes and (b) fails, report it and stop** — do not
  widen the bands, do not put appearance back into `Style:`, do not change anything further.
  Explicitly a human judgement, not a machine check.
- **SC9 (NON-BINDING, report-only)**
  `grep -c '^Style: ' generated/stories/band_red_test/story.md` is `1`. Report the actual
  number. A miss here is not a failure of this spec (rationale: Step 2 §3.4).

### 1.5 Must-have vs nice-to-have

Must-have: §5 (prompt-text rewrite), §6 (`_style_content_warnings` and its call site), §7
(tests), §8 (acceptance A0-A2).

Nice-to-have: §8 A3 (the real end-to-end rerun). It requires the 27B server and a human, and
**must not be run without the user's explicit go-ahead**. SC4-SC8 are gated on it; if it is
not run, report SC1-SC3 as the result and SC4-SC8 as *not evaluated*. Do not fabricate them.

Nothing in this spec is optional-by-omission: everything specified is to be implemented.

---

## 2. Scope

### 2.1 In scope

- `bin/ltx-movie` only:
  - `SEED_IMAGE_PREFACE` (starts line 141) — five edits, §5.1-§5.5.
  - `SEED_IMAGE_POSTFACE` (starts line 157) — one edit, §5.6.
  - the `require_style` violation message in `_validate_story_md` (lines ~430-437) — §5.7.
  - two new module-level objects, `_STYLE_BANNED_TOKENS` and `_style_content_warnings`, §6.
  - two new lines in `phase1_story`, §6.3.
- `tests/test_ltx_movie_offline.py`: six updated check rows (§7.1), two new test functions
  `L38` / `L39` (§7.4, §7.5), two new module-level fixtures (§7.3), two `__main__`
  registrations (§7.6).

### 2.2 Explicitly OUT of scope

- **`bin/ltx-story-images` is not edited.** `_style_text`, `_compose_prompt` and `_panel_seed`
  are correct: appending the `Style:` text verbatim to every panel is the right mechanism once
  the `Style:` text itself is distance-neutral. Do not add per-panel suffix filtering, do not
  make the suffix conditional on shot type, do not parse shot types in that file. Do not edit
  `tests/test_ltx_story_images.py`.
- **`bin/ltx-story-manifest` is not edited.** `p["style"]` and `p["image"]` already exist.
- **`STORY_PROMPT_TEMPLATE` and `STORY_PROMPT_TEMPLATE_NO_STILLS` are not edited.** Check
  `L25a` asserts the unseeded prompt is byte-identical to `STORY_PROMPT_TEMPLATE.format(...)`.
  Every new instruction goes in the preface or the postface, which are used only on seeded,
  non-`--no-stills` runs.
- **`_style_echo_warnings`, `_content_words`, `_load_story_panels`, `_ECHO_STOPWORDS`,
  `_ECHO_MIN_STYLE_WORDS`, `_ECHO_MIN_OVERLAP`, `_ECHO_FRACTION` are not edited**, and neither
  is test `L36`. The echo heuristic is orthogonal: it measures `Image:`-vs-`Style:` overlap,
  and a `Style:` line with the subject removed simply produces lower overlap. See §6.4 for why
  `L36`'s `_ECHO_STYLE` fixture is deliberately left describing the *old* convention.
- **`_validate_story_md` gains no new violation and its signature does not change.** The
  content boundary is advisory only; rationale §6.2. All five `L32` rows stay green unchanged.
- **No new CLI flag, no config key, no shot-type parser in `bin/ltx-movie`, no retry loop, no
  CLIP/drift metric, no img2img or pixel conditioning**, and no TODO, hook or comment
  anticipating one.
- **Do not touch** the pre-existing dirty files `bin/ltx-story-video`, `ltx_ceiling.json`,
  `ltx_video_skill.py`, `z_image_skill.py`, `bin/ltx-story-manifest`.
- **Do not change the string** `"Review story.md above. Enter to continue, Ctrl-C to abort: "`
  or `"Review the plan and the estimated render time above. Enter to render, Ctrl-C to abort: "`.
  The `pexpect` driver in §8 A3.2 matches both exactly.
- **`generated/stories/drift_red_test/` is not touched.** A3 uses a fresh story-id
  (`band_red_test`) precisely so Step 2's evidence survives on disk for the before/after table.

### 2.3 Deliberate supersessions of Step 2

Step 2's §2.2 contains two prohibitions that this spec overrides on purpose. The executor must
apply the new rule, not the old one:

1. Step 2: *"Do not change the `Style:` field's 40-70 word budget."* → **superseded.** The
   budget becomes **30-55 words**. Step 2's rationale was that the budget is what fixed
   identity; §1.2 shows it is also what breaks composition. Identity now lives inline, so the
   budget no longer carries it, and 40-70 words of palette/lighting/materials/render-style is
   more room than that content needs — the model fills the surplus with the subject words this
   spec is removing. Measured: the §7.3 compliant fixture is 39 words / 36 content words.
2. Step 2: *"`Appearance, wardrobe, hair, skin, face, build … must not be described again in
   any Image: field after Panel 1`"* → **superseded.** Appearance **is** described again, in
   every panel that can show it, bounded by §5.3's bands. Materials, colour palette, lighting
   character and rendering style remain banned from later `Image:` fields, unchanged.

Step 2's later-panel `Image:` budget of **45-70 words is NOT superseded** — it stays. See §3.2.

---

## 3. Design decisions (made here; the executor makes none)

### 3.1 Decision D1 — the boundary is drawn at "renderable at every distance", not at "constant"

`Style:` keeps what is true of the *image* regardless of what is in frame — palette, lighting
character, setting materials and textures, rendering style, medium, lens character. It loses
what is true of the *subject* — hair, skin, face, build, age, gender, wardrobe. The test for
any future attribute is: *could this be rendered in an extreme wide shot?* If no, it is not a
`Style:` attribute. This sentence is the boundary; §6.1's 109 tokens are its enforcement, not
its definition.

### 3.2 Decision D2 — identity words come **out of** the 45-70 budget, not on top of it

The later-panel budget stays 45-70 words. This is not a compromise, it is the point: a
near-band panel has almost no setting left in frame, so the words it spends on a face are
exactly the words a far-band panel spends on the street. A budget that grew with the band
would let a near-band panel keep its setting words *and* add face words, producing the
overstuffed prompts Step 2 removed. Keeping one number also keeps `L35c`, `L35d` and the SC6
measurement unchanged.

### 3.3 Decision D3 — three bands, partitioning the six shot types the template already names

`STORY_PROMPT_TEMPLATE` enumerates exactly six shot types. They partition 2/2/2:

| Band | Shot types | Identity budget | May name | Must not name |
| --- | --- | --- | --- | --- |
| FAR | `extreme wide shot`, `wide shot` | **at most 8 words** | overall build or height; the dominant colour of the clothing | hair texture, hair length, skin tone, face, eyes, lips, freckles, markings, fabric detail |
| MID | `medium shot`, `medium close-up` | **10 to 20 words** | the garments and their colours; hair colour and length; build | eye colour, lip colour, freckles, skin texture |
| NEAR | `close-up`, `extreme close-up` | **18 to 30 words** | skin tone; markings (freckles, scars); eye colour; lip colour; hair colour and texture; the garment visible at the neckline | — (this is the only band that describes a face) |

Three bands and not six: six per-shot rules is more than a 27B model reliably tracks across a
1500-word prompt, and the renderable/not-renderable distinction genuinely has three levels
(silhouette / clothed figure / face).

**The mid and near budgets are ranges, not ceilings, and the floor is the load-bearing half.**
Step 2 trained this prompt to write composition-only later panels, and the `Style:` line no
longer carries the subject — so a near-band panel that writes no identity words has nowhere
left to get identity from. §9.2's `near_under` generation is exactly that case: correct
close-up framing, wrong person. The far band has a ceiling only; at that distance the referring
phrase plus a garment colour is provably enough (§9.2 `far_new`).

### 3.4 Decision D4 — the band rule is stated in the preface **and** restated in the postface

Same reasoning as Step 2 §3.6, which is already validated on this codebase: a preface-only
instruction sits ~1000 words upstream of the template's own concrete rules and loses to them.
The postface is the last thing the model reads. The preface carries the full three-band block
(§5.3); the postface carries a one-paragraph restatement with the three caps (§5.6).

### 3.5 Decision D5 — the content check is advisory, and it is a token list, not a classifier

`_style_content_warnings` prints a warning; it never changes a return code and never becomes a
`_validate_story_md` violation. Rationale, identical in shape to Step 2 §3.5: violations are
fatal with no override flag, and a word-list heuristic must not be able to strand a legitimate
story behind a token match. A false positive here costs one ignorable warning line; a false
negative costs one visibly-wrong still, caught by SC8.

A fixed token list and not an LLM/embedding classifier: it is deterministic, it is testable
offline with no server, it is auditable by reading 109 words, and the failure it catches is
lexical (the model writing "hair" into a line that must contain no subject words).

### 3.6 Decision D6 — the call site loads the panels twice, on purpose

§6.3 adds a second `for warning in _style_content_warnings(_load_story_panels(story_md)):`
loop rather than hoisting `panels = _load_story_panels(story_md)` and reusing it. The hoist
would be marginally cleaner and would break checks `L37a` and `L37b`, which pin the existing
loop's exact two lines and its exact indentation. Two file reads of a ≤100-panel markdown file
once per run is not a cost worth two churned checks. **Do not "optimise" this.**

Order: the content warning prints **first**, then the echo warnings. The content warning names
the upstream cause (a bad `Style:` line); the echo warnings name a downstream symptom.

### 3.7 Decision D7 — the banned list is a `frozenset` of 109 lowercase tokens, matched through `_content_words`

Matching through the existing `_content_words` (lowercase, alphabetic, ≥3 chars, minus
`_ECHO_STOPWORDS`) buys case-insensitivity and punctuation-stripping for free and guarantees
the two advisory checks tokenise identically. Verified while authoring: the 109 tokens are
unique, all `isalpha()` and `islower()` and `len > 2`, and disjoint from `_ECHO_STOPWORDS`.

---

## 4. Inputs, outputs, side effects

**Inputs.** Unchanged: `bin/ltx-movie`'s existing CLI. The new logic reads only
`panels[0]["style"]` — the string `bin/ltx-story-manifest`'s `_parse_prompts_md` already
returns for Panel 1's `Style:` line (`""` when absent).

**Outputs.** One new class of line on stdout during Phase 1:

```
Warning: panel 1: Style: names 8 subject-level attribute word(s) (curled, eyes, freckles, hair, lips, skin, woman, young) -- ...
```

Nothing else changes: no new file, no new directory, no change to `story.md`, `images.json`,
`manifest.json`, `movie.mp4` or `movie.log`'s format. The warning lands in `movie.log` because
it goes to stdout and Phase 1 is tee'd.

**Side effects.** None. `_style_content_warnings` is pure: it takes a list of dicts and returns
a list of strings. It performs no I/O, mutates no argument, and cannot raise on any input
listed in §6.1.

**Exit codes.** Unchanged. The new check can never make `bin/ltx-movie` exit non-zero.

---

## 5. Change set 1 of 3 — `bin/ltx-movie` prompt text

All six strings in §5.1-§5.5 occur **exactly once** in `SEED_IMAGE_PREFACE` today (verified).
Replace each in place. Preserve every surrounding character, including the `--` em-dash
convention and the double newlines between paragraphs.

### 5.1 Edit A — the "consistency is handled for you" sentence

**Find** (in the third paragraph of the preface):

```
That consistency is already handled for you: the Style: line described below is appended word for word to the end of every panel's image prompt by the pipeline, before the panel is rendered. So: Do NOT copy Panel 1's Image: description into the later panels, and do not restate its content in your own words either.
```

**Replace with:**

```
The palette, lighting and rendering style are already handled for you: the Style: line described below is appended word for word to the end of every panel's image prompt by the pipeline, before the panel is rendered. The subject's identity is NOT handled that way -- it is written into each panel's own Image: field, sized to that panel's shot distance by the three bands below. So: Do NOT copy Panel 1's Image: description into the later panels, and do not carry more identity detail than that panel's shot distance can actually resolve.
```

Preserved substrings that other checks pin: `appended word for word to the end of every
panel's image prompt` (`L30b`), `Do NOT copy Panel 1's Image: description into the later
panels` (`L31b`), `must stay visually consistent with what you actually observed` (`L25e`,
earlier in the same paragraph, untouched).

### 5.2 Edit B — the attribute-class ban

**Find:**

```
Appearance, wardrobe, hair, skin, face, build, materials, colour palette, lighting character and rendering style must not be described again in any Image: field after Panel 1 -- not word for word and not reworded. Writing them a second time puts the same attribute list into the image prompt twice and crowds out the shot type, camera angle and framing that are the only things making that panel different from its neighbours.
```

**Replace with:**

```
Materials, colour palette, lighting character and rendering style must not be described again in any Image: field after Panel 1 -- not word for word and not reworded. Writing them a second time puts the same attribute list into the image prompt twice and crowds out the shot type, camera angle and framing that are the only things making that panel different from its neighbours. Appearance is the exception, and it works the other way round: hair, skin, face, build and wardrobe are NOT in the Style: line, so each later panel writes them itself -- but only as much of them as its own shot distance can show.
```

`not word for word and not reworded` is preserved exactly once here, keeping `L35e`'s count of
3 (template `Motion:` rule + preface + postface).

### 5.3 Edit C — the later-panel paragraph, and the new three-band block

**Find** (the whole fourth paragraph, from `Each later panel's` to `no Style: line.`):

```
Each later panel's Image: field is 45-70 words -- shorter than the 70-90 words asked for below, which applies to Panel 1 only, because the appearance words are gone -- and carries ONLY that panel's own composition: the shot type, the camera viewpoint and height, where the subject sits in the frame and which way it faces, the action or pose at that instant, the distance between camera and subject, and the setting and background elements in view. Write it in that order: shot type first, then camera viewpoint, then the subject's short referring phrase, then the action and placement, then the setting. Refer to each recurring subject by one short referring phrase of at most five words -- the same phrase the Motion: fields use, chosen the first time that subject appears and reused word for word in every later Image: and Motion: field, for example "the woman in grey" or "the red car". That phrase is the only appearance detail a later Image: field may carry. A later panel has exactly three fields, in this order: Image:, Motion:, Narration: -- and no Style: line.
```

**Replace with** (one paragraph, then a blank line, then the band block — the band block's
paragraphs are separated by single newlines so the three bands read as a list):

```
Each later panel's Image: field is 45-70 words -- shorter than the 70-90 words asked for below, which applies to Panel 1 only, because the global-look words are gone and the identity words are trimmed to what the shot distance can show -- and carries that panel's own composition plus the identity its band allows, and nothing else: the shot type, the camera viewpoint and height, where the subject sits in the frame and which way it faces, the action or pose at that instant, the distance between camera and subject, and the setting and background elements in view. Write it in that order: shot type first, then camera viewpoint, then the subject's short referring phrase, then the identity detail this shot band allows, then the action and placement, then the setting. Refer to each recurring subject by one short referring phrase of at most five words -- the same phrase the Motion: fields use, chosen the first time that subject appears and reused word for word in every later Image: and Motion: field, for example "the woman in grey" or "the red car". That phrase carries the subject's continuity; the identity words its shot band allows are written after it. A later panel has exactly three fields, in this order: Image:, Motion:, Narration: -- and no Style: line.

How much of the subject's appearance a later Image: field carries is decided by that panel's shot type and by nothing else. The rule is: write only the identity a viewer could actually resolve at that distance -- and write all of it, because the Style: line does not carry appearance and this field is the only place the subject's identity is stated. Too much identity in a distant shot is a contradiction the renderer resolves by moving the camera closer, which turns a wide shot into a portrait; too little in a near shot leaves the face unspecified, and the renderer invents a different person. The three bands are:
FAR BAND -- extreme wide shot, wide shot. At most 8 identity words after the referring phrase: overall build or height, and the dominant colour of the clothing. Nothing else. No hair texture, no hair length, no skin tone, no face, no eyes, no lips, no freckles, no markings, no fabric detail.
MID BAND -- medium shot, medium close-up. 10 to 20 identity words after the referring phrase: the garments and their colours, hair colour and length, and build. No face-feature detail -- no eye colour, no lip colour, no freckles, no skin texture.
NEAR BAND -- close-up, extreme close-up. 18 to 30 identity words after the referring phrase: skin tone, markings such as freckles or scars, eye colour, lip colour, hair colour and texture, and whatever garment is visible at the neckline. This is the only band that describes a face, and it is the band where writing too little is the bigger mistake.
The mid and near counts are ranges with a floor, not ceilings to stay under: a near-band panel that names only the referring phrase renders a stranger. The identity words come out of the same 45-70 words, not on top of them: a near-band panel has almost no setting left in frame, so the words it spends on the face are the words a far-band panel spends on the street.
```

### 5.4 Edit D — the `Style:` field template

**Find:**

```
Style: <40-70 words on a single line describing ONLY what is identical in every panel of this movie, taken from the attached image: the recurring subjects and their fixed appearance (wardrobe, colours, markings, distinguishing features), the materials and textures, the colour palette, the lighting character, and the rendering style, medium and lens character>
```

**Replace with:**

```
Style: <30-55 words on a single line describing ONLY the global look that every panel of this movie shares, taken from the attached image: the colour palette, the lighting character, the materials and surface textures of the setting, and the rendering style, medium and lens character. It must name NO person and NO subject attribute -- no hair, skin, face, eyes, lips, build, age, gender or wardrobe words -- because this line is appended unchanged to EVERY panel's image prompt, including the extreme wide shots where none of those could be resolved, and a face named in a wide shot's prompt drags the camera in.>
```

### 5.5 Edit E — the paragraph after the `Style:` template

**Find:**

```
Write the Style: line as a plain comma-separated list of attributes with no sentence subject: it is appended word for word to the end of every panel's image prompt, so it must read correctly after any panel's Image: text. It must not mention composition, framing, shot type, camera angle, viewpoint, pose, action, or where anything sits in the frame -- those change from panel to panel and each panel's own Image: field sets them.
```

**Replace with:**

```
Write the Style: line as a plain comma-separated list of attributes with no sentence subject: it is appended word for word to the end of every panel's image prompt, so it must read correctly after any panel's Image: text. It must not mention composition, framing, shot type, camera angle, viewpoint, pose, action, or where anything sits in the frame -- those change from panel to panel and each panel's own Image: field sets them. It must not mention the subject either -- who they are, their hair, skin, face, build, age, gender or clothing -- because those change in renderability from panel to panel, and each panel's own Image: field sets them, at its band's level of detail.
```

`It must not mention composition, framing, shot type, camera angle, viewpoint, pose, action`
is preserved exactly (`L30c`).

### 5.6 Edit F — `SEED_IMAGE_POSTFACE`, items 1 and 2

**Find** the whole of numbered items 1 and 2:

```
1. The VERBATIM-repetition rule applies only to a new recurring character or element you introduce later that is NOT visible in the attached image. For everything that IS visible in it, write the description once, in Panel 1's Image: field, put its fixed attributes in Panel 1's Style: line, and never describe it again -- not word for word and not reworded. No Image: field after Panel 1 may carry hair, skin, face, build, wardrobe, colour-palette, lighting-character or rendering-style words; those panels name their subject with the short referring phrase and nothing else.
2. The 70-90 word length applies to Panel 1's Image: field. Every later panel's Image: field is 45-70 words of composition only, in this order: shot type, camera viewpoint and height, the subject's referring phrase, the action and placement in frame, the setting and background.
```

**Replace with:**

```
1. The VERBATIM-repetition rule applies only to a new recurring character or element you introduce later that is NOT visible in the attached image. For everything that IS visible in it, the global look -- colour palette, lighting character, setting materials and textures, rendering style -- goes once into Panel 1's Style: line and is never described again -- not word for word and not reworded. No Image: field after Panel 1 may carry colour-palette, lighting-character or rendering-style words. The subject's appearance is NOT in the Style: line, so every later Image: field must state it: each names its subject with the short referring phrase and then adds the identity its shot band calls for -- far band (extreme wide shot, wide shot): at most 8 identity words, build and dominant clothing colour only, no face, no hair texture, no skin tone; mid band (medium shot, medium close-up): 10 to 20 identity words, garments and their colours, hair colour and length, build, and no face-feature detail; near band (close-up, extreme close-up): 18 to 30 identity words, and it is the only band that may describe a face. The mid and near counts have a floor: a close-up that names only the referring phrase renders a different person, because nothing else in the prompt says who this is.
2. The 70-90 word length applies to Panel 1's Image: field. Every later panel's Image: field is 45-70 words: composition first, then only the identity detail its shot band allows, in this order: shot type, camera viewpoint and height, the subject's referring phrase, the band's identity words, the action and placement in frame, the setting and background.
```

Preserved exactly: `Two of the rules above are overridden for this movie` (untouched line
above), `The VERBATIM-repetition rule applies only to a new recurring character or element you
introduce later that is NOT visible in the attached image.`, `not word for word and not
reworded` (once), `The 70-90 word length applies to Panel 1's Image: field.`, `45-70 words`,
and the unchanged trailing paragraphs including `Every other panel has exactly three, in this
order: Image:, Motion:, Narration: -- and no Style: line.` and the `Do not verify the file
with run_python or any other tool. Emit no other text.` terminator.

### 5.7 Edit G — the `require_style` violation message

In `_validate_story_md`, **find:**

```python
        violations.append(
            "panel 1: missing/empty Style: field, which --seed-image requires -- add one "
            "line to panel 1 after Narration:, naming only the recurring subjects' fixed "
            "appearance, materials, colour palette, lighting character and rendering style "
            "(no composition, framing or camera words)"
        )
```

**Replace with:**

```python
        violations.append(
            "panel 1: missing/empty Style: field, which --seed-image requires -- add one "
            "line to panel 1 after Narration:, naming only the global look: colour palette, "
            "lighting character, setting materials and textures, and rendering style, medium "
            "and lens character (no composition or camera words, and no subject, hair, skin, "
            "face, build or wardrobe words)"
        )
```

`missing/empty Style: field` is preserved, keeping both `L32a` rows green.

### 5.8 Not edited, deliberately

Do not touch: the preface's first two paragraphs; `This replaces the verbatim-repetition rule
below for everything that is visible in the attached image` / `The verbatim-repetition rule
below still applies to any NEW recurring character` (`L31c`, `L31d`); `Emit the Style: line
exactly once, in Panel 1, and never in any other panel.` and `The pipeline reads that line from
Panel 1 alone, so a Style: line written under Panel 2 or later is dead text that is never
read.` (`L30b`, `L35a`); `Panel 1, and only Panel 1, carries one extra field` (`L30b`);
`build_story_prompt` itself (`L25d` pins the exact assembly).

---

## 6. Change set 2 of 3 — `_style_content_warnings`

### 6.1 Edit — two new module-level objects

Insert **immediately after** `_style_echo_warnings`'s closing `return warnings` (currently
line 538) and **before** the `# ---` banner that follows it. Verbatim:

```python
# Subject-attribute tokens that must not appear in Panel 1's Style: line. The
# Style: text is appended unchanged to EVERY panel's image prompt (see
# bin/ltx-story-images _compose_prompt), so a face-level word in it is asserted
# over an extreme wide shot too, and the renderer reconciles the contradiction by
# moving the camera in -- the 2026-09-13 defect this list guards. Matched through
# _content_words, so the list is lowercase, alphabetic and 3+ characters, and
# matching is case- and punctuation-insensitive. Materials, palette, lighting and
# rendering-style words are deliberately absent: those ARE Style: content.
_STYLE_BANNED_TOKENS = frozenset("""
hair haired hairs hairline bald balding bangs fringe braid braided braids bun curls
curled curly ponytail dreadlocks updo
face faced facial cheek cheeks cheekbones chin jaw jawline brow brows eyebrow eyebrows
eyelash eyelashes eye eyes nose nostrils lip lips mouth teeth freckle freckles dimples
skin skinned complexion freckled blemish blemishes pores wrinkles scar stubble beard moustache
body build built physique figure muscular slender slim stocky athletic curvy petite tall
shoulders waist hips torso arms legs hands fingers neck
woman women man men girl boy person people young elderly aged teenage
wearing wears worn dressed clothing clothes wardrobe outfit garment garments shirt blouse
dress jacket coat trousers jeans skirt sweater
""".split())


def _style_content_warnings(panels):
    """Advisory warning about Panel 1's Style: line naming subject attributes.

    Returns [] or a single-element list; never raises, never fatal.

    The Style: line is the one piece of text bin/ltx-story-images appends to every
    panel's prompt unchanged, so it is the only place in the story where a word is
    asserted over every shot distance at once. Identity is distance-dependent --
    freckles and lip colour cannot be rendered on a forty-pixel-tall subject -- so a
    Style: line naming them contradicts every wide shot in the movie, and the
    renderer resolves that by closing the distance. Measured on the 2026-09-13
    reference Style: line, 8 of its content words are subject attributes; a
    compliant global-look line (palette, lighting, materials, render style) scores
    0 of 36.

    Advisory and not a _validate_story_md violation, for the same reason as
    _style_echo_warnings: violations are fatal with no override flag, and a token
    list must never be able to strand a legitimate story behind a word match.
    """
    if not panels:
        return []
    hits = sorted(_content_words(panels[0].get("style", "")) & _STYLE_BANNED_TOKENS)
    if not hits:
        return []
    return [
        "panel 1: Style: names %d subject-level attribute word(s) (%s) -- the Style: text is "
        "appended unchanged to EVERY panel's image prompt, including the extreme wide shots "
        "where a face cannot be resolved, so appearance words here fight each wide panel's own "
        "shot type and pull the camera in; move them into the Image: fields of the panels whose "
        "shot band can actually show them"
        % (len(hits), ", ".join(hits))
    ]
```

Exact behaviour, pinned:
- `panels == []` → `[]`.
- `panels[0]` with no `"style"` key → `[]` (the `.get` default).
- `panels[0]["style"] == ""` → `[]`.
- one or more hits → a list of **exactly one** string, beginning `panel 1: Style: names `.
- **all** hits are listed, sorted, comma-space joined — not truncated. (This differs
  deliberately from `_style_echo_warnings`'s `[:8]`: that function reports an overlap that can
  run to 40 words; this one reports the words to delete, and a truncated list would leave the
  author guessing.)
- Only `panels[0]` is inspected. A banned token in panel 2's `Style:`, or in any `Image:`
  field, is ignored — those are legitimate (§5.3) or already covered by `_style_echo_warnings`.

### 6.2 Why this is not a `_validate_story_md` violation

Restating §3.5 for the executor: do **not** add a `require_style`-style violation for banned
content, do **not** add an override flag, and do **not** make the warning conditional on
`--no-review`. `_validate_story_md`'s return contract is "the list of FATAL violations" and
`L32`/`L37c` pin it.

### 6.3 Edit — the call site in `phase1_story`

**Find** (currently lines 753-758):

```python
    # Advisory only -- never changes the return code (see _style_echo_warnings).
    # Printed after the story dump so a human reviewing it sees these immediately
    # above the prompt they are about to answer, and printed under --no-review too
    # so they land in movie.log.
    for warning in _style_echo_warnings(_load_story_panels(story_md)):
        print("Warning: %s" % warning)
```

**Replace with:**

```python
    # Advisory only -- never changes the return code (see _style_echo_warnings).
    # Printed after the story dump so a human reviewing it sees these immediately
    # above the prompt they are about to answer, and printed under --no-review too
    # so they land in movie.log. The content warning goes first: a Style: line that
    # names the subject is the upstream cause, the per-panel echo is the symptom.
    # _load_story_panels is deliberately called twice rather than hoisted -- the
    # hoist would churn the exact-text guards L37a/L37b for one markdown re-read.
    for warning in _style_content_warnings(_load_story_panels(story_md)):
        print("Warning: %s" % warning)
    for warning in _style_echo_warnings(_load_story_panels(story_md)):
        print("Warning: %s" % warning)
```

The `_style_echo_warnings` loop's two lines and their 4-space indentation are byte-identical to
today's, so `L37a` and `L37b` stay green.

### 6.4 Why `L36`'s `_ECHO_STYLE` fixture stays as it is

`_ECHO_STYLE` (`young woman with tightly curled auburn-red hair, …`) now describes a
*non-compliant* `Style:` line. Leave it. It is a fixture for overlap arithmetic, not a model of
the convention, and `L36` exercises `_style_echo_warnings`, which this spec does not change.
It also earns a second job: `L38` reuses it as the positive fixture for
`_style_content_warnings`, so the same string demonstrates both the old defect and the new
detector. Do not edit, rename or re-comment it.

---

## 7. Change set 3 of 3 — `tests/test_ltx_movie_offline.py`

### 7.1 The six pre-existing check rows that change (and the only ones)

Change the literal string in each row. Do not change the check name prefix, the surrounding
code, or any other row. Any seventh pre-existing row going red means an edit in §5 was not
made verbatim — fix §5, not the test.

| # | Check | Old literal | New literal |
| --- | --- | --- | --- |
| 1 | `L30b` | `"40-70 words on a single line"` | `"30-55 words on a single line"` |
| 2 | `L34d` | `"Every later panel's Image: field is 45-70 words of composition only"` | `"Every later panel's Image: field is 45-70 words: composition first, then only the identity detail its shot band allows"` |
| 3 | `L35a` | `"and do not restate its content in your own words either"` | `"and do not carry more identity detail than that panel's shot distance can actually resolve"` |
| 4 | `L35a` | `"Appearance, wardrobe, hair, skin, face, build, materials, colour palette, lighting character and rendering style must not be described again in any Image: field after Panel 1"` | `"Materials, colour palette, lighting character and rendering style must not be described again in any Image: field after Panel 1"` |
| 5 | `L35a` | `"That phrase is the only appearance detail a later Image: field may carry."` | `"That phrase carries the subject's continuity; the identity words its shot band allows are written after it."` |
| 6 | `L35a` | `"shot type first, then camera viewpoint, then the subject's short referring phrase, then the action and placement, then the setting"` | `"shot type first, then camera viewpoint, then the subject's short referring phrase, then the identity detail this shot band allows, then the action and placement, then the setting"` |

Row 4 keeps its multi-line implicit-concatenation form; re-wrap the new literal to fit the
file's existing line width. Rows 3, 5, 6 are entries in `L35a`'s `for phrase in (...)` tuple —
the tuple's length is unchanged, so `TOTAL` does not move.

Explicitly unchanged and expected green: `L25a`-`L25f`, `L30a`, `L30c`, `L30d`, `L30e`,
`L31a`-`L31e`, `L32a`-`L32e`, `L33a`-`L33b`, `L34a`-`L34c`, `L34e`, `L34f`, `L35b`-`L35e`,
all of `L36`, all of `L37`.

`L35e` deserves a note: it asserts `p_on.count("not word for word and not reworded") == 3`.
§5.2 keeps one occurrence in the preface and §5.6 keeps one in the postface; the template's is
untouched. If `L35e` goes red, an edit dropped or duplicated the phrase.

### 7.2 Where the new code goes

Append `L38` after `L37`'s `test_style_echo_call_site_guard` and before the
`if __name__ == "__main__":` block; `L39` after `L38`. Match the file's banner-comment style:

```python
# ---------------------------------------------------------------------------
# L38: _style_content_warnings -- the advisory subject-attribute check on Style:
# ---------------------------------------------------------------------------
```

### 7.3 New module-level fixtures

Place immediately above `L38`'s banner:

```python
# A compliant global-look Style: line: palette, lighting, setting materials, render
# style -- and no subject. 39 words / 36 content words, so it is comfortably inside
# the 30-55 word budget and well above _ECHO_MIN_STYLE_WORDS (the echo check stays
# engaged on it).
_BAND_GOOD_STYLE = ("muted teal and amber palette, desaturated shadows, soft overcast key "
                    "light from camera left, low contrast, damp asphalt and weathered brick "
                    "textures, painted metal railings, clean high-resolution photographic "
                    "rendering, 35mm lens character, shallow depth of field, fine natural "
                    "grain")
# The exact 8 tokens _ECHO_STYLE (the pre-fix reference Style: line) trips.
_BAND_ECHO_STYLE_HITS = ["curled", "eyes", "freckles", "hair", "lips", "skin", "woman", "young"]
```

Both numbers are measured, not estimated: `_content_words(_BAND_GOOD_STYLE)` has 36 elements
and 0 banned hits; `_content_words(_ECHO_STYLE) & _STYLE_BANNED_TOKENS` is exactly
`_BAND_ECHO_STYLE_HITS`.

### 7.4 New test `L38` — `_style_content_warnings` (9 check rows)

```python
def test_style_content_warnings():
```

**Exactly 9 `check(...)` calls, one per lettered row below** (same rule as §7.5: a row listing
several conditions is one `and`-combined `check`, never a loop). Rows, in this order and with
these exact names:

- **`L38a`** — `len(ltx_movie._STYLE_BANNED_TOKENS) == 109`. Detail on failure: the actual
  length. (The count is the guard against a token being dropped or duplicated in the
  triple-quoted block.)
- **`L38b`** — the list is disjoint from `_ECHO_STOPWORDS`. A token that is also a stopword can
  never match, because `_content_words` strips stopwords first.

  **REVISED 2026-09-13 (see §7.8). Write it exactly as below — do not call `.isdisjoint()` or
  `&` directly on `_STYLE_BANNED_TOKENS`:**

  ```python
      _banned_as_set = set(ltx_movie._STYLE_BANNED_TOKENS)
      check("L38b _STYLE_BANNED_TOKENS is disjoint from _ECHO_STOPWORDS",
            _banned_as_set.isdisjoint(ltx_movie._ECHO_STOPWORDS),
            "intersection: %r"
            % (_banned_as_set & set(ltx_movie._ECHO_STOPWORDS)))
  ```

  Both the condition **and** the detail argument must go through `_banned_as_set`: Python
  evaluates the detail eagerly, so a bare `_STYLE_BANNED_TOKENS & ...` crashes on a non-set
  container even when the condition would not. This keeps `L38b` a pure statement about
  *contents*, leaving container *type* to `L38c` alone.
- **`L38c`** — `isinstance(ltx_movie._STYLE_BANNED_TOKENS, frozenset)` **and** every token
  satisfies `t.isalpha() and t.islower() and len(t) > 2`. Detail: the offending tokens. A token
  failing any of these can never match through `_content_words`.
- **`L38d`** — `_style_content_warnings(_echo_panels(_ECHO_STYLE, [_ECHO_GOOD_IMAGE]))` returns
  a one-element list and that string contains every token in `_BAND_ECHO_STYLE_HITS`, and
  contains `"names 8 subject-level attribute word(s)"`.
- **`L38e`** — the same call returns **exactly one** warning (`len(w) == 1`) and it starts with
  `"panel 1: Style: names "` and contains `"extreme wide shots"` and `"pull the camera in"`.
- **`L38f`** — `_style_content_warnings(_echo_panels(_BAND_GOOD_STYLE, [_ECHO_GOOD_IMAGE])) == []`.
  The compliant line is silent.
- **`L38g`** — `_style_content_warnings` returns `[]` for an empty list, a panel with no
  `style` key, and a panel with an empty `style`. Nothing raises.

  **REVISED 2026-09-13 (see §7.9). Write it exactly as below.** A bare call cannot express
  "never raises": an exception inside a `check(...)` condition propagates before `check` is
  entered, killing the run. The helper converts a raise into an ordinary red check. Still
  **one** `check(...)` call, so `TOTAL` is unchanged.

  ```python
      def _never_raises(panels):
          """_style_content_warnings' contract is "returns [], never raises". A bare
          call here cannot express that: an exception in a check()'s condition
          argument propagates before check() is ever entered, killing the run and
          suppressing both the OK n/n summary and every later row. Catching it turns
          a raise into an ordinary red check."""
          try:
              return ltx_movie._style_content_warnings(panels)
          except Exception as exc:
              return "raised %s: %s" % (type(exc).__name__, exc)

      _g_cases = ([], [{"number": 1, "image": "x"}],
                  [{"number": 1, "image": "x", "style": ""}])
      check("L38g never raises on an empty panel list or a missing/empty style key",
            all(_never_raises(c) == [] for c in _g_cases),
            "got %r" % ([_never_raises(c) for c in _g_cases],))
  ```
- **`L38h`** — case- and punctuation-insensitivity: a panel-1 style of
  `"Young Woman With Auburn HAIR And Freckled SKIN, teal palette"` produces exactly one
  warning naming `freckled, hair, skin, woman, young`.

  **REVISED 2026-09-13 (see §7.9): build the fixture with `_echo_panels`, not as a bare
  one-element list.** A one-element fixture cannot survive a `panels[0]` → `panels[1]`
  mutation — it raises `IndexError` and kills the run instead of going red.

  ```python
      # Built with _echo_panels (two panels) rather than a bare one-element list: a
      # one-element fixture cannot survive a panels[0]->panels[1] mutation, so it
      # crashed the run instead of letting the row's own checks go red (see the
      # spec's Q-6 finding). Panel 1 still carries the mixed-case Style: text, which
      # is what this row is actually about.
      w_case = ltx_movie._style_content_warnings(_echo_panels(
          "Young Woman With Auburn HAIR And Freckled SKIN, teal palette",
          [_ECHO_GOOD_IMAGE]))
  ```

  The `check(...)` call itself is unchanged.
- **`L38i`** — only panel 1 is inspected: with `_BAND_GOOD_STYLE` on panel 1 and `_ECHO_STYLE`
  on panel 2 (via `_echo_panels(..., styles={2: _ECHO_STYLE})`) and `_ECHO_BAD_IMAGE` as a
  later `Image:`, the result is `[]`.

Reuse the existing `_echo_panels` helper; do not write a second one.

### 7.5 New test `L39` — the band contract and the call site (10 check rows)

```python
def test_band_prompt_and_content_call_site():
```

Binds `p_on = ltx_movie.build_story_prompt("n", "sid", 5, False, True)`,
`p_off = ltx_movie.build_story_prompt("n", "sid", 5)`, `pre = ltx_movie.SEED_IMAGE_PREFACE`,
`post = ltx_movie.SEED_IMAGE_POSTFACE`, and `text = open(_SCRIPT_PATH).read()`.

**Exactly 10 `check(...)` calls, one per lettered row below.** Rows that list several phrases
(`L39d`, `L39e`, `L39f`, `L39h`, `L39i`) are a **single** `check(...)` whose condition
`and`-combines them — not a `for phrase in (...)` loop, which would emit one row per phrase and
break SC1's `OK 309/309`. Pass the failing phrase list as the `detail` argument so a failure is
still diagnosable.

- **`L39a`** — the call-site loop appears exactly once, at function indent:
  `text.count('    for warning in _style_content_warnings(_load_story_panels(story_md)):\n        print("Warning: %s" % warning)\n') == 1`.
- **`L39b`** — it is not nested: `'        for warning in _style_content_warnings(' not in text`.
  Detail: "the loop must be at function indent, so --no-review runs still log it".
- **`L39c`** — it is advisory, not fatal: `"_style_content_warnings"` does not appear in the
  body of `_validate_story_md` (same slicing technique as `L37c`:
  `text.split("def _validate_story_md")[1].split("return violations")[0]`).
- **`L39d`** — the `Style:` template carries the boundary: `pre` contains
  `"30-55 words on a single line"`, `"It must name NO person and NO subject attribute"`, and
  `"It must not mention the subject either"`.
- **`L39e`** — the three band headings and their budgets are present in `pre`, each exactly
  once: `"FAR BAND -- extreme wide shot, wide shot."` / `"At most 8 identity words"`,
  `"MID BAND -- medium shot, medium close-up."` / `"10 to 20 identity words"`,
  `"NEAR BAND -- close-up, extreme close-up."` / `"18 to 30 identity words"`.
- **`L39f`** — the rationale sentences are present in `pre`, **both** directions of the
  trade-off: `"write only the identity a viewer could actually resolve at that distance"`,
  `"which turns a wide shot into a portrait"`,
  `"the renderer invents a different person"`,
  `"This is the only band that describes a face"`, and
  `"The mid and near counts are ranges with a floor, not ceilings to stay under"`.
- **`L39g`** — the budget is shared, not additive: `pre` contains
  `"The identity words come out of the same 45-70 words, not on top of them"`.
- **`L39h`** — the postface restates all three bands:
  `"far band (extreme wide shot, wide shot): at most 8 identity words"`,
  `"mid band (medium shot, medium close-up): 10 to 20 identity words"`,
  `"near band (close-up, extreme close-up): 18 to 30 identity words"`, and the floor sentence
  `"The mid and near counts have a floor"` all in `post`.
- **`L39i`** — no leakage into the unseeded prompt: none of `"FAR BAND"`, `"MID BAND"`,
  `"NEAR BAND"`, `"30-55 words"`, `"identity words"` appears in `p_off`.
- **`L39j`** — the banned-content language is in the assembled seeded prompt exactly where
  expected: `p_on.count("30-55 words on a single line") == 1` and
  `p_on.count("FAR BAND") == 1` and `p_on.startswith(pre)` and `p_on.endswith(post)`.

### 7.6 `__main__` registration

Add, in this order, after `test_style_echo_call_site_guard()`:

```python
    test_style_content_warnings()
    test_band_prompt_and_content_call_site()
```

### 7.7 Mutation table (SC3) — 20 rows

Apply each mutation to a clean tree, run `python3 tests/test_ltx_movie_offline.py`, record the
FAIL lines and the non-zero rc, revert, confirm `OK 309/309`. Capture `rc` **before** any pipe.

| # | Mutation | Expected | Checks that go red |
| --- | --- | --- | --- |
| Q-1 | Delete the token `hair` from `_STYLE_BANNED_TOKENS` | `rc=1`, `OK 306/309` | `L38a`, `L38d`, `L38h` |
| Q-2 | Add the token `the` to `_STYLE_BANNED_TOKENS` | `rc=1`, `OK 307/309` | `L38a`, `L38b` (detail `intersection: {'the'}`) |
| Q-3 | Change `frozenset("""` to `set("""` | `rc=1`, `OK 308/309` | `L38c` only (detail `offending tokens: []` — the `isinstance` clause, not the shape clause) |
| Q-4 | Change the list's first token from `hair` to `ha` | `rc=1`, `OK 306/309` | `L38c` (detail `offending tokens: ['ha']`), `L38d`, `L38h` |
| Q-5 | Insert `return []` immediately after the `if not panels:` guard | `rc=1`, `OK 306/309` | `L38d`, `L38e`, `L38h` |
| Q-6 | In `_style_content_warnings` **only**, change `panels[0]` to `panels[1]` (anchor on `hits = sorted(`; the identical expression at line 520 in `_style_echo_warnings` must NOT be touched) | `rc=1`, `OK 304/309` | `L38d`, `L38e`, `L38g`, `L38h`, `L38i` |
| Q-7 | Delete its `if not panels: return []` guard | `rc=1`, `OK 308/309` | `L38g` only |
| Q-8 | Return one warning per hit: replace `% (len(hits), ", ".join(hits))` with `% (len(hits), h) for h in hits` | `rc=1`, `OK 306/309` | `L38d`, `L38e`, `L38h` |
| Q-9 | Replace `_content_words(panels[0].get("style", ""))` with `set(panels[0].get("style", "").split())` (same `hits = sorted(` anchor as Q-6) | `rc=1`, `OK 307/309` | `L38d`, `L38h` |
| Q-10 | Delete the `_style_content_warnings` loop from `phase1_story` | `rc=1`, `OK 308/309` | `L39a` |
| Q-11 | Indent that loop inside an `if not args.no_review:` block | `rc=1`, `OK 307/309` | `L39a`, `L39b` |
| Q-12 | Add `violations.extend(_style_content_warnings(panels))` before `_validate_story_md`'s `return violations` | `rc=1`, `OK 308/309` | `L39c` |
| Q-13 | Revert the `Style:` budget in §5.4 to `40-70 words on a single line` | `rc=1`, `OK 306/309` | `L30b`, `L39d`, `L39j` |
| Q-14 | Delete the clause `It must name NO person and NO subject attribute` from §5.4 | `rc=1`, `OK 308/309` | `L39d` |
| Q-15 | Change the FAR band cap `At most 8 identity words` to `At most 30 identity words` | `rc=1`, `OK 308/309` | `L39e` |
| Q-16 | Change the NEAR band budget `18 to 30 identity words` to `At most 30 identity words` (drops the floor) | `rc=1`, `OK 308/309` | `L39e` |
| Q-17 | **Delete the entire `NEAR BAND --` line** from the preface. Deleting only part of it, or prefixing a character, does **not** work — the asserted substring survives inside the longer string and the suite stays green (verified) | `rc=1`, `OK 307/309` | `L39e`, `L39f` |
| Q-18 | Revert §5.3's order sentence to the Step 2 wording (drop `, then the identity detail this shot band allows`) | `rc=1`, `OK 308/309` | `L35a` (order row) |
| Q-19 | Revert **both** §5.1's final clause and §5.3's `That phrase carries…` sentence | `rc=1`, `OK 307/309` | `L35a` ×2 (rows 3 and 5) |
| Q-20 | Revert **both** §5.6 item 2's sentence and §5.2's first sentence | `rc=1`, `OK 307/309` | `L34d`, `L35a` (row 4) |

Q-19 and Q-20 are two-edit mutations; apply both edits of the row together and expect both
named rows red. Every other row is a single edit.

### 7.8 Finding: the original Q-3 (`frozenset` → `tuple`) was an invalid mutation

Raised by `code-executor` during the first mutation walk, and **confirmed by reproduction**.
This section records the resolution so the row is never reinstated.

**What the original row claimed.** "Change `frozenset(...)` to `tuple(...)` … (membership still
works) → `L38c`."

**What actually happens.** Reproduced against the implemented files (`OK 309/309` before
mutation):

```
PASS L38a _STYLE_BANNED_TOKENS has exactly 109 tokens
Traceback (most recent call last):
  File "tests/test_ltx_movie_offline.py", line 1390, in test_style_content_warnings
    ltx_movie._STYLE_BANNED_TOKENS.isdisjoint(ltx_movie._ECHO_STOPWORDS),
AttributeError: 'tuple' object has no attribute 'isdisjoint'
```

`rc=1`, but **no `OK n/n` summary line is printed at all**, and `L38c` — the row the mutation
names — never executes. Neither do `L38d`..`L39j`. The mutation's observable effect is "the
harness dies", which is a strictly less informative signal than a named red check and is the
same class of false-signal this project has been bitten by before.

**Two independent defects, both fixed:**

1. *Ordering hazard in the test.* `L38b` called a set-specific method on the object whose type
   `L38c` is responsible for asserting, so `L38b` crashed first and masked every later row.
   Fixed by §7.4's revised `L38b` (option (b)) — a **real test-code change**, not a doc fix.
2. *The mutation itself was unusable.* Fixing `L38b` is **provably insufficient**. Verified: with
   the revised `L38b` in place, the `tuple` mutation gets `L38c` to fail cleanly and then
   crashes anyway at `L38d`, inside production code:

   ```
   FAIL L38c ... offending tokens: []
   File "bin/ltx-movie", line 590, in _style_content_warnings
       hits = sorted(_content_words(...) & _STYLE_BANNED_TOKENS)
   TypeError: unsupported operand type(s) for &: 'set' and 'tuple'
   ```

   The container type is **load-bearing at runtime** (line 590 intersects it with a `set`), not
   merely a style assertion, so no amount of test-side defensiveness makes `tuple` a clean
   mutation. It was replaced (option (c)) by `frozenset("""` → `set("""`, which a `set`
   satisfies at runtime in every respect except `isinstance(..., frozenset)`.

**Verification of the replacements** (each applied alone to the implemented files, then
reverted):

| Mutation | Result | Evidence |
| --- | --- | --- |
| Q-3 `frozenset(` → `set(` | `rc=1`, `OK 308/309`, suite completes | Exactly `FAIL L38c … offending tokens: []` — the empty list proves the `isinstance` clause fired, not the shape clause |
| Q-4 `hair` → `ha` | `rc=1`, `OK 306/309`, suite completes | `FAIL L38c … offending tokens: ['ha']` (shape clause), plus `L38d`, `L38h` — the token is no longer matchable |
| Q-2 `the` added, against the **revised** `L38b` | `rc=1`, `OK 307/309` | `FAIL L38a … got 110` and `FAIL L38b … intersection: {'the'}` — the revised detail argument still reports correctly |
| Revised `L38b`, no mutation | `OK 309/309` | Type-agnostic rewrite is behaviour-preserving on the clean tree |

Q-4 is new: `L38c` asserts **two** clauses (container type, token shape) and the original table
covered neither in isolation. Each clause now has its own mutation, and each fails with a
distinguishing `offending tokens:` detail.

**Why not option (a)** (accept the crash and redescribe the row): it would leave `L38c`'s
`isinstance` clause covered by no mutation at all — the clause could be deleted and the table
would stay green — and it would normalise a mutation that suppresses the suite's summary line
and 20+ later checks. SC3's contract is "makes the named check(s) FAIL", not "makes the
interpreter exit".

#### 7.8.1 Action required from `code-executor`

Three changes, all in `tests/test_ltx_movie_offline.py`. **`bin/ltx-movie` is not touched** —
no production change is needed or wanted here.

1. **Replace the body of `L38b`** with the four-line form in §7.4 (introduce the
   `_banned_as_set` local; use it in both the condition and the detail). This is the only edit
   to already-implemented test code. `TOTAL` is unchanged — `_banned_as_set = ...` is an
   assignment, not a `check(...)` — so the suite must still print `OK 309/309` on a clean tree.
   Confirm that before proceeding.
2. **Resume the mutation walk from the revised table**, which is now 20 rows. Rows Q-1 and Q-2
   are already done and unaffected except that Q-2 must be re-run against the revised `L38b`
   (expected: `OK 307/309`, `L38a` + `L38b` red, detail `intersection: {'the'}`).
3. **Do not apply the old `tuple` mutation at all.** It is retired, not deferred. If any row
   ever crashes the harness instead of printing `OK n/n` with named red checks, stop and report
   it exactly as you did here — that is the correct response, not a nuisance.

### 7.9 Full mutation walk performed by the spec author — all 20 rows, empirically

After the same failure shape appeared a third time (Q-6), every row was applied for real
against the implemented files rather than reasoned about. The walk used a scripted
apply → run → record → restore loop with a SHA-256 integrity assertion after each restore.
**Baseline before and after the walk: `rc=0`, `OK 309/309`.**

#### 7.9.1 Two further test defects found and fixed

Both are test-side; **`bin/ltx-movie` needs no change**.

1. **`L38g` could not fail cleanly (breaks Q-7, contributes to Q-6).** It asserted
   "never raises" with a bare call, but an exception in a `check(...)` condition propagates
   before `check` is entered. Under Q-7 the run died with `IndexError` and printed no summary.
   Fixed by §7.4's `_never_raises` helper. After the fix Q-7 is `rc=1`, `OK 308/309`, exactly
   `L38g` red.
2. **`L38h`'s fixture was a one-element panel list (breaks Q-6).** With `panels[0]` mutated to
   `panels[1]` it raised `IndexError` at `bin/ltx-movie:590`, killing the run *after* `L38g`
   had already gone red. Fixed by building it with `_echo_panels` (§7.4). After the fix Q-6 is
   `rc=1`, `OK 304/309`, with its named target `L38i` reached and red.

The generalisable rule, now three-for-three: **a fixture that is smaller than the shape the
production function indexes into cannot survive an index mutation.** `L38g` is the one row that
legitimately passes short lists, which is exactly why it is the row that must be
exception-safe.

#### 7.9.2 Row expectations corrected against measurement

| Row | Previously claimed | Actually observed |
| --- | --- | --- |
| Q-6 | `L38d`, `L38e`, `L38i` | `L38d`, `L38e`, `L38g`, `L38h`, `L38i` (after the two fixes) |
| Q-8 | `L38e`, `L38h` | `L38d`, `L38e`, `L38h` |
| Q-9 | `L38h` | `L38d`, `L38h` |

Two mutation *definitions* were also found to be under-specified and are now pinned in the
table itself:

- **Q-6 / Q-9** — `_content_words(panels[0].get("style", ""))` appears **twice** in
  `bin/ltx-movie` (line 520 in `_style_echo_warnings`, line 590 in `_style_content_warnings`).
  An unanchored replace hits both. Both rows now specify the `hits = sorted(` anchor.
- **Q-17** — prefixing or partially editing the `NEAR BAND` line leaves the asserted substring
  intact inside the longer string, and the suite stays **green** (`rc=0`, `OK 309/309`,
  verified). The row now requires deleting the whole line. This was a live false-negative: as
  originally worded the row proved nothing.

#### 7.9.3 Result — every row walked, no crashes

All 20 rows produce `rc=1`, a printed `OK n/n` summary, and their named checks red. No row
crashes the harness; no row is green. The per-row `Expected` column in §7.7 is transcribed
from this run, so any future deviation is a real regression rather than a stale estimate.

#### 7.9.4 Action required from `code-executor` (supersedes §7.8.1 item 2)

1. Apply the revised **`L38g`** (§7.4) and the revised **`L38h` fixture** (§7.4). Both are in
   `tests/test_ltx_movie_offline.py`; neither changes `TOTAL`. Confirm `OK 309/309` on a clean
   tree before walking anything.
2. Then walk §7.7's 20 rows, checking each against its `Expected` column. The mutation
   definitions in that table are exact — use the given anchors, especially for Q-6, Q-9 and
   Q-17.
3. Rows Q-1..Q-5 and Q-7..Q-20 need no further investigation; they are confirmed. Report any
   deviation from the `Expected` column rather than adjusting the table.

---

## 8. Acceptance

Run from `/Users/reubenpatterson/local_model_harness/qwen-agent-workspace`. `$SCRATCH` is the
session scratchpad directory.

### A0 — record the baseline BEFORE editing anything

```
python3 tests/test_ltx_movie_offline.py; rc=$?; echo "rc=$rc"
git status --porcelain bin/ltx-movie tests/test_ltx_movie_offline.py
cp bin/ltx-movie "$SCRATCH/ltx-movie.BEFORE"
cp tests/test_ltx_movie_offline.py "$SCRATCH/test_ltx_movie_offline.py.BEFORE"
```

Expect `rc=0` and `OK 290/290`. If the count is not 290, **stop and report** — the tree is not
the one this spec was written against.

`generated/stories/drift_red_test/` is Step 2's evidence. Do not delete it, do not regenerate
it, and do not pass `--story-id drift_red_test` anywhere in this spec's acceptance.

### A1 — offline suites (SC1, SC2)

```
python3 tests/test_ltx_movie_offline.py; rc=$?; echo "rc=$rc"
python3 tests/test_ltx_story_images.py; rc=$?; echo "rc=$rc"
python3 tests/test_ltx_story_video.py; rc=$?; echo "rc=$rc"
python3 tests/test_ltx_chain.py; rc=$?; echo "rc=$rc"
python3 tests/test_ltx_mlx_render.py; rc=$?; echo "rc=$rc"
```

Capture `rc` **before** any pipe — `… | tail` reports tail's status, not the suite's. Report
each `rc` and each `OK n/n`. The first must read `OK 309/309`.

### A2 — mutation table (SC3)

Walk all 20 rows of §7.7 one at a time. Report per row: the mutation applied, the exact FAIL
check names observed, the non-zero rc, and confirmation the suite returned to `OK 309/309`
after revert.

### A3 — the real end-to-end rerun. **Do not run without the user's explicit go-ahead.**

Requires the 27B server (`ailexleon/Huihui-Qwen3.8-27B-abliterated-mlx-6Bit` via
`mlx_vlm.server` at 127.0.0.1:8177) and the Z-Image stack. Phase 4 is hours of GPU time and
proves nothing here — the driver aborts before it.

#### A3.1 — fresh story-id

`band_red_test`. Fresh, not `drift_red_test`, so Step 2's story.md and stills survive untouched
for the before/after comparison and so `--force-story` cannot destroy them.

#### A3.2 — the driver

Write to `"$SCRATCH/run_a3.py"` verbatim, then `python3 "$SCRATCH/run_a3.py"`:

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
    "--story-id band_red_test --seed-image /Users/reubenpatterson/Downloads/red.jpg "
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

The narrative is byte-identical to Step 2's on purpose: same subject, same shot mix, only the
story-id differs, so the two runs are comparable.

#### A3.3 — machine checks (SC4, SC5, SC6, SC7, SC9)

```
grep -c 'Warning: panel 1: Style: names' "$SCRATCH/movie_a3.log"        # SC4: must be 0
grep -c 'Warning: panel .*: Image: restates' "$SCRATCH/movie_a3.log"    # SC5: must be 0
grep -c '^Style: ' generated/stories/band_red_test/story.md             # SC9: report only
```

Then write `"$SCRATCH/measure_a3.py"` verbatim and run
`python3 "$SCRATCH/measure_a3.py" generated/stories/band_red_test/story.md`:

```python
import importlib.machinery, os, sys

WS = "/Users/reubenpatterson/local_model_harness/qwen-agent-workspace"
ltx = importlib.machinery.SourceFileLoader(
    "ltx_movie", os.path.join(WS, "bin", "ltx-movie")).load_module()

FAR = ("extreme wide shot", "wide shot")
MID = ("medium close-up", "medium shot")
NEAR = ("extreme close-up", "close-up")
FACE = set("freckle freckles freckled eye eyes lip lips cheek cheeks chin jaw jawline nose "
           "teeth complexion pores".split())
# (floor, ceiling) on the count of _STYLE_BANNED_TOKENS in a panel's Image: field.
# Measured basis (spec section 9.2): compliant far/mid/near score 5/6/12; far_over
# scores 11 and breaks composition; near_under scores 3 and breaks identity.
BAND = {"FAR": (0, 7), "MID": (4, 12), "NEAR": (6, 10 ** 6)}


def band(image_text):
    head = image_text.strip().lower()
    for name, prefixes in (("FAR", FAR), ("MID", MID), ("NEAR", NEAR)):
        for p in prefixes:
            if head.startswith(p) or head.startswith("a " + p) or head.startswith("an " + p):
                return name
    return "UNKNOWN"


path = sys.argv[1]
panels = ltx._load_story_panels(path)
style = panels[0].get("style", "") if panels else ""
sw = ltx._content_words(style)
banned_in_style = sorted(sw & ltx._STYLE_BANNED_TOKENS)
print("style words=%d  banned_in_style=%d %s" % (len(sw), len(banned_in_style), banned_in_style))
print("style word count (raw)=%d" % len(style.split()))
fails = []
for p in panels[1:]:
    img = p["image"]
    b = band(img)
    words = ltx._content_words(img)
    hits = sorted(words & ltx._STYLE_BANNED_TOKENS)
    face_hits = sorted(words & FACE)
    n = len(img.split())
    ok_words = 45 <= n <= 70
    lo, hi = BAND.get(b, (0, -1))
    ok_hi = b != "UNKNOWN" and len(hits) <= hi
    ok_lo = b != "UNKNOWN" and len(hits) >= lo
    ok_face = not (b == "FAR" and face_hits)
    print("panel %s band=%-7s words=%-3d identity_hits=%-2d (band %s..%s) %s face_hits=%s "
          "%s%s%s%s"
          % (p["number"], b, n, len(hits), lo, "-" if hi > 1000 else hi, hits[:6], face_hits,
             "" if ok_words else "[WORDS]", "" if ok_hi else "[OVER-SPECIFIED]",
             "" if ok_lo else "[UNDER-SPECIFIED]", "" if ok_face else "[FACE]"))
    if not (ok_words and ok_hi and ok_lo and ok_face):
        fails.append(p["number"])
print("FAILING PANELS:", fails)
```

Pass conditions:
- **SC4**: `banned_in_style` is `[]` and the log grep is `0`.
- **SC5**: the `Image: restates` grep is `0`.
- **SC6**: every `words=` is 45-70; at most one panel outside, none above 85.
- **SC7**: no `[OVER-SPECIFIED]`, `[UNDER-SPECIFIED]` or `[FACE]` marker on any panel;
  `band=UNKNOWN` on any panel is a **failure** (it means the `Image:` field did not open with
  one of the six shot types, which §5.3 requires). `[OVER-SPECIFIED]` on a far-band panel is
  the §9.2 `far_over` failure (composition collapses); `[UNDER-SPECIFIED]` on a near-band panel
  is the §9.2 `near_under` failure (identity drifts to another person). Both are real,
  photographed failure modes, not theoretical ones.
- **SC9**: report `grep -c '^Style: '` whatever it is.

Report the script's full output as a table in the result. Also paste the authored `Style:` line
verbatim — it is the single most diagnostic artefact of this change.

#### A3.4 — human eyeball (SC8)

Open `generated/stories/band_red_test/images/` next to
`generated/stories/drift_red_test/images/` and `~/Downloads/red.jpg`. Answer both halves
separately and in writing:

(a) Does each panel whose `Image:` says *wide shot* / *extreme wide shot* actually render wide?
(b) Is the subject in the mid- and near-band panels still recognisably the person in
`red.jpg`?

If (a) passes and (b) fails, **report and stop.** Do not widen the bands, do not restore
appearance words to `Style:`, do not iterate. That outcome means the identity/composition
trade needs a different mechanism than prompt text and belongs in a new spec.

---

## 9. Verification performed while authoring this spec

### 9.1 Static checks against the working tree

Everything below was executed against the working tree, not estimated:

- `python3 tests/test_ltx_movie_offline.py` → `rc=0`, `OK 290/290`.
- `_style_content_warnings` and `_STYLE_BANNED_TOKENS` are absent from both files
  (`grep -c` → 0); `L38` / `L39` are absent.
- All six §7.1 target substrings occur **exactly once** in `SEED_IMAGE_PREFACE` /
  `SEED_IMAGE_POSTFACE` today.
- `not word for word and not reworded` occurs once each in the template, preface and postface
  (`L35e`'s 3).
- The §6.1 token block: 109 whitespace-separated tokens, 109 unique (0 duplicates), all
  `isalpha()` + `islower()` + `len > 2`, and `isdisjoint(_ECHO_STOPWORDS)` → `True`.
- `_content_words(_ECHO_STYLE) & _STYLE_BANNED_TOKENS` → exactly
  `['curled', 'eyes', 'freckles', 'hair', 'lips', 'skin', 'woman', 'young']` (8 hits).
- `_content_words(_BAND_GOOD_STYLE) & _STYLE_BANNED_TOKENS` → `[]`; `_BAND_GOOD_STYLE` is 39
  raw words and 36 content words (inside 30-55; above `_ECHO_MIN_STYLE_WORDS`).
- `_content_words("Young Woman With Auburn HAIR And Freckled SKIN, teal palette") &
  _STYLE_BANNED_TOKENS` → `['freckled', 'hair', 'skin', 'woman', 'young']` (`L38h`).

### 9.2 Real Z-Image-Turbo generations behind every number

The band budgets, the `Style:` budget and the SC7 thresholds are **measured, not reasoned**.
Six images were generated at the exact production config — `Tongyi-MAI/Z-Image-Turbo` +
`BennyDaBall/Qwen3-4b-Z-Image-Turbo-AbliteratedV1` on MPS/bfloat16, `width=1280`,
`height=704`, `num_inference_steps=9`, `guidance_scale=0.0`,
`generator=torch.Generator("cpu").manual_seed(0)`, prompt assembled as
`image_text + " " + style_text` exactly as `_compose_prompt` does it — using the same
red-curly-haired-woman-on-a-dusk-street scenario as the Step 1/Step 2 evidence. ~40s each.

The `Style:` suffix under test (37 raw words, 34 content words, **0** banned tokens — inside
the new 30-55 budget):

> muted teal and amber dusk palette, desaturated shadows, soft overcast key light, low
> contrast, damp asphalt and weathered brick textures, painted metal railings, clean
> high-resolution photographic rendering, 35mm lens character, shallow depth of field, fine
> natural grain

| Case | `Image:` words | identity words | banned tokens in `Image:` | What actually rendered |
| --- | --- | --- | --- | --- |
| `far_new` (extreme wide, 7 identity words) | 58 | 7 | **5** | ✅ Correct. Figure ~8% of frame height, back-facing, walking away down the centre of the road, houses and parked cars receding to a distant intersection, dusk sky. Red hair and green coat read as colour blocks only. |
| `mid_new` (medium, 13 identity words) | 50 | 13 | **6** | ✅ Correct. Medium/cowboy framing, front-facing, green wool coat over cream sweater, shoulder-length curly auburn hair, hand on the railing, cars and brick houses behind. Identity clearly readable at wardrobe+hair level. |
| `near_new` (close-up, 30 identity words) | 53 | 30 | **12** | ✅ Correct. True close-up, freckles across nose and cheeks, brown eyes, glossy pink lips, tightly curled auburn-red hair, dark green collar at the neckline, blurred brick and railing behind. Identity fully held. |
| `far_ctrl_oldstyle` (Step 2's composition-only far text + the **old** subject-carrying `Style:`) | 50 | 0 | 2 | ❌ **Reproduces the defect.** Renders a front-facing close-up portrait. Not wide, not back-facing, not small, not receding — despite the text saying "extreme wide shot … very small in the centre of the frame walking away from camera". |
| `far_over` (extreme wide + 28 inline identity words, i.e. what a cap of 30 would allow) | 75 | 28 | **11** | ❌ **Cap is load-bearing.** Same shot-type wording as `far_new`, collapses to a front-facing medium close-up. Inline over-specification breaks a far shot exactly as the old suffix did. |
| `near_under` (close-up + **zero** inline identity words, Step 2's convention) | 50 | 0 | 3 | ❌ **Floor is load-bearing.** Framing is a correct close-up, but the subject is a visibly different, older woman with straight rather than tightly curled hair, grey-green not brown eyes, no glossy lips, and no green coat. |

What these six establish, in order of importance:

1. **The root cause in §1.2 is confirmed, deterministically.** `far_ctrl_oldstyle` differs from
   `far_new` only in where the identity words sit — suffix vs. inline — and it is the suffix
   version that collapses. The defect is the `Style:` line, not the panel text.
2. **The far cap of 8 is real.** 7 identity words → correct wide shot; 28 → portrait. The
   breaking point lies between, and 8 sits at the safe end.
3. **The near floor is real, and it was missing from the first draft of this spec.** Removing
   appearance from `Style:` without *requiring* it inline yields correct framing and the wrong
   person. This is why §3.3's mid/near budgets are ranges, and why SC7 is two-sided.
4. **SC7's original thresholds were inverted and are now corrected.** The first draft capped
   far-band banned tokens at ≤2; the *compliant* `far_new` scores 5 and the *defective*
   `far_ctrl_oldstyle` scores 2, so that metric would have passed the defect and failed the
   fix. The corrected thresholds (far ≤7, mid 4-12, near ≥6) classify all six cases correctly.
5. **The echo heuristic stays silent on all three compliant cases.** `Image:`∩`Style:` overlap
   is 2/3/3 words against a threshold of `max(12, 0.5·34+1) = 18`, so `_style_echo_warnings`
   does not false-positive on the new convention.

The one number *not* independently probed is the mid-band ceiling of 20 (the generated mid case
used 13). It is interpolated between a verified-safe 7 and a verified-breaking 28, at a shot
distance where the subject already fills much of the frame and over-specification is therefore
less able to pull the camera. If A3 shows a mid-band panel losing its framing, that is the
number to look at first — report it rather than adjusting it.

The remaining unprobed number is the panel-2..N word budget of **45-70**, inherited unchanged
from Step 2 where it was already validated; all three compliant generations landed inside it
(58/50/53) with their band's identity words included, which is the specific claim §3.2 makes.

---

## 10. Open questions

None blocking. Two judgement calls are recorded rather than left open, so the executor is not
asked to decide them:

1. **`pale`, `tan`, `short`, `frame` were considered for and excluded from the banned list** —
   each has a legitimate global-look or composition meaning (`pale palette`, `tan brick`,
   `short lens`, `framing`) and would produce false positives on compliant lines. The cost of
   missing a `Style:` line that says only "pale" is one ignorable word; the cost of a false
   positive is an operator learning to ignore the warning.
2. **Fabric words (`denim`, `wool`, `leather`) were excluded** even though they are usually
   wardrobe, because §5.4 explicitly admits "the materials and surface textures of the
   setting" and those words can legitimately describe a bench, a door or a wall.
