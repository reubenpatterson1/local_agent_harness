# ltx-movie: panel drift fix — pinned still seed + mechanical style carry-forward

Date: 2026-09-13
Branch: `ltx2-mlx-video-pipeline`
Status: ready for `code-executor`
Supersedes in part: `docs/superpowers/specs/2026-09-12-ltx-movie-seed-image-design.md` §3.3 (see §9)

---

## 1. Problem and success criteria

### 1.1 Problem

With `bin/ltx-movie --seed-image REF.jpg`, panel 1's still *is* the reference image
(copied + crop-to-fill, `bin/ltx-story-images:103-114`). Panels 2..N are pure, independent
txt2img calls. Nothing conditions them on pixels. Two mechanisms therefore let them drift
away from the reference over a 15-panel story:

1. **Uncorrelated noise.** `bin/ltx-story-images:223` seeds every panel differently
   (`args.seed + i`), so even near-identical prompts land on unrelated composition,
   palette and identity draws.
2. **Paraphrase decay.** The only channel carrying the reference forward is the
   story-writing LLM re-typing panel 1's description into each later panel, per the
   "repeated VERBATIM" clause in `SEED_IMAGE_PREFACE` (`bin/ltx-movie:145`). It decays:
   a prior run described a domed building in panel 1 and "the Washington Monument obelisk"
   a few panels later. It also drags panel 1's *composition* into later panels, which
   fights their own framing.

### 1.2 Success criteria (binding; verified in §7 and §8)

- **SC1** `python3 tests/test_ltx_story_images.py` exits 0; `python3 tests/test_ltx_movie_offline.py`
  exits 0. Every pre-existing check in both files still passes, unchanged.
- **SC2** Every mutation in the mutation table (§7.3) makes the named test FAIL when applied,
  and the file returns to green when reverted.
- **SC3** On a story.md whose Panel 1 carries a `Style:` field, `bin/ltx-story-images --dry-run`
  prints the style text verbatim once, prints the pinned RNG seed, and marks every
  generated panel line with `+style` and the same `rng <N>` value.
- **SC4** On a real stills run of that story.md, `images.json` shows every panel with
  `"source": "generated"` having a `prompt` that ends with the exact `Style:` text.
- **SC5** A real `bin/ltx-movie --seed-image` Phase 1 run produces a `story.md` containing
  exactly one line matching `^Style: `, inside Panel 1, and Phase 1 validation passes.
- **SC6** Human eyeball on panels 2-6 against `~/Downloads/red.jpg`: subject identity,
  markings/wardrobe, colour palette, lighting character and render style are shared with
  the reference; framing/composition still differs panel to panel (panels must not all be
  re-crops of panel 1).
- **SC7** Back-compat: a story.md with no `Style:` field produces **byte-identical**
  `--dry-run` output before and after this change, and the per-panel seed for such a story
  stays `--seed + i`.

### 1.3 Must-have vs nice-to-have

Must-have: §3 (parser), §4 (Phase 2), §5 (Phase 1 prompt + validation), §7 (tests), §8 (acceptance).
Nice-to-have: none. Nothing in this spec is optional.

---

## 2. Scope

### 2.1 In scope

- `bin/ltx-story-manifest` — one new optional panel field, `Style:`, in the single shared
  story.md parser.
- `bin/ltx-story-images` — read Panel 1's `Style:`, append it verbatim to every panel's
  txt2img prompt, and pin the RNG seed while it is present.
- `bin/ltx-movie` — `SEED_IMAGE_PREFACE` asks for the `Style:` field and stops asking for
  verbatim per-panel repetition of the reference description; `_validate_story_md` requires
  the field on seeded runs.
- `tests/test_ltx_story_images.py`, `tests/test_ltx_movie_offline.py` — new cases.
- `docs/superpowers/specs/2026-09-12-ltx-movie-seed-image-design.md` — a superseded-in-part
  note (§9).

### 2.2 Explicitly OUT of scope

- **img2img anchoring of panels 2..N (the "Step 2" of the prior investigation) is OUT OF
  SCOPE.** Do not add `ZImageImg2ImgPipeline`, do not add `image=`/`strength=` parameters
  to `z_image_skill.generate_image`, do not add any panel-to-panel or panel-to-reference
  pixel conditioning, and do not leave TODOs, hooks, flags, config keys or comments
  anticipating it. The user chose the text/seed fix only. This spec is complete as written.
- **The video layer is untouched.** `bin/ltx-mlx-render`'s per-clip seed convention
  (`--seed + i`, `docs/superpowers/specs/2026-09-10-ltx2-mlx-video-pipeline-design.md:466`,
  with a test at :1088-1090 that targets exactly one panel *by its distinct seed*) must
  keep working. Change nothing in `bin/ltx-mlx-render`, `ltx2_mlx_video_skill.py`, or
  `bin/ltx-movie`'s `_render_flags`/`_phase4_flags`.
- **No drift metric / CLIP similarity script.** Not now.
- **Do not touch** the four pre-existing dirty files: `bin/ltx-story-video`,
  `ltx_ceiling.json`, `ltx_video_skill.py`, `z_image_skill.py`. None of them need to change.
- `STORY_PROMPT_TEMPLATE` and `STORY_PROMPT_TEMPLATE_NO_STILLS` are **not** edited. The
  new instruction lives only in `SEED_IMAGE_PREFACE`, which is prepended only for seeded,
  non-`--no-stills` runs. (Test `L25a` asserts the unseeded prompt is byte-identical to
  `STORY_PROMPT_TEMPLATE.format(...)`; the non-seeded path must stay bit-for-bit the same.)

