# Character seed-image datasets by instruction editing

Date: 2026-10-21. Amends docs/superpowers/specs/2026-10-05-character-library-design.md, Section 4
(create). Status: built.

## 1. Problem

A seed-image `bin/character create` builds its 24 training stills from the seed image's *text
description*: the vision model writes a 25-55 word descriptor and Z-Image draws every still from
those words alone. The seed contributes nothing to the pixels but char_00 and the score reference.

The 2026-10-21 spike (scratchpad `edit_spike/`, seeds: the fubohockey upload and
~/Downloads/edomusician.png) showed what that loses:

- **Identity.** The no-seed hockey set is a different player in a white jersey; the seed is an
  orange #18. Describe-based stills of the musician are a look-alike, eyes shut in almost every
  frame ("eyes often closed" in the descriptor).
- **Equipment.** DESCRIBE_PROMPT deliberately leaves out held items, so the musician's shamisen,
  its tassel and his purple finger guard appear in no generated still. The dotted collar became
  plain.
- **Robustness.** A descriptor over 70 words failed the create outright (fixed separately by the
  retry-with-feedback in `describe()`).

Posing the seed itself with an instruction editor kept all of it:

| Arm (6 stills per seed) | s/still | hockey score | musician score | equipment |
|---|---|---|---|---|
| no-seed / describe-based | ~60 | 8.2 | - | lost |
| Qwen-Image-Edit-2511, 40 steps, CFG 4 | 1260 | 9 (1 still) | 10 (1 still) | kept |
| + Lightning 4-step | 69 | 9.2 | 9.2 | kept |
| + Lightning 8-step (chosen) | 140 | 9.3 | 9.5 | kept |

