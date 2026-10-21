# Character ensembles -- Design Spec (pair LoRAs built from existing characters)

Status: scope draft (2026-10-20). Parallels the character library
(`2026-10-05-character-library-design.md`) and shots mode (`2026-10-06-shots-mode-design.md`).
Motivating failure: `generated/stories/the_ronins_walk` panel 3, where `edobandit` and `ronin`
video LoRAs fused at 0.8/0.8 rendered two ronins and no bandit.

## 0. Purpose and scope

### 0.1 Problem
A character LoRA is trained on one person alone. When two are fused into one render
(`ltx2_mlx_video_skill.build_command` emits one `--lora PATH STRENGTH` each), both act on the
whole frame: nothing binds trigger A to the left man and trigger B to the right one, so the
identities blend and the one already in the conditioning frame wins. `panel_strengths` lowering
both to 0.8 (`character_lib.py:634-642`) reduces the restyling but not the blend. The library
spec's L6 sweep held only for a visually distinct pair (kyra + ronin), and shots mode records
"two characters at 0.8 in quiet shots held (user eyeball) but drifted (judge)".

### 0.2 Goal
From two **already trained** characters, build -- with one command and no hand-made data -- an
**ensemble**: one video LoRA and one stills LoRA trained on images of the pair together,
captioned with each member's existing trigger. When a panel names both members, the pipeline
uses the ensemble LoRA at 1.0 instead of the two member LoRAs; panels naming one member keep
using that member's LoRA. Stories, triggers and `cast_text` do not change.

### 0.3 Non-goals
- More than two members (matches `SHOTS_MAX_CAST_PER_PANEL = 2`, `character_lib.py:45`).
- Touch or contact between members: the no-contact rules (`SHOTS_CAST_BLOCK_RULES`,
  `bin/ltx-movie:206`) stay. An ensemble is for two people sharing a frame, not fighting in one.
- Motion: datasets stay one-frame clips, the same as member video LoRAs (`wrap_still`,
  `character_dataset.py:654`). Moves belong to the action library.
- Spatial masks or regional prompting: ltx-2-mlx has none (only temporal Prompt Relay).

## 1. Grounding (shipped code this builds on)

| Piece | Where | Reused as |
|---|---|---|
| Z-Image txt2img / img2img, multi-LoRA adapters, one LoRA set per process | `z_image_skill.py:161-196`, `:239-275`; child `character_dataset.py zimage --spec` `:1469-1532` | solo renders (member stills LoRA at 1.0), plate renders (no LoRA), harmonize pass (img2img) |
| VLM identity scoring vs a reference, face box | `CHECK_PROMPT` `:128`, `FACE_PROMPT` `:121`, `MIN_SCORE` 7 | per-person scoring inside each pair image |
| Caption format | `character_dataset.py:286` | extended with both triggers and left/right |
| Video LoRA preprocess + train YAML (rank 32, 1000 steps, q8-dev) | `:1055-1136`, `TRAIN_MODEL_DIR` `:149` | same trainer, larger dataset, more steps |
| Stills LoRA via mflux-train (rank 16) + module-count compat gate | `:1304-1432` | unchanged |
| story-server stop/restart, memory/disk gates, library lock, `busy_process()` | `:461-511`, `:781-795`, `:1241-1246`; `bin/character-train-vlm` | unchanged |
| Cast resolution, trigger insertion, strengths, manifest `characters`, render `loras` | `character_lib.py:549-642`; `bin/ltx-story-manifest:683-697`; `bin/ltx-mlx-render:235-360` | ensemble substitution hook |
| Shots stills grouping by cast set | `bin/ltx-movie:1820-1842`, `bin/ltx-story-images:256-330` | an ensemble is one LoRA set, so a pair shot fits one group |
| ltx-2-mlx `--image PATH FRAME_IDX STRENGTH` (repeatable, keyframe conditioning) | `~/ltx-2-mlx/.../cli.py:610-629` | optional entrance keyframe (Section 6) |

