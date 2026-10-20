# Action LoRA library -- Design Spec (identity-agnostic motion LoRAs, e.g. martial arts)

Status: draft (2026-10-20). Author: pipeline work this session. Parallels the
character library (`docs/superpowers/specs/2026-10-05-character-library-design.md`)
and reuses the LoRA catalog (`2026-10-17-robust-story-lora-catalog-design.md`) and
the LoRA architecture gate (`bin/lora-check`).

## 0. Purpose and scope

### 0.1 Purpose
Teach the LTX-2.3 MLX video DiT a **named, reusable action** -- a martial-arts
movement (roundhouse kick, sword draw, a kata beat), a gesture, a gait -- as a
**motion LoRA** that any character can perform. Where a *character* LoRA fixes
*who* is on screen (appearance, trained on stills), an *action* LoRA fixes *what
they do over time* (temporal dynamics, trained on multi-frame clips). The two
compose: character LoRA + action LoRA fused into one render so the cast member
does the move.

### 0.2 Grounding (shipped code, read this session)
- The LoRA catalog already models this: `lora_catalog.KINDS = ("style", "motion",
  "physics")` and `TARGETS = ("video", "stills")`. An action LoRA is
  **`kind: "motion"`, `target: "video"`**. No catalog schema change is required.
- Video LoRAs train via `ltx-2-mlx train --config <yaml> --low-ram` (the character
  video-LoRA path, `character_dataset.py`). Character video LoRAs train on 24
  **one-frame** stills (identity, no motion). Action LoRAs must train on
  **multi-frame clips** -- that is the core difference and the main new work.
- Application: `ltx-movie --lora PATH[:STRENGTH]` is the global video-DiT LoRA
  slot (repeatable; fused by `ltx-2-mlx` via `fuse_loras.py`). Character LoRAs
  apply per-panel at strength 0.8. Multiple `--lora` fuse together.
- `bin/lora-check` (this session) verifies a LoRA's tensors match the base DiT
  architecture and enforces `alpha == rank` (the `ltx-2-mlx` fuser does B@A*strength
  with no alpha/rank scaling). `bin/lora-catalog add` runs it as a gate.
- Geometry/temporal limits (`ltx2_mlx_video_skill.validate_geometry`,
  `2026-10-20-...` sweep): width/height multiples of 64; frames on the `8k+1`
  lattice, `>= 9`; one clip holds a single coherent ~6-10 s action (`<= ~241`
  frames); longer sequences are built by chaining panels, one beat per panel.

### 0.3 Deliverables
1. `generated/actions/<name>/action.json` (schema_version 1) + an action library
   module `action_lib.py` (stdlib) mirroring `character_lib.py`.
2. `bin/action` -- `create` (build the clip dataset, stop for review), `train`
   (train the motion LoRA via `ltx-2-mlx train`), `list`, `show`.
3. `action_dataset.py` -- clip ingestion, normalization, captioning, the
   `ltx-2-mlx train` invocation and the training safety gate.
4. `ltx-movie --action NAME[:STRENGTH]` and `--cast-action "PHRASE=NAME"`:
   compose an action LoRA with the cast per panel.
5. Catalog integration: trained action LoRAs register as `kind: "motion"`,
   `target: "video"` entries (and fold into the planner like character video LoRAs).
6. A render-smoke acceptance check: the action visibly appears on a neutral
   character and composes with a character LoRA without breaking identity.

### 0.4 Out of scope (this spec)
- Stills/image actions (actions are inherently temporal; `target: "stills"`).
- Pose/ControlNet conditioning as an alternative to LoRAs (a separate feature;
  noted as an alternative in Section 7).
- Violence/safety classification of martial-arts content. `content_safety` gates
  **NSFW**, not violence; action LoRAs do not change that gate (Section 6).
- Full motion-capture or physics simulation.

### 0.5 Success criteria
1. From a set of reference clips of one action by **varied performers**, `bin/action
   create <name>` builds a normalized, captioned clip dataset and stops for review.