8-step over 4-step: more skin and hair texture, and it removed a stray object 4-step added. Known
costs, accepted: a slight over-sharpening, a colour shift (the charcoal kimono came out navy), and
pose copying (2 of 6 hockey edits kept the seed's skating stance).

The identity score is lenient: a white-jersey stranger scored 10 against the orange #18 seed.

## 2. Decisions

E1. **Every seed-image create edits the seed.** The 24 VARIANTS stills come from
    Qwen/Qwen-Image-Edit-2511 with lightx2v/Qwen-Image-Edit-2511-Lightning (8-step bf16), true
    CFG 1.0, 8 steps, 1024x640, generator seeded with character.json `seed`. There is no switch
    back to describe-based stills for seed images. Descriptor creates (`--descriptor`, no seed)
    are unchanged, including CHARACTER_TWO_SOURCE.

E2. **The descriptor is still written, for stories only.** Stories need it (cast lines, the image
    prompt checks in character_lib), so a seed create still runs `describe()` for the class noun
    and descriptor. Neither feeds the dataset. `--seed-image` now also accepts `--descriptor TEXT
    --class NOUN`, which skips describe; `--descriptor` without `--class` is refused as before.

E3. **Edit prompt** (EDIT_PROMPT, one per VARIANT):
    "Show this exact same person: keep their face, hair, clothing, colours, logos, accessories and
    anything they carry identical. Re-shoot them as a {shot}, {pose}, in {setting}. Change the
    camera angle, pose and background to match; the body position must clearly differ from the
    original photo. Photorealistic live-action film still, natural light."
    The last clause before the style sentence is new against the spike prompt, aimed at pose
    copying.

E4. **Preview stop.** The 6 EDIT_PREVIEW stills (VARIANTS 1, 3, 8, 10, 12, 21: one of every shot
    size, profile, walking, sitting, wide action) are edited first. create writes
    dataset/preview_sheet.jpg (unscored) and stops:
    "Review the preview stills in PATH. Enter to edit the remaining 18, Ctrl-C to abort: ".
    `--no-review` skips the stop and edits all 24 in one child run, the way `ltx-movie
    --no-review` skips its review gates. Without `--no-review` a seed create (or a --regenerate
    of a seed character) needs an interactive stdin and is refused up front otherwise (exit 2),
    as ltx-movie does. Ctrl-C at the stop restarts the vision server, leaves status "dataset",
    prints how to --regenerate, and exits 1.

E5. **One model in memory at a time.** The editor runs in a child process
    (`character_dataset.py qwenedit --spec SPEC`, the zimage-child pattern) with the story server
    stopped and at least EDIT_MIN_AVAIL_GIB = 64 GiB available (the bf16 model is 54 GB). The
    vision server is restarted in a `finally`, as for Z-Image.

E6. **Content screen.** Every edited image goes through `content_safety.assert_image_safe`
    (skill "character_edit") before it is saved; a blocked still is reported "blocked", is never
    written, and is dropped at scoring like a blocked Z-Image still.

E7. **No download at create time.** create checks both repos are in the local HF cache before any
    vision work and refuses with the download command otherwise (exit 2). The child loads with
    `local_files_only=True`.

E8. **Stricter identity check.** CHECK_PROMPT now tells the scorer to compare garment colours,
    numbers and logos and carried items or instruments, scoring a mismatch at most 5. Applies to
    every create.

E9. **Regenerate** of a seed character re-edits seed.png. Editing "descriptor" changes stories, not
    stills, so the seed-mode "next:" and too-few-kept hints point at "seed" in character.json
    instead.

E10. **movie-ui** passes `--no-review` on character-create and character-regenerate jobs (its jobs
     have no terminal).

E11. **Fixes found by the spike.** QWEN_AGENT_VLM_MODEL defaults to "auto" (the old default
     "qwen38-6bit" is not what story-server mlx-vision serves, so a shell create failed its VLM
     preflight). bin/character re-executes itself under CHARACTER_PYTHON (default
     ~/img-gen/bin/python) when create/train cannot import PIL or psutil.

E12. **Face-centred reference still.** char_00 (the always-kept reference and a training still)
     was a centre crop of the seed to 16:10, which cut a portrait seed's head off at the nose. It
     is now cropped around the face box (face centre 40% down the frame); the box is saved to
     seed_face.json for --regenerate, which runs no face check.

E13. **A too-long descriptor is shortened, not re-described.** Re-describing from the image with
     the rejection quoted still overshot (88 words on the fubohockey seed after 3 tries); a
     text-only DESCRIBE_SHORTEN request of the rejected descriptor gave 57-64 words keeping the
     clothing and its colours. Other rejections still retry with the reason quoted.

E14. **The check retries with the rejection too** (CHECK_ATTEMPTS = 3, CHECK_RETRY), "full shot"
     and "long shot" map to "wide shot", and a caption leaves out empty check fields: an
     unparseable check of the reference had produced "trigger man, , , in , ...".

## 3. Flow (seed-image create)

preflights (args, tty unless --no-review, edit models cached, lock, busy, disk, VLM) -> face check
-> describe (unless --descriptor) -> character.json -> stop story server -> wait 64 GiB ->
edit preview 6 -> [preview_sheet.jpg, stop unless --no-review] -> edit remaining 18 -> restart
VLM -> score 25 against char_00 -> captions, 1-frame mp4s, manifest, contact_sheet.jpg.

Time on the M-series host: ~140 s per still, about 58 min for 24 plus model loads.

Live, 2026-10-21, edomusician (portrait seed, shamisen): 6 preview stills in ~14 min, the
review stop, the other 18 in ~41 min; 22/25 kept; the shamisen, hakama and collar in nearly
every still. The stricter check dropped two wide shots (score 5) and the one edit that lost the
instrument.

## 4. Tests

tests/test_character_tool.py K19-K24 and tests/test_character_dataset.py D3b, D3c, D43-D48: the edit plan
and prompts, the preview order and the review stop (Enter, Ctrl-C, --no-review), the tty refusal,
the missing-model refusal, --seed-image with --descriptor, the edit child with fake torch/diffusers
(job loop, content block), and the movie-ui argv.
