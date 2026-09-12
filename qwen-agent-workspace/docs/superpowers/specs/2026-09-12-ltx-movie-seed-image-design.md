# Spec: `--seed-image` for the ltx-movie pipeline

**Status:** Design approved via brainstorming dialogue, 2026-09-12. Not yet implemented.
**Type:** Architectural — new input modality across story authoring, still-image generation,
and (indirectly) video rendering.
**Repo:** `/Users/reubenpatterson/local_model_harness/qwen-agent-workspace`, branch `ltx2-mlx-video-pipeline`.

---

## 1. Problem and goal

Today `bin/ltx-movie` builds a story, panel stills, and video clips purely from a text
narrative: Phase 1 sends the narrative to the hosted 27B model (via `bin/qwen-agent`
one-shot mode), which invents every panel's `Image:`/`Motion:`/`Narration:` fields from
scratch; Phase 2 renders every panel's still with `z_image_skill.generate_image` (pure
text-to-image); Phase 4 renders each panel's video clip conditioned on that panel's own
still (image-to-video conditioning already exists and is already used this way).

The goal: let the user supply a **seed image** alongside the narrative. That image
becomes the movie's literal opening frame, and the model's Panel 1 description is a
faithful account of what the image actually shows rather than an invention — the same
authoring call also uses that grounding to keep later panels visually consistent with it.

## 2. What already exists (load-bearing facts checked against the code)

- **Image-to-video conditioning already exists and is already used per-panel.**
  `ltx_video_skill.generate_video(image_path, prompt, ...)` accepts any image as frame-0
  conditioning; every panel's clip is already conditioned on that panel's own still. No
  new capability is needed here — a seed image is just another `image_path` once it's a
  file on disk in the right shape.
- **No vision-language capability existed in `bin/qwen-agent` before this feature.** No
  `image_url`/multimodal content-block handling was found anywhere in the file; every
  chat message is sent as a plain string (`oneshot()`, `bin/qwen-agent:3558`:
  `messages = [system_msg, {"role": "user", "content": args_ns.user_prompt}]`).
- **The hosted model IS vision-capable.** Per the user: the currently-served 27B model
  (`DEFAULT_MODEL = "qwen38-6bit"`, `DEFAULT_BASE_URL = "http://127.0.0.1:8177/v1"`,
  Gemma-based chat conventions per the existing `STORY_PROMPT_TEMPLATE` work) already
  supports multimodal input on its OpenAI-compatible endpoint. This feature only needs to
  *use* that, not stand up new infrastructure.
- **No image-to-image capability exists for stills.** `z_image_skill.generate_image` is
  pure text-to-image with no init-image/strength parameter. Stills cannot be regenerated
  "in the style of" the seed image today — the only faithful way to make Panel 1 match the
  seed image exactly is to use the seed image itself as Panel 1's file.
- **Dimension constraints on the render path** (`ltx_video_skill._validate_geometry`):
  the video *request's* width/height must satisfy `% 32 == 0` (and `% 16 == 0`), raised as
  a hard `ValueError`, not silently floored. This constrains the request, not the raw
  conditioning image's own pixel size directly — but Panel 2+ stills are already rendered
  at exactly `--image-width`x`--image-height` (default 1280x704, both `% 32 == 0`), so
  Panel 1 must match that same size for the pipeline to treat every panel uniformly.

## 3. Design

### 3.1 CLI surface

New flag `--seed-image PATH` on `bin/ltx-movie`, given alongside the existing `narrative`
positional argument (both together — the image grounds the story, it does not replace the
narrative text). The same original file has two independent downstream consumers: Phase 0
derives a downscaled copy from it for the Phase 1 multimodal request (Section 3.3), and
the *original, full-quality* path is threaded through unchanged to `bin/ltx-story-images`
as the same `--seed-image` flag name for Phase 2 (Section 3.4) — that tool already owns
"produce `panels/panel_NN.png` at the configured size" for every other panel, so it keeps
owning that job for panel 1 too, working from the original file, not the downscaled copy.