---

## 3. Design decisions (made here; the executor makes none)

### 3.1 Decision D1 — the new field is `Style:`, a fourth label inside Panel 1

**Syntax.** One line, the LAST line of Panel 1's body, after `Narration:`:

```
## Panel 1 — Down the Avenue
Image: <70-90 words>
Motion: <110-160 words>
Narration: <one sentence>
Style: dark navy carbon bodywork with red bull-logo decals and a small white 31, glossy blue-and-white helmet with a mirrored visor, black slick tyres, orange-and-white barrier livery, bright midday sun with hard shadows, saturated blue-and-red palette, photoreal high-definition cinematic wide-angle rendering with slight fisheye
```

**Why a panel-1 label and not a top-level `## Style` section or a top-level `Style:` line
before the first panel:**

- The workspace has exactly one story.md parser by design (`bin/ltx-story-manifest::_parse_prompts_md`,
  load-bearing comment at `bin/ltx-story-images:121-125`). A panel-scoped label rides on the
  existing `_PANEL_LABEL_RE` machinery: a 3-line change, no new tuple element, no second
  file read, and callers keep receiving `(narrative, panels)`.
- A `## Style` section's body is **silently discarded** by the current parser (`bin/ltx-story-manifest:192-196`
  sets `current = None` for any non-panel `##` heading), so it would need a second
  extractor *and* a signature change at three call sites.
- A top-level `Style:` line before the first `## Panel` collides with `_extract_narrative`
  (`bin/ltx-story-manifest:139-154`), which returns the first non-blank, non-`#`, non-`-`
  line after the `# ` heading — it would start returning the style text as the manifest's
  `narrative`.

**Back-compat.** `p["style"]` is `""` whenever the label is absent, exactly like
`image`/`motion`/`narration`/`prompt` already behave. A `Style:` line in panels 2..N is
parsed but never read by anything (§4.2). No existing story.md in `generated/stories/`
contains a line matching `^Style:` (verified 2026-09-13), so the widened regex changes no
existing parse.

**Known, accepted side effect.** `p["text"]` (the v1 whole-body join) for Panel 1 now also
contains the style text. `text` is only consumed by `bin/ltx-story-manifest`'s
*no-labels* fallback branch (`bin/ltx-story-manifest:432-436`), which a panel with an
`Image:` field never reaches. No behavioural impact.

### 3.2 Decision D2 — "grounded mode": ONE switch drives both fixes, and it is the `Style:` field, not the `--seed-image` flag

`bin/ltx-story-images` computes `grounded = bool(style)` where `style` is Panel 1's
`Style:` text. When `grounded`:

- the style text is appended verbatim to every panel's txt2img prompt, and
- every panel uses the RNG seed `--seed` exactly, instead of `--seed + i`.

When not grounded, both behaviours are exactly today's.

**Why the seed pin is NOT universal.** Without a reference image, panels are independent
scenes and per-panel noise variety is the shipped, unreported behaviour of the tool. Pinning
everywhere would change the output of *every* existing non-seeded workflow (panel 1 goes
from seed `N+1` to `N`, and so on for all panels) for zero reported benefit, and would make
correlated composition bias across unrelated scenes the new default. The user reported drift
only in the seed-image path. Surgical change: pin only where one shared visual identity is
the point.

**Why the switch is the `Style:` field and not the `--seed-image` flag.** `bin/ltx-story-images`
is independently runnable, and the documented fast-iteration loop reruns single panels
(`--only 5 --force`). If the pin were gated on `--seed-image`, a rerun without that flag
would silently regenerate panel 5 at a *different* seed than its siblings and with no style
suffix — reintroducing exactly the defect this fixes, in the workflow most likely to be
used while judging the fix. Keying both behaviours to a property of the story.md file makes
them reproducible from the file alone, with or without the flag, in `ltx-movie` or
standalone. The `Style:` field only exists because `SEED_IMAGE_PREFACE` asked for it, so in
practice "grounded" still means "authored against a reference image".

**Accepted consequence.** A hand-written story.md that carries a `Style:` line gets pinned
seeds even with no seed image. That is the documented contract: `Style:` means "all panels
share one visual identity."

**Accepted consequence 2.** Old seeded stories on disk (e.g.
`generated/stories/wash-dc-f1-test/story.md`) have no `Style:` field. Re-running
`bin/ltx-movie --seed-image` against them now fails Phase 1 validation (§5.3) with an
actionable one-line remediation. Loud failure is preferred over silently reverting to the
drift-prone behaviour this replaces.

### 3.3 Decision D3 — the style is APPENDED (suffix), not prepended

`prompt = "<panel Image: text> <style text>"`, single space, no connective prose, no
punctuation inserted.