**Missing today:** a person matting model. No `rembg`/BiRefNet in any venv or HF cache;
`~/img-gen` has torch + transformers, enough to run BiRefNet (MIT) through transformers.

## 2. The combining pipeline (`bin/ensemble create`)

Automated end to end. For each of N pair items (default 24, `ENSEMBLE_ITEMS`):

1. **Plan the item.** Draw (shot, setting, pose A, pose B, side) from a variant table like
   `VARIANTS` (`character_dataset.py:72-97`), restricted to medium/wide shots that fit two people.
   A/B sides alternate 50/50 so neither trigger learns a fixed side. Poses are non-contact and
   separated (standing apart, facing each other, walking side by side, one in the foreground).
2. **Plate.** Render the empty setting with Z-Image, no LoRA, 1024x640, at the item's seed.
3. **Solo renders.** Render member A alone with A's stills LoRA at 1.0 and A's normal
   prompt (`gen_prompt` with A's descriptor and pose, plain backdrop), then B likewise. Two child
   processes, one LoRA set each. Identity is at full strength because nothing else is fused.
4. **Matte.** BiRefNet cuts each solo render to an RGBA person cutout. Reject if the mask is
   empty, touches more than one image edge, or covers under 5% / over 70% of the frame.
5. **Composite.** Scale each cutout to the shot's person height (bottom anchored on a shared
   ground line, the "foreground" pose larger), place A and B on their sides with a gap of at
   least 8% of the width (no overlap: no contact), alpha-blend onto the plate with a soft
   1-2 px feathered edge.
6. **Harmonize.** One Z-Image img2img pass over the composite at strength `HARMONIZE_STRENGTH`
   0.35 (tunable 0.25-0.45), prompt = the pair caption text plus both descriptors, with **both**
   members' stills LoRAs at 0.5. This fixes lighting, edges and shadows. Low strength keeps the
   identities from the solo renders, and the two LoRAs at 0.5 only nudge, they don't re-blend.
7. **Score.** Ask the VLM for both people's boxes, crop each, and score each crop against its
   member's dataset reference with `CHECK_PROMPT`. **Keep** only if both scores are at least
   `MIN_SCORE` 7 and the **swap test** passes: A's crop scores at least 2 higher against A's
   reference than against B's, and the same for B. The swap test is what catches a
   ronin/bandit-style blend.
8. **Caption.** `"<trigA> <classA> on the left and <trigB> <classB> on the right, <shot>,
   <poseA> and <poseB>, in <setting>, photorealistic live-action film still, natural light."`
   (sides follow the item), into `captions/pair_NN.txt`. Wrap the still as a one-frame mp4.

**Solo anchors.** The dataset also takes 8 kept stills from each member's existing
`dataset/` (their captions unchanged), so each trigger keeps meaning one person when that
person is alone. That gives 24 pair items + 16 solo = 40 by default.

**Gates.** Same as `create`: lock, not busy, 2 GiB disk, VLM served for scoring, story-server
stopped for the Z-Image steps and always restarted. Exit 3 if fewer than 12 pair items are kept.
A contact sheet (`dataset/contact_sheet.jpg`) shows kept and dropped items, dropped ones marked
with their reason (matte, score A, score B, swap).

**Distinctness pre-check.** Before any rendering, the VLM is shown both members' references and
asked whether they are easy to tell apart. A "no" (ronin vs edobandit is the expected case) only
warns, since the composite route still works, but it predicts a lower keep rate and is recorded.

## 3. Training (`bin/ensemble train`)

- **Video LoRA:** the member video path unchanged (`ltx-2-mlx preprocess --max-frames 1`, then
  `ltx-2-mlx train --low-ram` on `TRAIN_MODEL_DIR`), rank 32, alpha 32. Steps scale with
  dataset size: `round(1000 * kept / 24)`, about 1670 for 40 items. Validation prompts: one pair
  prompt, one solo prompt per member (`validation.prompts` is a list, trainer `config.py:170`).