### 3.2 Phase 0 — pre-flight validation and payload prep (new, in `bin/ltx-movie`)

Before Phase 1 (the expensive LLM call) runs, when `--seed-image` is given: verify the
file exists and can be opened as a valid, non-degenerate image. Fail loudly here, not
partway through Phase 1 or Phase 2 — there is no point spending a 27B-model call or GPU
time on a broken input. This step also produces the downscaled temp copy Phase 1 sends to
the model (Section 3.3) — see the dependency note there for why this resizing work lives
in `ltx-movie` and not in `bin/qwen-agent`.

### 3.3 Phase 1 — multimodal story authoring

- `bin/qwen-agent`'s one-shot mode gets a new `--image PATH` flag, validated the same way
  `--system-prompt`/`--skill` are validated against `--user-prompt` today (`--image
  requires --user-prompt`). **Dependency note:** `bin/qwen-agent`'s own docstring states
  it is "single-file, standard-library-only" — confirmed by its imports (no PIL, no
  third-party packages at all). This flag must not break that: `qwen-agent` does no image
  *processing*, only reads whatever file it is given and base64-encodes the raw bytes
  (stdlib `base64`) into the content block below. All resizing happens upstream, in
  `ltx-movie`'s Phase 0 (Section 3.2), which is not stdlib-only-constrained and passes
  `qwen-agent --image` the path to an already-downscaled temp copy, never the original.
  The mime type in the data URL is read from the file's actual declared format at the time
  it was written (`image/png` — Phase 0 always writes the temp copy as PNG regardless of
  the seed's original format), not guessed from a path extension.
- When `--image` is given, `oneshot()`'s user message content becomes a list instead of a
  plain string: `[{"type": "text", "text": args_ns.user_prompt}, {"type": "image_url",
  "image_url": {"url": "data:image/png;base64,<...>"}}]` — the standard
  OpenAI-compatible multimodal shape. Every other call path (REPL, tool-calling turns,
  non-seeded one-shot calls) is untouched; this is purely additive.
- In `ltx-movie`'s Phase 0, the seed image is opened, downscaled to a fixed max dimension
  (1024px on the long edge, preserving aspect ratio) and re-saved as a PNG to a temp path —
  both to bound the multimodal request payload and because `CHARS_PER_TOKEN`'s
  context-budget math (in `qwen-agent`) has no model for image-token cost at all today. A
  new fixed, conservative constant in `qwen-agent` (analogous to `CONTEXT_FLOOR`) accounts
  for one attached image in the budget estimate, rather than attempting to model real
  vision-token cost precisely. This downscaled copy is used **only** for the Phase 1
  request; Phase 2 (Section 3.4) works from the original, full-quality seed file.
- `STORY_PROMPT_TEMPLATE` (in `bin/ltx-movie`) gets a new conditional preface, inserted
  only when a seed image is attached, instructing the model: Panel 1's `Image:` field must
  be a faithful, literal description of exactly what the attached image shows (subject,
  pose, setting, lighting, palette, style) — not a generative prompt — because Panel 1's
  still will not be rendered at all, it *is* the seed image. Every later panel's
  `Image:`/`Motion:` must stay visually consistent with what the model actually observed,
  using the existing verbatim-repetition convention for recurring characters/settings.
- One combined model turn: the model sees the image and writes the entire `story.md` in
  the same call it does today (not a separate captioning-then-writing pipeline).

### 3.4 Phase 2 — the seed image becomes `panel_01.png`

`bin/ltx-story-images`, when given `--seed-image`, skips calling
`z_image_skill.generate_image` for panel 1 and instead: loads the seed image, resizes +
**center-crops to fill** exactly `--width`x`--height` (no letterboxing — matches how every
generated panel already fills the frame edge-to-edge), and saves it as `panels/panel_01.png`.
Downstream tooling (manifest builder, dry-run, video renderer) needs no special-casing —
panel 1 is just another same-sized PNG on disk. `panels/images.json` gets one added field,
`"source": "seed"` vs. `"generated"`, for operator visibility only; no schema consumer
requires it.

### 3.5 `--force`/`--only` interaction

When `--seed-image` is given, panel 1 always takes the copy-and-normalize path regardless
of `--force` (there is no txt2img output to regenerate for it). If `ltx-story-images` is
rerun standalone without `--seed-image` a second time, panel 1 falls back to being
txt2img-rendered from its own (faithful, literal) `Image:` text description — visually
close, not a hard failure. This is an accepted edge case; no "this panel came from a seed"
tracking file is introduced to prevent it (avoids state that must stay in sync for no
concrete benefit).

### 3.6 Error handling

- **Model doesn't honor the image / writes an unrelated story.** Code can validate
  *structure* (all three fields present, correct panel count — the existing
  `_validate_story_md` already does this) but not *semantic faithfulness* to the image.
  This is a prompt-quality problem, addressed the same way the Motion:/Image: template
  work was: prompt iteration and human review of the resulting `story.md`, not a code
  assertion.
- **Multimodal request rejected by the server.** Surfaces through the existing
  oneshot-mode error envelope/exit-code conventions; `ltx-movie`'s Phase 1 already treats
  a failed `qwen-agent` subprocess as a phase failure and aborts with a clear message. No
  new swallowing logic.
- **Missing/corrupt seed image.** Caught by Phase 0 pre-flight (Section 3.2), before any
  model or GPU time is spent.

## 4. What this spec deliberately does NOT do

- No image-to-image regeneration for stills (`z_image_skill` gains no new capability).
- No new vision infrastructure — this only wires up multimodal input on the server
  already hosting the story-authoring model.
- No "seed provenance" tracking file for the `--force`/`--only` edge case (Section 3.5).
- No attempt to model exact vision-token cost in the context budget — a fixed
  conservative constant only (Section 3.3).

## 5. Testing strategy

**Offline/unit-testable:**
- `bin/qwen-agent`'s new `--image` flag: correct multimodal content-block construction;
  no regression to any existing text-only call path.
- The resize/center-crop function in `bin/ltx-story-images`: exact output dimensions for
  varied input aspect ratios, no distortion, no letterboxing.
- The conditional `STORY_PROMPT_TEMPLATE` preface: structural presence when `--seed-image`
  is given, absence when it is not — same style as the existing offline prompt-template
  tests in `tests/test_ltx_movie_offline.py`.
- `--force`/`--only` interaction with a seed-sourced panel 1 (Section 3.5).
- Phase 0 pre-flight validation: missing file, corrupt/unreadable file, degenerate image.

**Not offline-testable:** whether the model's output is actually faithful to the real
image content. That requires a live GPU run with the real hosted model and human
eyeballing — the same caveat already tracked for the Motion:/Image: prompt-template work
(real GPU run still un-eyeballed as of this writing).

## 6. Files touched

- `bin/ltx-movie` — `--seed-image` flag, Phase 0 pre-flight + downscale-to-temp-PNG
  (new PIL dependency — this file is not stdlib-only today, and this is a deliberate,
  scoped addition), conditional `STORY_PROMPT_TEMPLATE` preface, threading the seed path
  to `bin/ltx-story-images` and the downscaled temp path to `bin/qwen-agent --image`.
- `bin/qwen-agent` — `--image` flag on one-shot mode, multimodal content-block
  construction in `oneshot()` (stdlib `base64` only, no image processing — see Section
  3.3's dependency note), one new context-budget constant for attached-image cost.
- `bin/ltx-story-images` — `--seed-image` flag, resize+center-crop-and-copy path for
  panel 1, `images.json`'s new `"source"` field.
- New/extended test files covering the above (exact file(s) decided at implementation-plan
  time, following this repo's existing offline-test conventions — direct invocation,
  non-raising `check()`, not pytest).