2. `bin/action train <name>` produces a video LoRA that passes `bin/lora-check`
   against the LTX-2.3 base (`alpha == rank`, modules/dims match).
3. Rendering a neutral prompt with the action trigger (via `ltx-movie --action`)
   shows the action; the LoRA is **identity-agnostic** (does not drag in one
   performer's face).
4. `ltx-movie --character C --action A` renders C performing A: identity from the
   character LoRA, motion from the action LoRA, both fused in one pass.

### 0.6 Must-have vs nice-to-have
- Must: library + `action.json`, `bin/action create/train/list/show`, clip
  normalization, `ltx-2-mlx train` wiring, catalog registration, `--action`
  application, `lora-check` gate, identity-agnostic training.
- Nice: automatic clip segmentation (shot/beat detection), generated-clip
  bootstrapping (Section 7), per-panel action auto-selection by the story planner,
  a judge-clips acceptance score for "did the action render".

## 1. Architecture

### 1.1 Data flow
```
reference clips ──► action_dataset: normalize (geometry, fps, frame lattice),
  (varied performers)   trim to the action window, caption (motion descriptor +
                        trigger), identity-agnostic check
                               │
                               ▼
                    ltx-2-mlx train --config --low-ram  ──► motion LoRA (.safetensors)
                               │
                               ▼                         bin/lora-check (gate)
                    action.json + catalog entry (kind=motion, target=video)
                               │
                               ▼
   ltx-movie --character C --action A[:s]  ──► ltx-2-mlx generate --lora C 0.8 --lora A s
                               │                     (fused together, one render)
                               ▼
                    panel clip: C performs A
```

### 1.2 Module boundaries [spec choice]
Mirror the character pipeline so the existing guards and import rules carry over:
- `action_lib.py`: stdlib only (library read/write/validation, like `character_lib`).
  `bin/action list`/`show` import only this.
- `action_dataset.py`: stdlib + `PIL`/`psutil`, heavy imports (torch, cv2/av for
  clip decode) **only inside a child process**, as `character_dataset` does for
  Z-Image. `create`/`train` import this.
- `ltx-movie` loads `action_lib` by path inside functions (as it does `character_lib`).
- No new import into `ltx2_mlx_video_skill.py` (its forbidden-import test stays green);
  it already takes `--lora PATH STRENGTH`, so action LoRAs flow through unchanged.

### 1.3 Internal names [spec choice]
`generated/actions/`, `action.json`, `ACTION_LIBRARY_DIR` (test seam, like
`CHARACTER_LIBRARY_DIR`), `ACTION_TWO_SOURCE` not applicable. Trigger phrase shape
reuses `lora_catalog.TRIGGER_RE`.

## 2. The library on disk

### 2.1 Layout
```
generated/actions/<name>/
  action.json
  dataset/
    clips/        clip_00.mp4 ... normalized training clips (multi-frame)
    captions/     clip_00.txt  motion descriptor + trigger per clip
    contact_sheet.jpg   a grid of mid-clip frames for review
    manifest.json
  loras/
    video/        lora_weights_step_*.safetensors (the trained motion LoRA)
  logs/
```

### 2.2 `action.json` (schema_version 1) [spec choice]
```
{ "schema_version": 1,
  "name": "roundhouse-kick",
  "kind": "motion",                       // fixed: actions are motion LoRAs
  "trigger": "performs a roundhouse kick", // phrase inserted into Motion: fields
  "descriptor": "a spinning kick delivered with the rear leg ...",  // 8-60 words
  "default_strength": 0.7,
  "strength_range": [0.4, 1.0],
  "source": { "type": "clips", "paths": [ ... ] },  // operator-supplied refs
  "identity_agnostic": true,              // asserted by the dataset check (2.4)
  "dataset": { "clips": 16, "frames": 97, "width": 1344, "height": 768, ... },
  "lora": { "path": "...", "sha256": "...", "rank": N, "alpha": N, "base_model": "dgrauet/ltx-2.3-mlx-q8" },
  "status": "dataset" | "untrained" | "trained",
  "created_at": "..." }
```
Validation mirrors `character_lib.validate_character`: strict keys, `trigger`
matches `TRIGGER_RE`, descriptor 8-60 words, `default_strength` within
`strength_range` within `(0, 2]`, `alpha == rank`.

### 2.3 Trigger and composition semantics
- The `trigger` is a **Motion:** phrase (e.g. "performs a roundhouse kick"), not an
  Image: attribute -- actions describe what happens over the clip's seconds. It is
  inserted into the panel's Motion: field by the planner / `--cast-action`, using
  `lora_catalog.prefix_triggers` so missing triggers are prepended.
- One action per panel (reuses `ltx-movie`'s existing "one continuous motion per
  shot" rule). A multi-beat sequence (draw → strike → recover) is several panels,
  each with its own action trigger, chained.

## 3. Dataset building (`action_dataset`, normative)

### 3.1 Clip ingestion (A1)
Input is a set of operator-supplied reference clips of the **same action** performed
by **varied people** (different builds, clothing, settings). Each is decoded,
trimmed to the action window (operator in/out points, or whole clip in the MVP),
and normalized to the training geometry: width/height floored to multiples of 64,
frame count snapped to the nearest `8k+1 <= 241`, fps resampled to 24. Clips that
cannot be normalized (too short, wrong aspect) are reported, not silently dropped.

### 3.2 Identity-agnostic requirement (A2) [the load-bearing choice]
An action LoRA must bind to the **motion**, not a performer. The dataset check
requires clips from **>= 3 distinct performers** (operator-asserted, or a VLM
"is this the same person as clip 0?" check reused from `character_dataset.score_still`,
inverted: diversity, not identity). If clips are too homogeneous, `create` warns
that the LoRA may leak appearance; `--force` overrides. Captions deliberately omit
appearance (no gender/skin/hair/clothing) -- only the motion and the trigger --
so training has no appearance signal to lock onto.

### 3.3 Captioning (A3)
`caption = "<trigger>, <shot>, <one motion clause>"`, appearance-free, one per clip.
Parallels `character_dataset.caption` but motion-first and identity-free.

### 3.4 Review gate (A4)
`create` writes `contact_sheet.jpg` (mid-clip frame per clip) and stops with
`status: "dataset"`. The operator inspects that every clip shows the action cleanly
and the performers vary, then runs `bin/action train`, or edits `descriptor`/clips
and re-runs `create --regenerate`. Minimum **>= 8** usable clips to train (parallels
the character `MIN_KEEP = 12`; fewer, because clips carry far more frames of signal).

## 4. Training (`action_dataset`, normative)

### 4.1 Invocation (A5)
`ltx-2-mlx train --config <generated.yaml> --low-ram`, the same binary and flag the
character video-LoRA path uses, but the config points at the **multi-frame** clip
dataset (not 1-frame stills). The config sets rank; `alpha` is set equal to rank
(A6) so the result satisfies `ltx-2-mlx`'s fuser and `bin/lora-check`.

### 4.2 Base-model pin (A6)
Trained against the configured LTX-2.3 MLX base (`ltx2_mlx_video_skill.MODEL_ID`,
currently `dgrauet/ltx-2.3-mlx-q8`). `base_model` is recorded in `action.json` and
the catalog entry. On a base change (e.g. a future 2.5 MLX build), `bin/lora-check`
flags the LoRA as incompatible and it must be retrained -- the datasets and configs
are kept for exactly this (parallels the character-LoRA retraining note).

### 4.3 Concurrency and memory (A7)
Reuses `character_dataset`'s `busy_process` fail-closed gate (no train concurrent
with a render) and the `--low-ram` flag. Training a multi-frame video LoRA is
heavier than the 1-frame character case; the gate and the host memory budget
(128 GB dev host) must be re-measured, not assumed.

## 5. Application (`ltx-movie`, normative)

### 5.1 Flags (A8)
- `--action NAME[:STRENGTH]` (repeatable): apply action LoRA(s) to **every** panel,
  at `default_strength` or the given strength.
- `--cast-action "PHRASE=NAME[:STRENGTH]"`: apply the action only to panels whose
  Motion: names PHRASE (parallels `--cast` for characters), so different panels can
  carry different actions.

### 5.2 Composition with character LoRAs (A9) [spec choice]
Per panel, `ltx-movie` emits one `ltx-2-mlx generate` with multiple `--lora`:
the cast character LoRA(s) at their strength (default 0.8) **then** the action
LoRA(s) at theirs (default 0.7), all fused in one pass. Ordering is character-first,
action-second (determinism; the fuser is additive so order is not quality-critical,
but it is fixed for reproducibility). Total fused strength is not auto-capped; the
operator tunes. The planner inserts the action trigger into the panel's Motion:
field via `prefix_triggers`.

### 5.3 Catalog path (A10)
A trained action LoRA registers via `bin/lora-catalog add ... --kind motion --target
video --base-model dgrauet/ltx-2.3-mlx-q8 --trigger "<trigger>"`. The existing
`add` gate (`bin/lora-check`) blocks a mismatched LoRA. The robust story planner may
then auto-select a motion LoRA per panel when the Motion: field matches its trigger
(same mechanism as catalog style LoRAs; opt-in, `--no-auto-lora` disables).

## 6. Safety
- `content_safety.assert_frames_safe` continues to screen generated frames for
  **NSFW**; it is unchanged and does **not** classify violence. Martial-arts action
  LoRAs therefore pass the gate on violence grounds -- this is called out explicitly
  so it is a conscious project decision, not an oversight. If violence screening is
  later wanted, it is a new classifier in `content_safety`, out of scope here.
- Reference clips are operator-supplied; the operator is responsible for their rights
  and content. `create` records `source.paths` for provenance.

## 7. Alternatives considered / open questions
- **Where do clips come from?** MVP: operator supplies real reference clips (the only
  reliable identity-agnostic source). Phase 2 (nice-to-have): bootstrap by generating
  candidate clips with the base DiT and curating, or augment with pose-conditioned
  renders -- both risk the base model not performing the action, so they are deferred.
- **LoRA vs ControlNet/pose.** A pose-skeleton conditioning path (drive motion from a
  reference skeleton) is an alternative to a motion LoRA and may capture precise
  choreography better, but needs an LTX ControlNet and per-frame pose extraction; out
  of scope, noted for a future spec.
- **Action + character identity bleed.** Even with the A2 diversity check, a motion
  LoRA can subtly shift body proportions. Acceptance (0.5.3) must verify the character
  LoRA still dominates identity when both are fused; if not, lower the action strength
  default or add an identity re-anchor (character-library §12 re-anchoring).
- **Temporal length.** One clip = one action beat (<= ~10 s). A full kata is a chained
  multi-panel sequence; the spec does not try to fit a long form into one clip.

## 8. Phases
1. Library + `action.json` + `action_lib.py` (+ validation tests).
2. `action_dataset` ingestion/normalization/captioning + `bin/action create` (review
   gate), unit-tested on synthetic clips.
3. Training wiring (`ltx-2-mlx train`) + `bin/action train` + catalog registration.
4. `ltx-movie --action`/`--cast-action` composition + `lora-check` gate integration.
5. Acceptance: render-smoke (action appears; identity-agnostic; composes with a
   character LoRA). Optional judge-clips score.

## 9. Acceptance criteria (restating 0.5 as checks)
- AC1: `bin/action create` on >= 8 varied clips yields a reviewable dataset and
  `status: "dataset"`; `--regenerate` rebuilds from `action.json`.
- AC2: `bin/action train` yields a LoRA that `bin/lora-check --deep` passes against
  the LTX-2.3 base.
- AC3: `ltx-movie --action <A>` on a neutral prompt shows the action; swapping the
  neutral subject does not change the motion (identity-agnostic).
- AC4: `ltx-movie --character C --action A` renders C doing A, C's identity intact.