- **Stills LoRA:** mflux-train as for members (rank 16, about 672 steps, scaled the same way);
  the module-count compat gate applies.
- **Test renders:** `tests/pair_video.mp4` (ensemble at 1.0), `tests/pair_video_members.mp4`
  (the two member LoRAs at 0.8, today's behaviour), and the same pair for stills. Seed 42, so
  the before/after comparison is like for like.
- Preconditions as `train`: story-server STOPPED, 30 GiB available, 8 GiB disk per kind; run
  through a `character-train-vlm`-style wrapper so the VLM always comes back.

## 4. Records

`generated/ensembles/<name>/ensemble.json`, schema_version 1, validated strictly like
`character.json`:

```json
{
  "schema_version": 1,
  "name": "ronin-edobandit",
  "members": [
    {"name": "edobandit", "trigger": "edobamn", "video_sha256": "...", "stills_sha256": "..."},
    {"name": "ronin", "trigger": "roninmn", "video_sha256": "b239...", "stills_sha256": "f516..."}
  ],
  "status": "dataset | untrained | trained | stale",
  "strength": null,
  "created_at": "...",
  "dataset": {"pair_kept": 19, "pair_total": 24, "solo": 16, "harmonize_strength": 0.35,
              "distinct": false, "contact_sheet": ".../dataset/contact_sheet.jpg"},
  "loras": {"video": {"path": "...", "sha256": "...", "base_model": "...", "rank": 32,
                      "alpha": 32, "steps": 1583, "trained_at": "...", "sample_path": "...",
                      "control_path": "..."},
            "stills": {"...": "same shape as character.json"}}
}
```

- `members` is sorted by name, so a pair has one canonical record; the name defaults to
  `<a>-<b>`. Triggers are copied, never new: the ensemble speaks the members' triggers.
- **Stale:** `ensemble_lib.load` compares each member's current LoRA sha256 with the recorded
  one. If a member is retrained, the ensemble reads `stale` and is not used for casting until it
  is retrained. Deleting a member makes the ensemble invalid.
- New module `ensemble_lib.py` (stdlib, mirrors `character_lib.py`); library dir
  `<WS>/generated/ensembles`, overridable with `ENSEMBLE_LIBRARY_DIR`.

## 5. Casting integration (the automatic swap)

- `resolve_cast` also loads trained, non-stale ensembles whose members are both in the cast.
- Per panel, after `cast_text` reports the names a prompt mentions (`character_lib.py:607-631`):
  if exactly two names are mentioned and an ensemble covers them, the panel's LoRA entries become
  **one** `{"kind": "ensemble", "name", "path", "strength"}` at 1.0 (or the ensemble's
  `strength`) **instead of** the two character entries. Trigger insertion is unchanged, so the
  prompt still reads "the edobamn bandit ... the roninmn ronin".
- Panels with one member keep that member's LoRA at 1.0 (unchanged `SINGLE_CHARACTER_STRENGTH`).
- Recorded in `manifest.json` `panel["characters"]` (both members, `via: "<ensemble>"`) and
  in clip provenance `loras` as kind `ensemble`; `ltx-mlx-render`'s validator accepts the kind.
- Shots-mode stills: an ensemble panel is one LoRA set, so `_shots_stills_groups` keys it by
  the ensemble name, and z_image_skill's one-set-per-process rule still holds.
- `--no-ensemble` restores today's behaviour (both member LoRAs at the pair strength).
- Global LoRAs (`--lora`, `--stills-lora`) still go first and are never counted.

## 6. Chained mode: the entrance problem (optional phase)

An ensemble fixes identities once both members are on screen. It does not fix a chained panel
whose first frame holds only one of them and whose text never describes the newcomer (the
`the_ronins_walk` case). Optional fix: when a chained panel names two members and the previous
panel named one, Phase 2 renders a **pair still** with the ensemble stills LoRA (the panel's
Motion text, both triggers, the previous clip's setting sentence) and Phase 3 passes it as a
late keyframe, `--image pair.png <idx> <strength>` alongside the chain seed at frame 0 (ltx-2-mlx
accepts repeated `--image`, `cli.py:610-629`). Default index: two thirds of the panel, strength
0.6, both to be tuned. This needs a live gate before it's on by default.

## 7. movie-ui

- Characters tab, new **Ensembles** section: pick two trained characters, Create (job kind
  `ensemble-create`), review the contact sheet with drop reasons, Train (`ensemble-train`). It
  uses the same job runner, queue, logs and cancel as character jobs.
- `/api/ensembles`, `/api/ensembles/<name>`, `/api/ensembles/<name>/train`.
- Compose pre-run checks (V5): for each cast pair that shares a panel, report `pass` (trained
  ensemble will be used), `skip` (`--no-ensemble`), or an advisory "no ensemble for ronin +
  edobandit; the two LoRAs will blend in shared panels".

## 8. Phases and size

| Phase | Content | New code (rough) | Tests |
|---|---|---|---|
| E1 | `ensemble_lib.py`: schema, validate, load, stale, list/show; `bin/ensemble list/show` | ~400 lines | `test_ensemble_lib.py` |
| E2 | Matting (BiRefNet in `~/img-gen`, `bin/model-download` entry), composite, harmonize, scoring with swap test, captions, contact sheet; `bin/ensemble create` | ~700 lines | `test_ensemble_dataset.py` (fake Z-Image, VLM and matting children, as `test_character_dataset.py` does) |
| E3 | `bin/ensemble train` (video + stills, scaled steps, test renders, wrapper) | ~250 lines | trainer argv/YAML tests |
| E4 | Casting swap, manifest/provenance kind, render validator, shots grouping, `--no-ensemble` | ~200 lines across 4 files | additions to `test_casting_pipeline.py`, `test_shots_mode.py`, `test_ltx_mlx_render.py` |
| E5 | movie-ui section, endpoints, V5 checks | ~300 lines | `test_movie_ui_*` additions |
| E6 (optional) | Chained entrance keyframe | ~150 lines | `test_ltx2_mlx_video_skill` |

Wall clock per ensemble on this host (estimates from member runs): dataset about 24 x (plate +
2 solos + harmonize) Z-Image renders plus about 72 VLM calls, roughly 30-45 min; training about
1.7x a member's video run plus a stills run.

## 9. Acceptance gates (live)

- **G1 composite quality:** `bin/ensemble create ronin-edobandit` keeps at least 12 of 24 pair
  items; a human pass over the contact sheet finds no pasted-on look on the kept items.
- **G2 the motivating case:** the `the_ronins_walk` panel 3 prompt rendered three ways at seed
  3: members at 0.8/0.8 (today), ensemble at 1.0, ensemble at 0.8. Pass: with the ensemble,
  `bin/judge-clips` and a human both find two distinct men, the bandit's stubble, cheek scar,
  grey sash and pendant visible, the ronin unchanged.
- **G3 no regression alone:** a ronin-only panel renders the same with and without the ensemble
  present (the swap must not trigger).
- **G4 distinct pair:** repeat G2 for kyra + ronin, which already held at 0.8; the ensemble must
  be no worse.
- **G5 stale:** retrain a member's stills LoRA, and the ensemble shows `stale` and is skipped with
  a warning.

## 10. Open questions

1. **Matting model.** BiRefNet (MIT, about 0.9 GB) is the proposal. RMBG-2.0 is stronger but its
   licence is non-commercial. Is a new download acceptable?
2. **Harmonize strength.** 0.35 is a guess; G1 should sweep 0.25 / 0.35 / 0.45.
3. **Retrain vs reuse.** Train the ensemble from scratch (proposed), or start from one member's
   LoRA? From scratch avoids a bias toward one member.
4. **Solo anchor count.** 8 per member is a guess; too few and triggers drift when alone, too
   many and the pair signal thins.
5. **Ensemble strength in shots mode.** 1.0 assumed; the lone-1.0 restyling of uncast extras
   seen in shots mode may apply here too.