Reasons: (a) the panel's own content must lead the prompt — it is what makes the panel
different from its siblings; (b) the existing `--dry-run` line truncates the prompt to 100
characters, so a prefix would hide every panel's actual content behind identical boilerplate
(and would break existing tests `I11`'s content assertions); (c) `images.json`'s `prompt`
field stays readable as "panel text, then the shared suffix".

### 3.4 Decision D4 — the `Style:` field describes identity/style ONLY, never composition

The Phase 1 instruction (§5.1) explicitly bans composition, framing, shot type, camera
angle, viewpoint, pose, action and in-frame placement from the `Style:` line, and asks for a
comma-separated attribute list with no sentence subject, 40-70 words, one line. Composition
is panel-specific; carrying panel 1's composition forward is part of the current defect,
not part of the fix.

### 3.5 Decision D5 — the base template's VERBATIM rule stays

`STORY_PROMPT_TEMPLATE:101` ("...repeat that exact description VERBATIM...") is the only
character-consistency mechanism for non-seeded runs and stays untouched. The new preface
text states an explicit precedence rule: for elements **visible in the attached image**, the
`Style:` field replaces verbatim repetition; for **new** recurring characters introduced
later in the story, the VERBATIM rule still applies.

### 3.6 Decision D6 — `images.json` schema is NOT bumped and gains no field

The `prompt` field already exists and now holds the composed prompt (panel text + style
suffix) — that is a value change, not a shape change. `schema_version` stays `1`
(test `I13` asserts this). The pinned seed is made verifiable through stdout instead
(§4.4), which is captured in `movie.log` on full runs.

---

## 4. Change 1 of 3 — `bin/ltx-story-manifest` (the shared parser)

Three code edits plus a docstring edit. No other change to this file.

### 4.1 Edit P1 — widen the label regex (line 69)

Before:
```python
_PANEL_LABEL_RE = re.compile(r"^(Image|Motion|Narration|Prompt):\s*(.*)$")
```
After:
```python
_PANEL_LABEL_RE = re.compile(r"^(Image|Motion|Narration|Prompt|Style):\s*(.*)$")
```

### 4.2 Edit P2 — add the field bucket (line 205)

Before:
```python
        fields = {"Image": [], "Motion": [], "Narration": [], "Prompt": []}
```
After:
```python
        fields = {"Image": [], "Motion": [], "Narration": [], "Prompt": [], "Style": []}
```

### 4.3 Edit P3 — emit the joined value (after line 220, i.e. after `p["prompt"] = ...`)

Insert:
```python
        p["style"] = " ".join(fields["Style"])
```

### 4.4 Edit P4 — docstring (inside `_parse_prompts_md`, currently lines 158-177)

Change the first docstring line's key list from
`'motion': str, 'narration': str, 'prompt': str}` to
`'motion': str, 'narration': str, 'prompt': str, 'style': str}`, and append this paragraph
immediately before the closing `"""` of that docstring (keep existing paragraphs verbatim):

```
    A `Style:` label is the once-per-story visual-identity block written by
    bin/ltx-movie's --seed-image preface, and it is expected in Panel 1 only:
    bin/ltx-story-images appends Panel 1's `style` verbatim to every panel's
    image prompt. `style` is "" when the label never appears, so a story.md
    written before this field existed parses exactly as it did before.
```

---

## 5. Change 2 of 3 — `bin/ltx-story-images` (Phase 2)

### 5.1 Edit S1 — module docstring (lines 1-39)

Insert this paragraph immediately after the `images.json schema (schema_version 1): {...}`
block and before the `Dependencies:` paragraph:

```
Grounded mode: when the story.md's Panel 1 carries a `Style:` field (written by
bin/ltx-movie's --seed-image story preface), that text is appended verbatim to
every panel's image prompt, and every panel is generated with the SAME CPU RNG
seed (--seed exactly, not --seed + index) so that panels sharing a prompt suffix
also share their noise draw. Without that field nothing changes: prompts are the
Image: text alone and panel i uses --seed + i, exactly as before. The Style:
field, not the --seed-image flag, is the switch -- so a single-panel rerun
(--only 5 --force) reproduces the same seed and the same prompt as the original
batch whether or not --seed-image is passed again.
```

### 5.2 Edit S2 — `--seed` help text (line 61)

Before:
```python
    parser.add_argument("--seed", type=int, default=0)
```
After:
```python
    parser.add_argument("--seed", type=int, default=0,
                        help="base CPU RNG seed. Ungrounded story.md: panel i uses "
                             "--seed + i. Grounded story.md (Panel 1 has a Style: field): "
                             "every panel uses --seed exactly.")
```

### 5.3 Edit S3 — three new module-level helpers

Insert **between** `_write_seed_panel` (ends line 114) and `def main(` (line 117), verbatim:

```python
def _style_text(panels):
    """Panel 1's once-only Style: text, stripped, or "" when there is none.

    Only Panel 1 is consulted: the Phase 1 preface asks for exactly one Style:
    line, in Panel 1, and a stray one elsewhere is parsed but never read. The
    .get() keeps this working against a story.md parser that predates the field.
    """
    if not panels:
        return ""
    return panels[0].get("style", "").strip()


def _compose_prompt(image_text, style_text):
    """The txt2img prompt for one panel: its own Image: text, then the story's
    Style: text appended verbatim, joined by a single space.

    The panel's own text leads because it carries everything panel-specific; the
    style suffix carries only what every panel shares. With no style this returns
    the Image: text unchanged (the parser already strips and space-joins it), so
    an ungrounded story.md produces byte-identical prompts to before this existed.
    """
    image_text = image_text.strip()
    style_text = style_text.strip()
    if not style_text:
        return image_text
    if not image_text:
        return style_text
    return image_text + " " + style_text


def _panel_seed(base_seed, index, grounded):
    """The CPU RNG seed for panel `index` (1-based).

    Ungrounded: base_seed + index -- unchanged pre-existing behaviour, where each
    panel is an independent scene and per-panel noise variety is wanted. Grounded:
    base_seed for every panel, so panels that share a prompt suffix also share
    their noise draw instead of drifting apart on composition and palette alone.
    """
    return base_seed if grounded else base_seed + index
```

### 5.4 Edit S4 — compute grounded mode in `main()`

Insert immediately after the `--seed-image` existence check (after line 159's `return 2`
block, before the `out_paths` comment block at line 161):

```python
    # Grounded mode (see the module docstring): a non-empty Panel 1 Style: field
    # means this story.md was authored against a reference image and every panel
    # shares one visual identity. Two things then change, together: the style text
    # is appended verbatim to every panel's prompt, and the RNG seed is pinned to
    # --seed for every panel. Both are keyed to the file, not to --seed-image, so a
    # single-panel rerun reproduces the batch exactly.
    style = _style_text(panels)
    grounded = bool(style)
```

### 5.5 Edit S5 — `--dry-run` output (lines 166-172)

Before:
```python
    if args.dry_run:
        for i in selected_indices:
            if args.seed_image is not None and i == 1:
                print("%d | %s | seed: %s" % (i, out_paths[i], args.seed_image))
            else:
                print("%d | %s | %r" % (i, out_paths[i], panels[i - 1]["image"][:100]))
        return 0
```
After:
```python
    if args.dry_run:
        if grounded:
            print("style: %s" % style)
            print("seed: pinned to %d for every generated panel (grounded mode)" % args.seed)
        for i in selected_indices:
            if args.seed_image is not None and i == 1:
                print("%d | %s | seed: %s" % (i, out_paths[i], args.seed_image))
            elif grounded:
                print("%d | %s | rng %d | +style | %r"
                      % (i, out_paths[i], _panel_seed(args.seed, i, grounded),
                         _compose_prompt(panels[i - 1]["image"], style)[:100]))
            else:
                print("%d | %s | %r" % (i, out_paths[i], panels[i - 1]["image"][:100]))
        return 0
```

Contract: with no `Style:` field the printed bytes are identical to before (no banner, no
extra columns) — SC7.

### 5.6 Edit S6 — per-panel prompt (line 185)

Before:
```python
        prompt = panels[i - 1]["image"]
```
After:
```python
        prompt = _compose_prompt(panels[i - 1]["image"], style)
        seed_used = _panel_seed(args.seed, i, grounded)
```

`prompt` continues to flow into every `results.append({... "prompt": prompt ...})` call
site unchanged (lines 197, 204, 212, 227, 236, 243) — so `images.json` records the composed
prompt for every panel, including the seed panel and the "skipped, exists" panel. That is
intentional: `prompt` documents what the panel's prompt *is* under this story.md.

The pre-existing empty-`Image:` validation at lines 152-155 stays on the RAW field
(`panels[i - 1]["image"].strip()`), so a panel carrying only a style suffix is still an error.

### 5.7 Edit S7 — use the seed and log it (lines 216-229)

Before:
```python
            z_image_skill.generate_image(
                prompt,
                output_path=path,
                width=args.width,
                height=args.height,
                generator=torch.Generator("cpu").manual_seed(args.seed + i),
            )
            elapsed = time.monotonic() - start
            print("panel %d -> %s (%.1fs)" % (i, path, elapsed))
```
After:
```python
            z_image_skill.generate_image(
                prompt,
                output_path=path,
                width=args.width,
                height=args.height,
                generator=torch.Generator("cpu").manual_seed(seed_used),
            )
            elapsed = time.monotonic() - start
            print("panel %d -> %s (seed %d, %.1fs)" % (i, path, seed_used, elapsed))
```

No other print in the loop changes (the seed-panel line, the "skipped, exists" line, the
BLOCKED line and the ERROR line keep their current text).

---

## 6. Change 3 of 3 — `bin/ltx-movie` (Phase 1)

### 6.1 Edit M1 — replace `SEED_IMAGE_PREFACE` (lines 141-145)

Replace the whole assignment with exactly this. Paragraphs 1 and 2 are unchanged byte for
byte; paragraph 3's second half is replaced and paragraphs 4-6 are new.

```python
SEED_IMAGE_PREFACE = """An image is attached to this message. It is the movie's literal opening frame: Panel 1's still will NOT be rendered from your text -- the attached image IS Panel 1's still, exactly as it is.

Before you write anything, look at the attached image and describe what it actually shows. Panel 1's Image: field must be a faithful, literal description of that attached image and nothing else -- its subject, pose, framing, setting, lighting, colour palette and visual style as they really appear -- not a generative prompt, not an embellishment, and not an invention. Do not add people, objects, actions or scenery that are not visible in the attached image, and do not omit the ones that are.

Panel 1's Motion: and Narration: fields are written normally, and Panel 2 onward continue the narrative as usual -- but every later panel's Image: field must stay visually consistent with what you actually observed in the attached image: the same characters, wardrobe, setting, lighting and style. Do NOT copy Panel 1's Image: description into the later panels: each later panel's Image: field is its own 70-90 word description of that panel's own composition, and the shared look is carried forward by the Style: field described next instead of by repetition.

Panel 1, and only Panel 1, carries one extra field, written as its LAST line, after Narration:, in exactly this form:

Style: <40-70 words on a single line describing ONLY what is identical in every panel of this movie, taken from the attached image: the recurring subjects and their fixed appearance (wardrobe, colours, markings, distinguishing features), the materials and textures, the colour palette, the lighting character, and the rendering style, medium and lens character>

Write the Style: line as a plain comma-separated list of attributes with no sentence subject: it is appended word for word to the end of every panel's image prompt, so it must read correctly after any panel's Image: text. It must not mention composition, framing, shot type, camera angle, viewpoint, pose, action, or where anything sits in the frame -- those change from panel to panel and each panel's own Image: field sets them. Emit the Style: line exactly once, in Panel 1, and never in any other panel.

This replaces the verbatim-repetition rule below for everything that is visible in the attached image: describe those elements once, in Panel 1's Image: field, name their fixed attributes in the Style: line, and do not repeat either description in later panels. The verbatim-repetition rule below still applies to any NEW recurring character or visual element you introduce later that is not visible in the attached image."""
```

Preserved verbatim (asserted by existing test `L25e`): `Panel 1's still will NOT be rendered
from your text`, `faithful, literal description of that attached image`, `not a generative
prompt`, `must stay visually consistent with what you actually observed`.

Removed deliberately: `Any character or recurring visual element visible in the attached
image gets its full visual description written out in Panel 1's Image: field, taken from the
image itself, and that exact wording is repeated VERBATIM in every later panel in which it
appears.`

`build_story_prompt` (lines 148-153) is **not** changed.

### 6.2 Edit M2 — `_validate_story_md` gains `require_style` (lines 356-394)

Signature (line 356):
```python
def _validate_story_md(story_md_path, expected_panels, no_stills=False, require_style=False):
```

Docstring: append this sentence to the existing docstring, before the closing `"""`:
```
    require_style additionally demands a non-empty Style: field on panel 1 --
    set only for a --seed-image run, whose Phase 2 carries the reference's
    identity forward from that field.
```

Insert immediately before `return violations` (line 394):
```python
    # A seeded run's whole grounding mechanism after panel 1 is Phase 2 appending
    # panel 1's Style: text to every panel prompt. Without the field the run would
    # silently fall back to the drift-prone paraphrase-per-panel behaviour this
    # replaced, so fail loudly: story.md is kept, and one hand-edited line fixes it.
    if require_style and panels and not panels[0].get("style", "").strip():
        violations.append(
            "panel 1: missing/empty Style: field, which --seed-image requires -- add one "
            "line to panel 1 after Narration:, naming only the recurring subjects' fixed "
            "appearance, materials, colour palette, lighting character and rendering style "
            "(no composition, framing or camera words)"
        )
```

The `panels and` guard is required: an empty story.md already reports the panel-count
violation and must not raise `IndexError`.

### 6.3 Edit M3 — call site in `phase1_story` (line 593)

Before:
```python
    violations = _validate_story_md(story_md, args.panels, args.no_stills)
```
After:
```python
    require_style = bool(getattr(args, "seed_image", None)) and not args.no_stills
    violations = _validate_story_md(story_md, args.panels, args.no_stills, require_style)
```

(`--seed-image` with `--no-stills` is already a hard error elsewhere in the file, line 876;
the `and not args.no_stills` term mirrors `build_story_prompt`'s own precedence and keeps
the two consistent.)

---

## 7. Tests

**Run mode: direct script invocation only.** Never `pytest`. `check()` in these files
records failures and the file's `__main__` sets the exit code; under pytest the same
functions report "passed" no matter what fails. Every acceptance command below captures the
return code *before* any pipe.

### 7.1 New cases in `tests/test_ltx_story_images.py`

Add this helper next to `_write_three_panel_story` (line 102):

```python
STYLE_TEXT = ("weathered brass fittings, deep teal and rust palette, matte film grain, "
              "soft overcast light, photoreal 35mm rendering")


def _write_three_panel_story_with_style(tmp, style=STYLE_TEXT):
    md_path = os.path.join(tmp, "story.md")
    with open(md_path, "w") as f:
        f.write(
            "# Story\n\n"
            "## Panel 1 - First\n"
            "Image: a red ball on a table\n"
            "Motion: camera zooms in\n"
            "Narration: the ball sits quietly\n"
            "Style: %s\n\n"
            "## Panel 2 - Second\n"
            "Image: a blue cube on the floor\n"
            "Motion: camera pans left\n"
            "Narration: the cube waits\n\n"
            "## Panel 3 - Third\n"
            "Image: a green pyramid in the sky\n"
            "Motion: slow rotation\n"
            "Narration: the pyramid floats\n" % style
        )
    return md_path
```

Then add these cases (each registered in `__main__`, in this order, after
`test_seed_source_guards()`):

**I14 — the parser reads `Style:`, back-compatibly.**
- On `_write_three_panel_story_with_style`: `panels[0]["style"] == STYLE_TEXT`;
  `panels[1]["style"] == ""`; `panels[2]["style"] == ""`.
- The other fields of panel 1 are unaffected: `panels[0]["image"] == "a red ball on a table"`,
  `panels[0]["motion"] == "camera zooms in"`, `panels[0]["narration"] == "the ball sits quietly"`.
- A wrapped `Style:` value space-joins: write a story whose panel 1 has
  `Style: first part\nsecond part\n` and assert `panels[0]["style"] == "first part second part"`.
- On `_write_three_panel_story` (no `Style:`): `panels[0]["style"] == ""` and
  `panels[0]["image"] == "a red ball on a table"`.

**I15 — `_compose_prompt`.**
- `_compose_prompt("a red ball", "teal palette") == "a red ball teal palette"` (exactly one space).
- `_compose_prompt("a red ball", "") == "a red ball"` and `_compose_prompt("a red ball", "   ") == "a red ball"`.
- `_compose_prompt("", "teal palette") == "teal palette"`.
- `_compose_prompt("  a red ball  ", "  teal palette  ") == "a red ball teal palette"`.
- Style is a suffix, not a prefix: the result `.startswith("a red ball")` and `.endswith("teal palette")`.

**I16 — `_style_text`.**
- `_style_text([])  == ""`.
- `_style_text([{"style": "  abc  "}]) == "abc"`.
- `_style_text([{}]) == ""` (missing key tolerated).
- Only panel 1 is read: `_style_text([{"style": ""}, {"style": "later"}]) == ""`.

**I17 — `_panel_seed`.**
- `_panel_seed(0, 1, False) == 1`, `_panel_seed(0, 5, False) == 5`, `_panel_seed(7, 3, False) == 10`.
- `_panel_seed(0, 1, True) == 0`, `_panel_seed(0, 5, True) == 0`, `_panel_seed(7, 3, True) == 7`.

**I18 — grounded `--dry-run` output.** Same subprocess pattern as `test_dry_run_prints_and_never_imports_torch`
(so torch-import is still asserted), on `_write_three_panel_story_with_style`, with
`['--story-md', md, '--out-dir', out, '--seed', '4', '--dry-run']`:
- `RC=0` and `TORCH_IMPORTED=False`.
- stdout contains a line exactly equal to `"style: " + STYLE_TEXT`.
- stdout contains a line exactly equal to `"seed: pinned to 4 for every generated panel (grounded mode)"`.
- Each of the three panel lines (those whose first char is a digit) contains `"| rng 4 |"` and `"| +style |"`.
- No panel line contains `"rng 5"`, `"rng 6"` or `"rng 7"` (proves the `+ i` offset is gone).
- The panel-2 line still contains `blue cube`, and the panel-3 line still contains `green pyramid`
  (proves the style is a suffix, not a prefix that pushes content out of the 100-char window).
- Each panel line also contains a substring of `STYLE_TEXT` itself (not just the `+style` marker),
  so the check actually confirms the style *text* reached the composed prompt, satisfying M-2 in
  the mutation table below.

**I19 — ungrounded `--dry-run` output is unchanged.** Same subprocess pattern on
`_write_three_panel_story` with `--seed 4`:
- Exactly 3 panel lines; none contains `+style`, `rng ` or `pinned to`.
- No line starts with `style: `.
- Each panel line matches `^\d+ \| .+ \| '.*'$`.

**I20 — source guards for the seed change.** Read `_IMAGES_PATH` as text:
- `src.count("_panel_seed(args.seed, i, grounded)") == 2` (the dry-run print and the loop).
- `"manual_seed(seed_used)" in src`.
- `"manual_seed(args.seed + i)" not in src` — the old per-panel offset is gone from the call site.
- `src.count("_compose_prompt(") == 3` (definition + dry-run + loop).
- `"grounded = bool(style)" in src`.

### 7.2 New cases in `tests/test_ltx_movie_offline.py`

Registered in `__main__` after `test_seed_source_guards()`:

**L30 — the preface specifies the `Style:` field.** With
`p_on = ltx_movie.build_story_prompt("n", "sid", 5, False, True)` and
`p_off = ltx_movie.build_story_prompt("n", "sid", 5)`:
- `"Style:" in p_on` and `"Style:" not in p_off` (the field is seeded-runs-only).
- `p_on` contains each of: `Panel 1, and only Panel 1, carries one extra field`,
  `40-70 words on a single line`, `appended word for word to the end of every panel's image prompt`,
  `Emit the Style: line exactly once, in Panel 1, and never in any other panel.`
- `p_on` contains `It must not mention composition, framing, shot type, camera angle, viewpoint, pose, action`.
- `p_on.startswith(ltx_movie.SEED_IMAGE_PREFACE)` and `p_on.endswith(p_off)` (unchanged assembly).

**L31 — the per-panel verbatim repetition of the reference is gone, with an explicit precedence rule.**
- `"that exact wording is repeated VERBATIM in every later panel in which it appears" not in p_on`.
- `"Do NOT copy Panel 1's Image: description into the later panels" in p_on`.
- `"This replaces the verbatim-repetition rule below for everything that is visible in the attached image" in p_on`.
- `"The verbatim-repetition rule below still applies to any NEW recurring character" in p_on`.
- The base rule survives for unseeded runs: `"VERBATIM" in p_off` (guards D5).

**L32 — `_validate_story_md(require_style=...)`.** Build two temp story.md files with 2
panels each, both structurally valid (Image/Motion/Narration on every panel), one with
`Style: teal palette, matte grain` as panel 1's last line and one without:
- `_validate_story_md(without, 2, False, True)` returns exactly one violation, and that
  string contains `missing/empty Style: field`.
- `_validate_story_md(with_style, 2, False, True) == []`.
- `_validate_story_md(without, 2, False) == []` — default is unchanged, back-compat.
- `_validate_story_md(without, 2, False, False) == []`.
- An empty file (no panels at all) with `require_style=True` returns violations, does not
  raise, and reports the panel-count problem (`"expected exactly 2 panels, found 0"` present).

**L33 — call-site guard.** Read `bin/ltx-movie` as text and assert both lines are present
exactly once:
- `'    require_style = bool(getattr(args, "seed_image", None)) and not args.no_stills\n'`
- `'    violations = _validate_story_md(story_md, args.panels, args.no_stills, require_style)\n'`

### 7.3 Mutation table (SC2) — each mutation must turn the named test RED

Apply one at a time, run the named file directly, confirm a FAIL line and a non-zero exit,
then revert.

| # | Mutation | Must fail |
|---|---|---|
| M-1 | `_panel_seed` returns `base_seed + index` unconditionally | `I17`, `I18` (tests/test_ltx_story_images.py) |
| M-2 | `_compose_prompt` returns `image_text` unconditionally | `I15`, `I18` |
| M-3 | `_compose_prompt` returns `style_text + " " + image_text` (prefix instead of suffix) | `I15` |
| M-4 | Remove `"Style": []` from the parser's `fields` dict (and the `p["style"]` join) | `I14`, `I16`-adjacent parse assertions, `L32` |
| M-5 | Drop the `if grounded:` banner block from the dry-run | `I18` |
| M-6 | Make `grounded = args.seed_image is not None` instead of `bool(style)` | `I18` (dry-run has no `--seed-image`, so banner/rng/+style vanish) |
| M-7 | Delete the `require_style` violation block in `_validate_story_md` | `L32` |
| M-8 | Restore the removed VERBATIM sentence in `SEED_IMAGE_PREFACE` | `L31` |

### 7.4 Regression set that must stay green

`python3 tests/test_ltx_story_images.py`, `python3 tests/test_ltx_movie_offline.py`,
`python3 tests/test_ltx_story_video.py`, `python3 tests/test_ltx_chain.py`,
`python3 tests/test_ltx_mlx_render.py` — the last three because they share
`bin/ltx-story-manifest`'s parser. All must exit 0.

---

## 8. Acceptance checks

Run from `/Users/reubenpatterson/local_model_harness/qwen-agent-workspace`.
`SCRATCH` below means the session scratchpad directory.

### A0 — capture the back-compat baseline BEFORE editing any file (SC7)

```
python3 bin/ltx-story-images --story-md generated/stories/wash-dc-f1-test/story.md \
  --out-dir "$SCRATCH/bc" --dry-run > "$SCRATCH/dryrun-before.txt"; echo "rc=$?"
```
After all edits, rerun to `"$SCRATCH/dryrun-after.txt"` and require
`diff "$SCRATCH/dryrun-before.txt" "$SCRATCH/dryrun-after.txt"` to print nothing and exit 0.
Paste both the rc values and the diff result into the completion report (a scratchpad file
is not durable evidence on its own).

### A1 — offline suites (SC1, SC2)

```
python3 tests/test_ltx_story_images.py; rc=$?; echo "rc=$rc"
python3 tests/test_ltx_movie_offline.py; rc=$?; echo "rc=$rc"
python3 tests/test_ltx_story_video.py; rc=$?; echo "rc=$rc"
python3 tests/test_ltx_chain.py; rc=$?; echo "rc=$rc"
python3 tests/test_ltx_mlx_render.py; rc=$?; echo "rc=$rc"
```
Capture `rc` before any pipe; `... | tail` reports tail's status, not the test's.
Then walk the §7.3 mutation table.

### A2 — grounded dry-run against the real asset (SC3), no GPU

Write `"$SCRATCH/red_story/story.md"` with six panels about a red subject, Panel 1 carrying
`Style: deep crimson lacquer body with fine specular highlights, warm neutral background,
soft directional key light, shallow depth of field, photoreal 50mm rendering, saturated
red-dominant palette` as its last line, then:

```
python3 bin/ltx-story-images --story-md "$SCRATCH/red_story/story.md" \
  --out-dir "$SCRATCH/red_story/panels" --seed-image ~/Downloads/red.jpg --dry-run; echo "rc=$?"
```

A human must see, in order:
- one `style: deep crimson lacquer body ...` line reproducing the Style text **verbatim and
  untruncated**;
- `seed: pinned to 0 for every generated panel (grounded mode)`;
- `1 | .../panel_01.png | seed: /Users/reubenpatterson/Downloads/red.jpg`;
- lines 2..6 each containing `| rng 0 | +style |` — the same `rng 0` on every one of them,
  never `rng 2`..`rng 6`.

### A3 — real stills run + A/B against the un-grounded control (SC4, SC6)

Requires the Z-Image stack up. Still generation is seconds per panel; this is the cheap
iteration layer — do **not** render video for it.

```
python3 bin/ltx-story-images --story-md "$SCRATCH/red_story/story.md" \
  --out-dir "$SCRATCH/red_story/panels" --seed-image ~/Downloads/red.jpg --force; echo "rc=$?"
```
Then the control, with the `Style:` line deleted from a copy of the story.md:
```
python3 bin/ltx-story-images --story-md "$SCRATCH/red_story/story_nostyle.md" \
  --out-dir "$SCRATCH/red_story/panels_control" --seed-image ~/Downloads/red.jpg --force; echo "rc=$?"
```

Machine checks:
- The grounded run's stdout shows `(seed 0, ...)` on **every** generated panel line; the
  control's shows `(seed 2, ...)`, `(seed 3, ...)` … ascending.
- Every `"source": "generated"` entry in `"$SCRATCH/red_story/panels/images.json"` has a
  `prompt` that ends with the exact Style string (verify with a one-line
  `python3 -c` over the JSON; require it for all of panels 2..6).

Human eyeball, panels 2-6 of each run side by side with `~/Downloads/red.jpg`:
- **PASS** when the grounded panels hold the reference's subject identity, markings, colour
  palette, lighting character and render style across all five, and the control visibly does
  not (that is the defect being fixed);
- **FAIL** when the grounded panels 2-6 are near-identical re-crops of panel 1 with no
  compositional variation — that means the Style text carried composition and §3.4/§6.1
  needs tightening, not more code;
- **FAIL** when identity still walks away by panel 5-6 despite an identical prompt suffix
  and an identical seed — report that verdict and stop. Do not implement anything further;
  the img2img follow-on is out of scope (§2.2) and is the user's decision, not the
  executor's.

Note for reruns: `bin/ltx-story-images` skips panels whose PNG already exists unless
`--force` is passed. Always pass `--force` when re-running a directory.

### A4 — end-to-end Phase 1 (SC5). Requires the 27B vLLM server UP.

```
python3 bin/ltx-movie "a short story about a red object crossing a city" \
  --story-id drift_red_test --seed-image ~/Downloads/red.jpg --panels 6 --force-story
```
Let Phases 0-3 run and **press Ctrl-C at the Phase 4 confirmation prompt** — Phase 4 is
hours of GPU time and proves nothing about drift.

Checks:
- `grep -c '^Style: ' generated/stories/drift_red_test/story.md` is `1`, and the line sits
  inside `## Panel 1`, after its `Narration:` line.
- No panel 2..6 `Image:` field is a verbatim copy of panel 1's `Image:` field.
- Phase 1 prints no validation violations.
- Negative control: delete that `Style:` line and rerun the same command — Phase 1 must now
  abort with `panel 1: missing/empty Style: field, which --seed-image requires`.

---

## 9. Relationship to prior specs

`docs/superpowers/specs/2026-09-12-ltx-movie-seed-image-design.md` §3.3 states that later
panels stay consistent "using the existing verbatim-repetition convention for recurring
characters/settings". **This spec supersedes that clause**: reference-derived identity is
carried by the mechanical `Style:` suffix instead, and the preface now forbids copying panel
1's `Image:` description forward. Everything else in that spec (Phase 0 pre-flight, the
`--image` multimodal wiring, the crop-to-fill framing contract, §3.4's panel-1 handling,
§3.5's `--force`/`--only` behaviour) stands unchanged.

Required documentation edit: insert the following two lines in that file immediately after
the §3.3 bullet that begins "`STORY_PROMPT_TEMPLATE` (in `bin/ltx-movie`) gets a new
conditional preface" (i.e. as a new bullet at the end of §3.3):

```
- **Superseded 2026-09-13** by `docs/superpowers/specs/2026-09-13-ltx-movie-panel-drift-fix.md`:
  the verbatim-repetition convention is no longer how later panels stay consistent with the
  reference. Panel 1 now emits a once-only `Style:` field and Phase 2 appends it to every
  panel's prompt mechanically, with the still-generation RNG seed pinned for such stories.
```

`docs/superpowers/specs/2026-09-10-ltx2-mlx-video-pipeline-design.md` is **not** in conflict:
its `--seed + i` rule (line 466) is the *video* layer's per-clip seed, which this spec does
not touch (§2.2).

---

## 10. Edge cases

| Case | Required behaviour |
|---|---|
| story.md with no `Style:` field | Everything exactly as before: `--seed + i`, no suffix, byte-identical dry-run (SC7). |
| `Style:` present but whitespace-only | Treated as absent (`_style_text` strips) — ungrounded. |
| `Style:` wrapped across several lines | Space-joined by the parser; used as one line. |
| `Style:` in panels 2..N | Parsed, never read. Not a validation error. |
| `--only 5` on a grounded story | Panel 1 is still parsed, so the style and the pinned seed apply to panel 5. |
| `--only` excluding panel 1 with an empty panels list | Impossible: `main()` already errors on a story.md with no panels before grounded mode is computed. |
| Panel has `Style:` but an empty `Image:` | Still an error (`panel N has no Image: field`) — validation reads the raw field. |
| `--seed-image` + `--no-stills` | Already a hard error in `bin/ltx-movie` (line 876); `require_style` is False in that combination and no `Style:` is requested. |
| Pre-existing seeded story.md without `Style:` re-run through `bin/ltx-movie --seed-image` | Phase 1 validation fails with the one-line remediation message (accepted, §3.2). |
| Mixed panel directory (some panels rendered before the change) | Operator must pass `--force`; the tool's existing "skipped, exists" behaviour is unchanged and is not special-cased. |
| Prompt length | The suffix adds 40-70 words, but dropping the verbatim repetition removes ~100 words per panel from `Image:`, so per-panel prompts get shorter, not longer. No new length logic. |

---

## 11. Executor checklist

1. Capture the A0 baseline **before** touching any file.
2. Apply §4 (3 code edits + docstring), §5 (7 edits), §6 (3 edits), §9 (doc note).
3. Add the tests in §7.1 and §7.2; register every new case in each file's `__main__`.
4. Run §8 A1 (all five suites, rc captured before any pipe), then the full §7.3 mutation table.
5. Run §8 A0-after and diff.
6. Report: rc of each suite, the OK n/n line from each, the mutation table with observed
   failing check names, the A0 diff result, and the A2 dry-run output verbatim.
7. Do NOT run A3/A4 unless the user asks — they need the GPU and the 27B server; hand back
   the exact commands instead.
8. Do not commit or push. Do not modify `bin/ltx-story-video`, `ltx_ceiling.json`,
   `ltx_video_skill.py` or `z_image_skill.py`.
9. If anything in this spec is ambiguous, stop and return the question. Make no design call.

---

## 12. Open questions

None. Every design choice (field name and placement, grounded-mode switch, seed-pin scope,
suffix vs prefix, schema stability, validation strictness, precedence over the base VERBATIM
rule) is resolved above.
