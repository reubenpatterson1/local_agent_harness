# ltx-movie narrative-chain redesign — design spec

Date: 2026-09-24
Status: APPROVED by the user (Approach A + derived-geometry revision). Ready for planning.
Branch: `ltx2-mlx-video-pipeline`
Workspace root (`WS`): `/Users/reubenpatterson/local_model_harness/qwen-agent-workspace`. Every relative path below is relative to `WS`.

---

## 1. Overview and motivation

`bin/ltx-movie` turns a narrative into a narrated multi-panel movie. Today every panel is imagined independently: one still per panel, one I2V clip per panel from that panel's own still, hard-cut together. Characters, setting and framing drift from panel to panel, and three separate center-crops cut the seed image.

The user's requirement (verbatim): "narrative -> story (focus on first setup frame) -> first image or seed -> first clip -> last frame as next clips seed -> until end then stitch. And the narrative prompts have to change to support the flow as well. Should be z_image_skill and ltx-2-mlx_video driven only … Also --seed-image produces a cropped instead of scaled downsized version."

This redesign:

1. Spends the creative effort on panel 1. Panel 1 gets the only still image: the `--seed-image` itself, or a z_image render of panel 1's `Image:` text.
2. Renders clip 1 as I2V from that still. Then it renders every later clip as I2V from the **exact last frame of the previous clip**, prompted by a short `Motion:`-only directive.
3. Stitches the clips at the end with the existing stream-copy concat.
4. Never crops the seed image. The video's width and height are **derived from the seed's aspect ratio**, on ltx-2-mlx's 64 px grid. Any residual gap is filled with a thin black pad.
5. Removes every ComfyUI, wan and cctech backend and the USB deployment tooling. The pipeline runs on `z_image_skill.py` and `ltx2_mlx_video_skill.py` only.

## 2. Current state and problems (verified against the working tree)

The working tree has uncommitted changes in `bin/ltx-movie`, `bin/ltx-mlx-render`, `ltx2_mlx_video_skill.py`, `z_image_skill.py` and their tests. These include clip provenance and the `LTX2_MLX_HF_HOME` / `Z_IMAGE_HF_HOME` scoped caches. **This spec applies to the working tree as it stands.** The implementer must not revert, re-stage or "clean up" any pre-existing uncommitted hunk that this spec does not name.

### 2.1 The pipeline is broken end to end today

| # | Defect | Location |
|---|---|---|
| P1 | `bin/ltx-mlx-render` fails at import: `import comfyui_mlx_video_skill` names a module that no longer exists in the tree. `python3 bin/ltx-mlx-render --help` exits with `ModuleNotFoundError`, so Phase 3 and Phase 4 always fail. | `bin/ltx-mlx-render:48` |
| P2 | `STORY_PROMPT_TEMPLATE` contains `{image_rules}` / `{motion_rules}` placeholders that `build_story_prompt` never fills. Every non-`--no-stills` run raises `KeyError` in Phase 1. | `bin/ltx-movie:106,108,172-182` |
| P3 | `model_identity()` imports `cctech_ltx25_runtime`. | `bin/ltx-mlx-render:250` |

### 2.2 The flow is wrong

- `_phase_sequence` (`bin/ltx-movie:1127-1137`) runs Phase 0 → 1 → 2 (all stills, `bin/ltx-story-images` loop `:254-317`) → 3 (manifest + dry-run) → 4 (one independent clip per panel; `image_path` is always that panel's own still, `bin/ltx-mlx-render:221`) → concat (`:457-465`).
- No path hands a clip's last frame to the next clip. The old torch backend's chaining (`bin/ltx-chain`, `bin/ltx-story-video --engine chain`) works on PNG frame directories plus `embeds.pt`, cannot be reached from `ltx-movie`, and is not reused.

### 2.3 The seed image is cropped three times

1. `bin/ltx-movie:659-676` `_crop_to_fill` (via `_downscale_seed_image`, `:679-724`) crops the copy the story LLM sees.
2. `bin/ltx-story-images:97-127` `_resize_center_crop` / `_write_seed_panel` crops `panel_01.png` to 1280x704.
3. ltx-2-mlx `resize_and_center_crop` (`~/ltx-2-mlx/packages/ltx-pipelines-mlx/src/ltx_pipelines_mlx/utils/media_io.py:226-245`) crops again: the 1280x704 still (ratio 1.82) does not match the 704x448 video (ratio 1.57).

EXIF orientation is also ignored (`bin/ltx-movie:704-707`, `bin/ltx-story-images:122-124`), so a portrait phone JPEG is treated as landscape.

### 2.4 ltx-2-mlx geometry facts (verified in source)

- The distilled pipeline is two-stage. `distilled.py:278` calls `snap_output_dimensions(height, width, two_stage=True)` (`ltx-core-mlx/src/ltx_core_mlx/components/patchifiers.py:127-177`). That call silently **floors both width and height to multiples of 64**, never below 64.
- I2V conditioning is encoded twice: at half size (`distilled.py:293-306`, `enc_w_half = W_half*32`) and at full size (`:377-382`). Both go through `resize_and_center_crop`. When the image is exactly W×H and W and H are multiples of 64, both resizes are exact scalings (1/2 and 1/1) and **nothing is cropped**.
- `ltx2_mlx_video_skill.validate_geometry` (`:81-99`) only requires multiples of 32. A request for 736 wide passes, ltx-2-mlx renders 704, and `render_panel` then fails the clip's uniformity check **after** the full GPU spend.

### 2.5 Measured resolutions

- `ltx_ceiling.json` is **not** MLX evidence. Its `meta` records `diffusers_version 0.40.0` and `generated_at 2026-09-08`, which is earlier than the MLX pipeline (2026-09-10/11). Its entries are torch/MPS frame ceilings.
- Every `generated/stories/*/runs/*/story_summary.json` on this host with an MLX backend is **704x448**, at 241 or 9 frames. The only verified MLX geometry is 704x448x241: acceptance run A1, 160 s per panel, 13.5 GiB.

## 3. Decisions (all resolved)

| ID | Decision |
|---|---|
| D1 | Backends: `z_image_skill.py` + `ltx2_mlx_video_skill.py` only. Full deletion list in §10. |
| D2 | No cropping anywhere in the pipeline. The seed is scaled to fit and centred, and any residual gap is black-padded. |
| D3 | With `--seed-image`, video width and height are **derived from the seed** (§5). Without it, the video is 704x448. |
| D4 | Flow: narrative → story (panel 1 is the full setup) → panel 1 still → clip 1 → last frame of clip N-1 seeds clip N → stitch. |
| D5 | With `--seed-image`, the seed itself is panel 1's still and z_image is not run. Without it, z_image renders panel 1's `Image:` at 2W×2H. |
| D6 | `ltx-movie --frames` defaults to **145** (6.04 s at 24 fps). `--length` divides by 145/24, so `--length 60` resolves to 10 panels. |
| D7 | Panel 1's clip prompt is its `Motion:` text only; the still carries the scene. Panels 2 and later use their `Motion:` text. |
| D8 | `--no-stills` stays independent text-to-video with hard cuts and no chaining. The template is unchanged except for the per-clip seconds figure (§6.4). |
| D9 | Every derived chain frame goes through the existing content screen before use, unless `--skip-input-screen` is set. |
| D10 | An old-format story.md with `Image:` on panels 2 and later still renders; those `Image:` fields are ignored with a warning. |
| D11 | Accepted for v1: one repeated frame (~42 ms) at each join, a hard audio cut at each join, and gradual colour/sharpness drift across many hops. Fixes are follow-ups (§12). |
| D12 | Resolution cap: area ≤ 77 cells of 64² (the 704x448 area, the only measured MLX point). Raising it is an out-of-scope follow-up, gated on hardware measurement. |
| D13 | `PAD_TOLERANCE_PX = 8`. |
| D14 | A seed whose aspect is outside 1:3 … 3:1 is a hard error, exit 2, raised in Phase 0 before Phase 1 runs (and in `--dry-run`). |
| D15 | The hardware gate (§11.2) is REQUIRED. The work is not done until it passes. |
| D16 | The `Style:` field and its grounding machinery are dropped from the `ltx-movie` flow. |

## 4. New flow (Approach A: the chain loop lives in `bin/ltx-mlx-render`)

The phase tools stay separate subprocesses. `_phase_sequence` keeps its current shape: `(phase0_seed,)` is prepended only with `--seed-image`, and `phase_release_story_server` is inserted after Phase 1 only with `--story-server-stop-after-story`.

| Phase | Stills mode (default) | `--no-stills` |
|---|---|---|
| 0 | Seed only: validate the seed, derive W×H (§5), write `seed_downscaled.png` for the LLM. | not allowed with `--seed-image` (unchanged) |
| 1 | Story via `bin/qwen-agent` using the chained templates (§6). | unchanged `NO_STILLS` template |
| 1b | optional, unchanged | optional, unchanged |
| 2 | `bin/ltx-story-images --only 1`: seed fit to W×H, or z_image at 2W×2H. | skipped (unchanged) |
| 3 | `bin/ltx-story-manifest --chain --image images/panel_01.png`, then `bin/ltx-mlx-render --dry-run`, then the review gate. | `--no-images` (unchanged) |
| 4 | `bin/ltx-mlx-render`: strict in-order loop, chaining last frames (§8), `--on-panel-failure stop`. | independent loop (unchanged), `--on-panel-failure skip` |

Stitching is unchanged: the concat demuxer with `-c copy` and the existing uniformity preflight (`bin/ltx-mlx-render:457-465`, `assert_clips_uniform`).

## 5. Geometry: derived dimensions

### 5.1 New module `ltx_image_fit.py` (at `WS` root)

It is stdlib-only at import time. PIL is imported inside the functions that need it. The module docstring states: no-crop policy, the 64 px grid source (`patchifiers.py snap_output_dimensions`), and the fact that 704x448 is the only measured MLX area.

Constants (exact names and values):

```python
GRID_PX = 64            # ltx-2-mlx two-stage snap modulus (patchifiers.py snap_output_dimensions)
MIN_CELLS = 5           # 320 px minimum edge; stage-1 half-size edge 160 px = 5 latent cells
MAX_CELLS = 15          # 960 px maximum edge; with MIN_CELLS this bounds aspect to [1:3, 3:1]
MAX_AREA_CELLS = 77     # 704*448 / 64**2 -- the only MLX-measured area (acceptance run A1)
MIN_AREA_CELLS = 40     # 163,840 px = 0.52x of 704x448; resolution floor
PAD_TOLERANCE_PX = 8    # total residual pad (width deficit + height deficit) treated as "no bar"
DEFAULT_VIDEO_WIDTH = 704
DEFAULT_VIDEO_HEIGHT = 448
```

Functions (exact signatures):

1. `load_oriented_rgb(path) -> PIL.Image.Image`
   - `from PIL import Image, ImageOps` inside the function.
   - `with Image.open(path) as img: img.load(); out = ImageOps.exif_transpose(img).convert("RGB")`, then `return out`.
   - Exceptions propagate to the caller.

2. `fit_pad_px(src_w, src_h, width, height) -> tuple[int, int, int]` (pure):
   ```
   s = min(width / src_w, height / src_h)
   new_w = min(width,  max(1, round(src_w * s)))
   new_h = min(height, max(1, round(src_h * s)))
   return new_w, new_h, (width - new_w) + (height - new_h)
   ```

3. `derive_video_dims(src_w, src_h) -> tuple[int, int, int]` returns `(W, H, pad_px)` and is pure and deterministic.
   1. **Range check, integer arithmetic.** If `src_w * MIN_CELLS > src_h * MAX_CELLS` (wider than 3:1) or `src_w * MAX_CELLS < src_h * MIN_CELLS` (taller than 1:3), raise `ValueError` with exactly this message:
      `"seed image is %dx%d (aspect ratio %.3f:1), outside the supported range 1:3 to 3:1; supply a seed image whose width/height ratio is between 0.333 and 3.0"`
      Exactly 3:1 and exactly 1:3 are accepted.
   2. **Candidates.** Every integer pair `(a, b)` with `MIN_CELLS <= a <= MAX_CELLS`, `MIN_CELLS <= b <= MAX_CELLS` and `MIN_AREA_CELLS <= a*b <= MAX_AREA_CELLS`. For each, `W = a*GRID_PX`, `H = b*GRID_PX`, and `pad = fit_pad_px(src_w, src_h, W, H)[2]`.
   3. **Selection.** If any candidate has `pad <= PAD_TOLERANCE_PX`, choose the one with the largest `a*b`; break ties by smaller `pad`, then larger `a`. Otherwise choose the smallest `pad`; break ties by larger `a*b`, then larger `a`.
   4. Return `(W, H, pad)`.

4. `fit_letterbox(img, width, height) -> PIL.Image.Image`
   - `new_w, new_h, _ = fit_pad_px(img.width, img.height, width, height)`.
   - Resize `img` to `(new_w, new_h)` with `Image.Resampling.LANCZOS`.
   - Paste at `((width - new_w)//2, (height - new_h)//2)` onto `Image.new("RGB", (width, height), (0, 0, 0))` and return the result.
   - It never crops. Padding is non-zero only for the leftover gap the grid cannot close.

### 5.2 Golden values

These come from a reference implementation of §5.1 and become test fixtures verbatim.

| Seed (w×h) | Derived W×H | pad_px |
|---|---|---|
| 704x448 | 704x448 | 0 |
| 1280x704 | 704x384 | 6 |
| 1920x1080 | 576x320 | 7 |
| 1080x1920 | 320x576 | 7 |
| 4032x3024 | 512x384 | 0 |
| 3024x4032 | 384x512 | 0 |
| 6000x4000 | 576x384 | 0 |
| 1024x1024 | 512x512 | 0 |
| 2560x1080 | 768x320 | 9 |
| 1170x2532 | 320x704 | 11 |
| 3000x1000 | 960x320 | 0 |
| 1000x3000 | 320x960 | 0 |
| 935x1000 | 512x576 | 28 |
| 4000x3000 | 512x384 | 0 |
| 800x600 | 512x384 | 0 |
| 396x704 | 320x576 | 7 |
| 1280x427 | 960x320 | 1 |
| 704x704 | 512x512 | 0 |
| 3001x1000 | ValueError | — |
| 1000x3001 | ValueError | — |

**Pad distribution.** Over aspect ratios sampled log-uniformly from 1:3 to 3:1, the residual pad is 0-4 px for 28%, 5-9 px for 30%, 10-14 px for 22%, 15-19 px for 15%, and 20-29 px for 5%. The worst case is 28-29 px total (~14 px per side), for near-square ratios around 0.935:1. A pad of "a few pixels" cannot be guaranteed for every ratio on a 64 px grid within the measured area. This is a known, accepted property of v1.

**Resolution cost.** Common photo ratios render below 704x448 area under D12: 16:9 at 576x320 (0.58x), 4:3 at 512x384 (0.62x).

### 5.3 Command-line changes in `bin/ltx-movie`

- **Remove** `--image-width` and `--image-height` (`:215-216`). The still size is derived.
- **Remove** `--video-backend` (`:220`) and the `comfyui-mlx` validation block in `main()` (`:1146-1159`).
- `--video-width` and `--video-height` now default to `None`.
- In `main()`, immediately after `_resolve_length`, in this order:
  1. If `--seed-image` is given and either `--video-width` or `--video-height` was passed explicitly (`args.video_width is not None or args.video_height is not None`): print `Error: video geometry is derived from --seed-image; omit --video-width/--video-height` to stderr and return 2.
  2. If there is no seed: for each of `args.video_width` and `args.video_height` that `is None`, set it to 704 or 448 respectively. Then, if either is not a multiple of 64 or is below 64, print `Error: --video-width/--video-height must be multiples of 64 (ltx-2-mlx two-stage floors to 64), got %dx%d` and return 2.
  3. The existing `--seed-image` + `--no-stills` conflict check stays where it is.
- `--frames` default changes from 241 to **145**. Help text becomes: `"flat per-panel frame count; must satisfy (n-1)%%8==0 and n>=9. 145 frames @ 24 fps = 6.04s per clip."`
- `--length` help: replace `10.04s per panel at the defaults` with `6.04s per panel at the defaults`.
- `--panels` help: `"number of chained clips; panel 1 also gets the movie's one still image; mutually exclusive with --length"`.
- `--seed-image` help: `"image that becomes the movie's literal first frame: Phase 0 derives the video width/height from its aspect ratio (1:3 to 3:1) and attaches a scaled copy to the Phase 1 story prompt; Phase 2 fits the ORIGINAL (scaled, never cropped) into panel_01.png at the video size. Incompatible with --no-stills and with --video-width/--video-height."`
- The `build_parser` description is replaced with: `"End-to-end orchestrator for the narrative-to-movie pipeline: story authoring (bin/qwen-agent), panel 1's still (bin/ltx-story-images --only 1), manifest + render dry-run (bin/ltx-story-manifest --chain, bin/ltx-mlx-render --dry-run), and the chained render (bin/ltx-mlx-render), in which every clip after the first continues from the previous clip's last frame. The wrapped phase tools remain individually usable."`

### 5.4 Phase 0: `phase0_seed`, with `_prepare_seed_image` replacing `_downscale_seed_image`

**Delete** `_crop_to_fill` (`:659-676`) and `_downscale_seed_image` (`:679-724`). **Add** two functions.

A module-level helper `_image_fit()` returns `importlib.machinery.SourceFileLoader("ltx_image_fit", os.path.join(WS, "ltx_image_fit.py")).load_module()`. It is called only inside function bodies.

**`_seed_geometry(seed_path) -> (violations: list[str], geometry: tuple | None, img)`** performs these steps in order and returns at the first violation, with `geometry=None, img=None`:

1. If the path is not a file: `"--seed-image not found: %s"`.
2. `fit = _image_fit()`, then `img = fit.load_oriented_rgb(seed_path)` inside one `try`:
   - `except ImportError as e` → `"--seed-image needs Pillow, which is not importable: %s"`;
   - `except Exception as e` → `"--seed-image is not a readable image: %s: %s" % (type(e).__name__, e)`.
3. If `min(img.size) < SEED_MIN_EDGE`: `"--seed-image is degenerate: %dx%d (each edge must be at least %d px)"`, where the size is the post-EXIF size.
4. `W, H, pad = fit.derive_video_dims(*img.size)`. On `ValueError` the violation is `str(e)`.
5. Return `([], (W, H, pad), img)`.

**`_prepare_seed_image(seed_path, out_path) -> (violations, geometry)`**:

1. Call `_seed_geometry(seed_path)`. On violations, return `(violations, None)` and write nothing.
2. `k = SEED_DOWNSCALE_MAX_EDGE / max(W, H)`, then `llm = _image_fit().fit_letterbox(img, round(W*k), round(H*k))`. For example, 576x320 → 1024x569 and 704x448 → 1024x652.
3. `os.makedirs(dirname(out_path), exist_ok=True)` and `llm.save(out_path, format="PNG")`. On `OSError`: `(["cannot write the downscaled seed copy to %s: %s" % (out_path, e)], None)`.
4. Return `([], (W, H, pad))`.

`SEED_DOWNSCALE_MAX_EDGE = 1024` and `SEED_MIN_EDGE = 64` are kept. The LLM copy keeps frame 0's exact aspect and relative pad at 1024 px, so the vision model can describe faces.

`phase0_seed(args)` calls `_prepare_seed_image(args.seed_image, paths["seed_downscaled"])`.
- On violations it prints each as `Error: %s` and returns 2. Because `phase0_seed` is first in the sequence, this happens before Phase 1 (D14).
- On success it sets `args.video_width, args.video_height = W, H`, `args.seed_pad_px = pad` and `args.seed_downscaled_path = paths["seed_downscaled"]`, then prints:
  `"seed image OK: %s (%dx%d after EXIF orientation) -> video geometry %dx%d (residual pad %d px, %.2fx of the measured 704x448 area); story-model copy %s"`

### 5.5 Phase 2 argv (`phase2_stills` and its dry-run mirror)

```
[sys.executable, WS/bin/ltx-story-images, "--story-md", story_md, "--out-dir", images_dir,
 "--only", "1", "--width", str(SW), "--height", str(SH), "--seed", str(args.image_seed)]
+ (["--seed-image", args.seed_image] if seed)
```

- Seed mode: `SW, SH = args.video_width, args.video_height`.
- Otherwise: `SW, SH = 2*args.video_width, 2*args.video_height`, which is 1408x896 at the defaults.

### 5.6 `bin/ltx-story-images`

- **Delete** `_resize_center_crop` (`:97-112`).
- `_write_seed_panel(seed_path, out_path, width, height)`: its body becomes `import ltx_image_fit` (inside the function; `WS` is already on `sys.path`, line 51) followed by `ltx_image_fit.fit_letterbox(ltx_image_fit.load_oriented_rgb(seed_path), width, height).save(out_path, format="PNG")`.
- Update the `--seed-image` help text and any docstring sentence that says "crop" for the seed path. New wording: the seed is "scaled to fit (never cropped) and centred on a black --width x --height canvas".
- Nothing else changes. The grounded `Style:` mode stays for standalone use; new story.md files carry no `Style:`, so it is inert under `ltx-movie`.

### 5.7 Render side

- `_render_flags` (`bin/ltx-movie:299-317`) already passes `--width/--height` from `args.video_width/args.video_height`. `render_panel` already passes them into `generate_video(width=, height=)` (`bin/ltx-mlx-render:571-576`). No new wiring; the skill's 704/448 module defaults only apply to standalone callers.
- `_render_flags` drops the `"--video-backend", args.video_backend` pair.
- **`ltx2_mlx_video_skill.validate_geometry`** changes. The multiple-of-32 checks become multiples of 64, and the minimum becomes 64. New messages:
  - `"width must be a multiple of 64 (ltx-2-mlx distilled two-stage floors to 64; patchifiers.py snap_output_dimensions), got %d"`
  - the same for height
  - `"width must be >= 64, got %d"` and `"height must be >= 64, got %d"`

  The `num_frames` checks are unchanged. This is the only change to `ltx2_mlx_video_skill.py`.
- `z_image_skill.py`: no change.
- **v3 still-aspect preflight** in `bin/ltx-mlx-render main()`. It runs after the ffmpeg/ffprobe/binary presence checks and before the content screen, and only for schema_version 3 manifests. For each `conditioning == "still"` panel:
  - Run `ffprobe -v error -select_streams v:0 -show_entries stream=width,height -of json IMAGE` with a 60 s timeout.
  - On failure, or if `img_w * args.height != img_h * args.width`, print `Error: panel %d's still %s is %dx%d; its aspect ratio does not match --width x --height (%dx%d), so ltx-2-mlx would crop it` (or the ffprobe error) and return 2. No GPU time is spent.

### 5.8 Dry run (`_print_dry_run_plan`)

In seed mode, call `_seed_geometry(args.seed_image)`. It writes nothing.
- If the only violation starts with `--seed-image needs Pillow`, print `W`/`H` as the literal placeholders `<W>` and `<H>` in every printed command, plus the line `video geometry: derived from the seed at Phase 0 (Pillow not importable in this interpreter)`.
- On any other violation (missing file, unreadable, degenerate, out of range), print `Error: %s` and return 2.
- On success, set `args.video_width/args.video_height` for the printed commands and print the same geometry line as Phase 0.

The Phase 0 block text becomes: `"Would validate %s (readable image, every edge >= %dpx, aspect 1:3 to 3:1), derive the video geometry from it, and write a scaled story-model copy (long edge %dpx) to %s. Phase 2 fits the ORIGINAL into panel_01.png at the video size; nothing is cropped."`

## 6. Prompt templates (`bin/ltx-movie`)

### 6.1 `build_story_prompt`

New signature: `build_story_prompt(narrative, story_id, panels, no_stills=False, seed_image=False, *, seconds)`, where `seconds` is keyword-only and required.

- Both call sites (`phase1_story`, `_print_dry_run_plan`) pass `seconds=_clip_seconds(args)`, with a new helper `_clip_seconds(args) -> str` returning `"%.0f" % (args.frames / args.fps)`. That is `"6"` at the defaults.
- Template selection is unchanged: `NO_STILLS` when `no_stills`; otherwise `STORY_PROMPT_TEMPLATE`, wrapped as `SEED_IMAGE_PREFACE + "\n\n" + rendered + "\n\n" + SEED_IMAGE_POSTFACE` when `seed_image`. The existing comment explaining why the postface comes last is kept.
- Every template is rendered with `.format(narrative=..., story_id=..., panels=..., seconds=...)`. No other placeholder may exist. A rendered template must contain no `{` or `}` when the narrative contains none.

### 6.2 `STORY_PROMPT_TEMPLATE`: replace wholesale with this exact text

```
You are authoring the shot list for a short narrated movie (story-id "{story_id}").

Narrative to adapt:
{narrative}

How this movie is made: it is ONE continuous take, built {seconds} seconds at a time. Panel 1's Image: field is rendered as a single still picture, and that picture becomes the movie's first frame. Every later panel is a {seconds}-second continuation that starts from the exact last frame of the panel before it. The picture is never re-described after Panel 1: the characters, their appearance, the setting, the lighting and the style all carry forward automatically from the frames already on screen. There are no cuts, no scene changes and no jumps in time or place between panels. If the story needs a new location, a new prop or a new character, it must arrive through visible movement inside a panel -- someone walks through a door, turns a corner, or picks something up.

Write the complete story to generated/stories/{story_id}/story.md using the write_file tool. The file must contain EXACTLY {panels} panel sections, numbered 1 through {panels} in order.

Panel 1 has exactly three fields, in this order:

## Panel 1 — <short title>
Image: <120-170 words describing the movie's opening frame as one still picture: every character who is on screen, each with their full visual description (apparent age group, build, skin tone, hair colour, length and style, clothing and accessories), where each one stands and which way they face, the setting and background, the lighting and colour palette, the shot type (exactly one of: extreme wide shot, wide shot, medium shot, medium close-up, close-up, extreme close-up), the camera viewpoint, and the rendering style. Introduce each character with a short referring phrase of at most four words, such as "the woman in grey", and use that exact phrase for them everywhere else in the file.>
Motion: <25-50 words: what the characters physically do during these first {seconds} seconds, and how the camera moves -- or that it stays static.>
Narration: <one sentence of voice-over narration>

Every later panel has exactly two fields, in this order, and no Image: field:

## Panel N — <short title>
Motion: <15-35 words in one or two plain sentences: what the characters physically do during these {seconds} seconds, continuing from where the previous panel left them. Name each character only by their referring phrase from Panel 1, word for word. Give at most two actions, and only actions that fit inside {seconds} seconds. Do not describe appearance, clothing, setting, lighting, colour, style, camera or lens -- all of that is already on screen.>
Narration: <one sentence of voice-over narration; vary the sentence length across panels rather than repeating a similar length every time>

Give the story a narrative arc -- an introduction, a middle, a climax and a conclusion -- carried by what the characters do from panel to panel and by the narration. Each panel should move the action forward instead of repeating the previous panel's movement.

Write the file in a single write_file call. Trust your first draft: do NOT read the file back, do NOT run run_python or any other tool to check it, and do NOT count or recount words. Once the write_file call returns, stop immediately and emit no further text or tool calls.
```

### 6.3 `SEED_IMAGE_PREFACE` and `SEED_IMAGE_POSTFACE`: replace wholesale

`SEED_IMAGE_PREFACE`:

```
An image is attached to this message. It IS the first frame of this movie: the pipeline uses the attached image itself as Panel 1's picture, so nothing you write is rendered into Panel 1's picture.

Before you write anything, look closely at the attached image. Panel 1's Image: field must be a faithful, literal description of what the attached image actually shows -- each person's apparent age group, build and body shape, skin tone, eye shape and colour, hair colour, length, style and texture, clothing and accessories, their pose and where they are in the frame, the setting, the lighting, the colour palette and the visual style. It is not a generative prompt, not an embellishment and not an invention: do not add people, objects or scenery that are not visible in the attached image, do not leave out the ones that are, and do not change anyone's age, gender or physical attributes unless the narrative directs it. Choose each person's short referring phrase from what is actually visible.

Panel 1's Motion: must start from the exact pose and position shown in the attached image.
```

`SEED_IMAGE_POSTFACE`:

```
Reminder, because the attached image is the first frame: Panel 1 has exactly three fields -- Image:, Motion:, Narration: -- and its Image: field literally describes the attached image. Every later panel has exactly two fields -- Motion:, Narration: -- with no Image: field and no appearance, clothing, setting, lighting, style or camera words; characters are named only by their Panel 1 referring phrase.

Do not verify the file with run_python or any other tool. Emit no other text.
```

### 6.4 `STORY_PROMPT_TEMPLATE_NO_STILLS`

The only change: in `carrying enough separate beats to fill the full ten seconds instead of rushing the action`, replace `ten seconds` with `{seconds} seconds`. Nothing else in that template changes.

### 6.5 Story validation (`_validate_story_md`)

New signature: `_validate_story_md(story_md_path, expected_panels, no_stills=False)`. The `require_style` parameter is removed, along with its call-site logic in `phase1_story` (`:813-814`).

- The panel-count check is unchanged.
- The `no_stills` branch is unchanged.
- The stills branch replaces the current per-panel `Image/Motion/Narration` check:
  - Panel 1 (`panels[0]`): non-empty `Image:`, `Motion:` and `Narration:`. The message format is the existing `"panel %d: missing/empty %s: field"`.
  - Every panel `p` in `panels[1:]`: non-empty `Motion:` and `Narration:`, with the same format.
  - Every panel with a non-empty `Prompt:`: `"panel %d: has a Prompt: field; the chained flow expects Image:, Motion: and Narration: on panel 1 and Motion: and Narration: on later panels"`.
- The `Style:` requirement block (`:436-446`) is deleted.

**Advisory warnings.** They never change a return code. Add `_chain_image_warnings(panels) -> list[str]`: for each `p` in `panels[1:]` with non-empty `p["image"]`, emit `"panel %d: has an Image: field, which is ignored -- panels after the first continue from the previous clip's last frame"`. In `phase1_story`, the two style-warning loops (`:829-832`) are replaced by one loop: `for w in _chain_image_warnings(_load_story_panels(story_md)): print("Warning: %s" % w)`. It is guarded by `if not args.no_stills`.

**Orphans to delete** from `bin/ltx-movie`: `_ECHO_STOPWORDS`, `_ECHO_MIN_STYLE_WORDS`, `_ECHO_MIN_OVERLAP`, `_ECHO_FRACTION`, `_content_words`, `_style_echo_warnings`, `_STYLE_BANNED_TOKENS`, `_style_content_warnings`. Keep `_load_story_panels`. The `re` import is removed only if nothing else in the file still uses it.

### 6.6 Parser

`bin/ltx-story-manifest:_parse_prompts_md` is unchanged. The `Style` label stays in `_PANEL_LABEL_RE` (`:69`), so an old story.md's `Style:` text is captured and ignored rather than being appended to `Narration`.

## 7. Manifest schema v3 (`bin/ltx-story-manifest`)

### 7.1 Schema

Only `--chain` writes schema_version 3. The `--glob`, `--image` (without `--chain`) and `--no-images` modes keep writing schema_version 2, byte-for-byte as today; `tests/test_ltx_story_video.py` M4c pins that.

v3 = v2 plus one required per-panel key: `"conditioning": "still" | "chain" | "t2v"`.

| conditioning | required |
|---|---|
| `still` | `image_path` is an existing, readable file |
| `chain` | `index >= 2` and `image_path` is `null` |
| `t2v` | `image_path` is `null` |

`--chain` output: panel 1 is `still`; panels 2..N are `chain`.

The module docstring gets a v3 section describing the key and the `--chain` mode.

### 7.2 `--chain` flag

- `parser.add_argument("--chain", action="store_true", default=False, help="chained flow (bin/ltx-movie): exactly one --image is panel 1's still; every later panel is conditioned at render time on the previous clip's last frame. Requires --prompts-md; mutually exclusive with --glob and --no-images.")`
- Argument validation, added before the existing no-images/glob branch:
  - `--chain` with `--no-images` or `--glob` → `parser.error("--chain is mutually exclusive with --glob and --no-images")`.
  - `--chain` without `--prompts-md` → `parser.error("--chain requires --prompts-md")`.
  - `--chain` with `len(args.image or []) != 1` → `parser.error("--chain requires exactly one --image (panel 1's still)")`.
- In the prompts section, `--chain` skips the `len(parsed_panels) != len(matched)` check and applies these instead, each an error with exit 2:
  - zero parsed panels → `"Error: --chain requires --prompts-md to contain at least one panel section; found 0"`;
  - panel 1 has an empty `Image:` → `"Error: --chain requires panel 1 to have a non-empty Image: field"`;
  - any panel has an empty `Motion:` → `"Error: --chain requires every panel to have a non-empty Motion: field; panel %d has none"`;
  - any panel has a non-empty `Prompt:` → `"Error: --chain does not accept Prompt: fields; panel %d has one"`.
  - The existing Prompt-vs-Image/Motion conflict check stays.
  - A panel ≥ 2 with a non-empty `Image:` prints `WARNING: panel %d has an Image: field; --chain ignores it (the panel continues from the previous clip's last frame)` and continues.
- `n_panels = len(prompt_texts)` when `args.no_images or args.chain`.
- Panel assembly: an `args.chain` branch is checked first.
  - `i == 1`: `image_path = abspath(args.image[0])`, `conditioning = "still"`, `panel_text = pt["image"]`, `motion_prompt = pt["motion"]`.
  - `i >= 2`: `image_path = None`, `conditioning = "chain"`, `panel_text = pt["motion"]`, `motion_prompt = pt["motion"]`.
  - `title` and `narration` come from `pt` as in the labeled branch.
  - The `conditioning` key is added only in chain mode.
- Length warning: in chain mode, `_prompt_length_warning(p["index"], p["motion_prompt"])`, the text actually sent to the video model. Other modes are unchanged.
- `"schema_version": 3 if args.chain else 2`.
- Summary table basename: `os.path.basename(p["image_path"]) if p["image_path"] else ("(chained)" if p.get("conditioning") == "chain" else "(no image)")`.

### 7.3 Phase 3 argv (`phase3_manifest` and its dry-run mirror)

In stills mode, `["--glob", "panel_*.png", "--images-dir", images_dir]` is replaced by `["--chain", "--image", os.path.join(images_dir, "panel_01.png")]`. The `--no-stills` argv is unchanged.

### 7.4 `bin/ltx-mlx-render load_manifest`

- `schema_version = data.get("schema_version", 1)`.
- For `schema_version >= 3`, every panel must carry `conditioning` in `{"still", "chain", "t2v"}` and satisfy the §7.1 table. Errors are `ValueError`s:
  - `"panel %d: conditioning must be one of still/chain/t2v, got %r"`
  - `"panel %d: conditioning 'still' requires an existing, readable image_path"`
  - `"panel %d: conditioning 'chain' requires index >= 2 and image_path null"`
  - `"panel %d: conditioning 't2v' requires image_path null"`
- For `schema_version < 3`, set `panel["conditioning"] = "still" if panel["image_path"] else "t2v"` after the existing image_path normalization. v1/v2 manifests therefore behave exactly as today.
- The existing `panel_text` requirement is unchanged. Chain panels carry their `Motion:` text there.
- Other consumer: `bin/ltx-story-video` (old torch backend) is not reachable from `ltx-movie` and is not changed. It reads v3 chain panels as image-less. Out of scope.

## 8. Chain loop, retry and resume (`bin/ltx-mlx-render`)

### 8.1 Units

`build_units(panels, seed, clips_dir, run_root=None)` adds two keys to every unit:

- `"conditioning": panel["conditioning"]`
- `"chain_source": os.path.join(clips_dir, "panel_%02d.mp4" % (i - 1)) if conditioning == "chain" else None`

For chain units, `"image_path"` is `os.path.join(clips_dir, "panel_%02d.chainseed.png" % i)`, which is derived at render time. For other units it stays `panel.get("image_path")`. Seeds stay `seed + i`. A manifest is a **chain manifest** when `any(u["conditioning"] == "chain" for u in units)`.

### 8.2 Last-frame extraction and validation

These are new module-level functions, stdlib + subprocess only. Test R2a forbids PIL/torch/content_safety/psutil in this file.

- `CHAIN_SEED_MIN_YAVG = 20` and `CHAIN_SEED_MIN_YRANGE = 10`. These are heuristics; limited-range black is Y=16.
- `extract_last_frame(clip_path, out_png, frames) -> list[str]`:
  - `tmp = out_png[:-len(".png")] + ".tmp.png"`.
  - Run `["ffmpeg", "-v", "error", "-nostdin", "-y", "-i", clip_path, "-vf", "select=eq(n\\,%d)" % (frames - 1), "-fps_mode", "passthrough", "-frames:v", "1", tmp]` with `timeout=120`, capturing output.
  - On `OSError`/`TimeoutExpired`, a non-zero return, or a missing/zero-byte `tmp`: return `["clip %s: last-frame extraction failed: <reason>"]`, where `<reason>` is the exception text or the last 5 lines of stderr.
  - Otherwise `os.replace(tmp, out_png)` and return `[]`.
  - Selecting by exact index is deterministic because every ok or reused clip has already been verified at `frames` frames. `-sseof` is deliberately not used; it seeks by time, not to the last frame.
- `check_chain_seed(png_path, width, height) -> list[str]`:
  1. `ffprobe -v error -select_streams v:0 -show_entries stream=width,height -of json PNG` (timeout 60). If it fails → `["chain frame %s: ffprobe failed: ..."]`. If the size is wrong → `["chain frame %s is %dx%d, expected %dx%d"]`.
  2. `ffmpeg -v error -nostdin -i PNG -vf signalstats,metadata=mode=print:file=- -f null -` (timeout 60). Parse `lavfi\.signalstats\.(YAVG|YMIN|YMAX)=([0-9.]+)` from stdout.
     - Values missing → `["chain frame %s: could not measure brightness"]`.
     - `YAVG < CHAIN_SEED_MIN_YAVG` or `YMAX - YMIN < CHAIN_SEED_MIN_YRANGE` → `["chain frame %s is degenerate (YAVG=%.1f, YMIN=%.1f, YMAX=%.1f): black or flat; edit panel %d's Motion: in story.md to change it, then rerun -- the edited panel and every later panel re-render"]`.
  3. Otherwise return `[]`.
- `prepare_chain_seed(unit, args) -> list[str]` returns `extract_last_frame(unit["chain_source"], unit["image_path"], args.frames) or check_chain_seed(unit["image_path"], args.width, args.height)`. The panel number in the degenerate message is `unit["index"] - 1`.

### 8.3 Provenance (schema_version 2)

`build_clip_provenance(unit, args, *, strict=False)`:

- `"schema_version": 2`
- `"backend": "ltx-2-mlx"`, a constant
- new `"conditioning": unit["conditioning"]`
- `"image_sha256": file_sha256(unit["image_path"]) if unit["conditioning"] == "still" else None`
- new `"chain_source_sha256": file_sha256(unit["chain_source"]) if unit["conditioning"] == "chain" else None`
- new `"chain_frame_index": args.frames - 1 if unit["conditioning"] == "chain" else None`
- The `vae_decode_budget_gb` branch is deleted. All other keys are unchanged.

Keying chain units on the **source clip's bytes**, not the PNG's, means an ffmpeg PNG-encoder change cannot trigger a spurious re-render cascade. The version bump deliberately makes every pre-redesign clip non-reusable; those clips were conditioned on the old cropped, independent stills.

### 8.4 Main loop (`main()`)

**Before the `--dry-run` short-circuit:** if it is a chain manifest and `args.on_panel_failure == "skip"`, print `Error: --on-panel-failure skip is not allowed for a chained manifest: a skipped panel leaves the next panel with no frame to continue from` and return 2.

**Per unit, in index order:**

1. **Resume check**, unchanged in form: `args.resume and clip_is_reusable(clip_path, args.frames, build_clip_provenance(unit, args))`. It reuses as today and skips extraction. For a chain unit, the previous clip is guaranteed to be present and ok, because every failure in a chain manifest stops the loop.
2. **Chain units not reused:**
   - `v = prepare_chain_seed(unit, args)`. If non-empty: print each entry as `panel %d FAILED (chain seed): %s`, record `unit_results[i] = {"unit": label, "status": "chain_seed_invalid", "attempts": 0, "seconds": 0.0, "clip": None, "resumed": False, "error": "; ".join(v)}`, set `stopped_reason = "chain_seed_invalid"` and break.
   - Then, unless `args.skip_input_screen`: `rc = run_input_content_screen([unit["image_path"]])`. If `rc != 0`: record the same shape with `status "chain_seed_blocked"`, set `stopped_reason = "chain_seed_blocked"` and break.
3. `result = render_panel(unit, args)`. On ok, continue, exactly as today. On `fatal`, `stopped_reason = "backend_failure"` and break, as today.
4. **Failure in a chain manifest** (this applies to panel 1 too):
   - If `args.retry_failed`: print `=== inline retry: panel %d (chained; later panels depend on it) ===`, `time.sleep(args.retry_idle)`, then `r2 = render_panel(unit, args)` with `r2["attempts"] = 2` and `r2["first_failure"] = result["status"]`. Store `r2`. On ok, continue.
   - Otherwise, or if the retry also failed: `stopped_reason = "chain_broken"`, break.
   - The consecutive-failure counter and the `stop`/`skip` policy branches are not consulted for chain manifests.
5. **Failure in a non-chain manifest:** exactly as today.

Units never reached are marked `not_attempted`, as today.

**`finish_run`:**
- The end-of-run retry pass also requires `not any(u.get("conditioning") == "chain" for u in units)`. The signature is unchanged.
- The concat takes the contiguous completed prefix, which follows automatically from the ordering.
- The relaunch hint prints when `stopped_reason in ("consecutive_failures", "chain_broken")`.
- `SUMMARY_KEYS` and the summary shape are unchanged. `stopped_reason` gains the values `chain_broken`, `chain_seed_invalid` and `chain_seed_blocked`.
- The exit code is 1 on any early stop, as today.

### 8.5 Dry run (`print_dry_run`)

- Per-unit line for chain units: `"  panel %2d: I2V chained <- last frame (index %d) of %s" % (index, args.frames - 1, unit["chain_source"])`. Still and t2v lines are unchanged.
- Resume prediction goes **in order**. A chain unit is predicted reusable only if its predecessor was predicted reusable AND `clip_is_reusable(...)` holds; that call hashes the predecessor clip, which exists in that case. Otherwise it is predicted to render and is not hashed. Still and t2v units are predicted exactly as today.
- The "first render command" uses the first unit predicted to render. For a chain unit its `--image` is the `.chainseed.png` path, which may not exist yet; `build_command` does not check.

### 8.6 Behaviour summary

| Situation | Behaviour |
|---|---|
| Clip k fails once | Inline retry after `--retry-idle` (ltx-movie passes 1 retry, 120 s). Clip k-1 is not re-rendered; only its last frame is re-extracted (~1 s). |
| Clip k fails twice | Stop with `chain_broken`. Clips 1..k-1 are concatenated into movie.mp4, the summary is written, exit 1, and the relaunch hint is printed. |
| Last frame black, flat or unextractable | Stop with `chain_seed_invalid`. The message names clip k-1 and the remedy: edit panel k-1's `Motion:`. |
| Chain frame fails the content screen | Stop with `chain_seed_blocked`. |
| Resume after a crash at panel 7 | Panels 1-6 are reused (provenance matches, no extraction); panel 7 renders. |
| Edit panel 4's `Motion:` | Panel 4's prompt hash changes, so panel 4 re-renders. That changes clip 4's bytes, so panels 5..N re-render (cascade via `chain_source_sha256`). |
| Replace or regenerate `panel_01.png` | Every panel re-renders. |
| Single-panel movie | No chain units. Panel 1 is I2V from the still; a single-clip concat works as today. |
| `--no-stills` | v2 manifest, all `t2v`, independent loop, `skip` policy, end-of-run retry. Unchanged. |
| Stale `panel_01.png` in z_image mode | Unchanged pre-existing behaviour: Phase 2 skips an existing `panel_01.png` without `--force` (seed mode always rewrites it). Delete the file to regenerate. |
| A legitimately very dark frame (YAVG < 20) | Stops as degenerate. The operator edits that panel's `Motion:`. Accepted v1 heuristic. |

### 8.7 `bin/ltx-movie` Phase 4 flags

`_phase4_flags` passes `"--on-panel-failure", "skip" if args.no_stills else "stop"`. All other flags are unchanged (`--retry-failed 1`, `--retry-idle 120`, `--max-consecutive-failures 3`).

## 9. Backend removal inside the kept files

**`bin/ltx-mlx-render`:**
- Delete the `import comfyui_mlx_video_skill as COMFY_MLX_SKILL` line (`:48`).
- Delete the `--video-backend` argument (`:98`).
- Delete the `cctech_ltx25_runtime` import and its `is_source_reference` branch in `model_identity` (`:250-252`).
- Every `args.video_backend == "comfyui-mlx"` conditional collapses to its mlx branch: `:312`, `:321-322`, `:571`, `:591`, `:652-653`, `:656`, `:696-697`, `:788`, `:837-847`, `:859-861`.
- `clips_dir` defaults to `<story_dir>/clips`.
- `estimate_seconds_per_panel` keeps its `backend="ltx-2-mlx"` parameter default; call sites stop passing a conditional.
- `SKILL` is used everywhere `selected_skill` was.

**`bin/ltx-movie`:** as §5.3, plus `_render_flags` (§5.7).

## 10. Deletion scope (final, no preservation)

Tracked files (`git rm`):
- `wan_video_skill.py`
- `bin/wan-generate`
- `wan_ceiling.json`
- `tests/test_wan_video_skill_offline.py`

Untracked files and directories (`rm -r`):

- **Code:**
  - `comfyui_video_skill.py`, `comfyui_video_supervisor.py`, `comfyui_split_video.py`
  - `comfyui_custom_nodes/` (entire directory)
  - `cctech_ltx25_convert.py`, `cctech_ltx25_cpu.py`, `cctech_ltx25_decoder.py`, `cctech_ltx25_mlx.py`, `cctech_ltx25_q8_layers.json`, `cctech_ltx25_requantize.py`, `cctech_ltx25_runtime.py`, `cctech_ltx25_source.py`
- **Scripts:**
  - `scripts/deploy/` (entire directory: `build_package.py`, `install_package.py`, `start-story-server.sh`)
  - `scripts/cctech_conv_decode_ab.py`, `scripts/cctech_repin_outputs.py`, `scripts/cctech_repin_sources.py`
  - `scripts/comfyui_frogjump_ab.py`, `scripts/comfyui_frogjump_cpu_diagnostic.py`
  - `scripts/verify_cctech_conversion.py`, `scripts/verify_cctech_requantization.py`
- **Tests:**
  - `tests/test_cctech_ltx25_convert.py`, `_cpu.py`, `_decoder.py`, `_mlx.py`, `_requantize.py`, `_runtime.py`, `_source.py`
  - `tests/test_comfyui_frogjump_cpu_diagnostic.py`, `test_comfyui_mlx_nodes.py`, `test_comfyui_mlx_video_skill.py`, `test_comfyui_split_nodes.py`, `test_comfyui_split_video.py`, `test_comfyui_video_skill.py`, `test_comfyui_video_supervisor.py`
  - `tests/test_verify_cctech_conversion.py`, `tests/test_deploy_package.py`
  - `tests/fixtures/cctech_component_oracle.py`, `tests/fixtures/split_video_surviving_descendant_supervisor.py`, `tests/fixtures/mlx_surviving_descendants_supervisor.py`, `tests/fixtures/mlx_affine_int8_g64.json`. The last two are used only by deleted tests.
- **Docs:**
  - `docs/comfyui-mlx-backend.md`, `docs/comfyui-mlx-validation.md`, `docs/comfyui-video-skill.md`
  - `docs/superpowers/specs/2026-09-14-comfyui-ltx25-frogjump-ab-render.md`
  - `docs/superpowers/specs/2026-09-15-comfyui-video-skill-design.md`
  - `docs/superpowers/specs/2026-09-17-usb-deployment-package-spec.md`, `.rev1.md`, `.rev2.md`, `.rev3.md`, `.rev3.1.md`, `-spec-review.md`, `-spec-rev2-review.md`, `-spec-rev3-review.md`, `2026-09-17-usb-deployment-package-tooling-review.md`
  - `docs/superpowers/plans/2026-09-15-comfyui-capacity-next-steps.md`, `2026-09-15-comfyui-recovery-stability-proposal.md`, `2026-09-15-comfyui-skill-progress.md`, `2026-09-15-comfyui-split-process-implementation.md`, `2026-09-15-comfyui-video-skill-implementation.md`
  - `docs/superpowers/plans/2026-09-16-cctech-conversion-contract.md`, `2026-09-16-cctech-full-pipeline.md`, `2026-09-16-cctech-q8-requantize-plan-review.md`, `2026-09-16-cctech-q8-requantize-plan.md`, `2026-09-16-cctech-runtime-contract.md`, `2026-09-16-cctech-smaller-quant-investigation.md`
  - `docs/superpowers/plans/2026-09-16-comfyui-mlx-backend-progress.md`, `2026-09-16-comfyui-mlx-backend.md`
  - `docs/superpowers/plans/2026-09-17-cctech-decode-gpu-options.md`, `2026-09-17-cctech-decode-speedup-plan-review.md`, `2026-09-17-cctech-decode-speedup-plan.md`, `2026-09-17-cctech-decode-speedup-plan.rev1.md`, `2026-09-17-deployment-package-inventory.md`

Kept despite mentioning a deleted name (comment-only mentions, not changed): `tests/check_ltx_no_grad.py`, `tests/test_ltx_t2v_offline.py`, `tests/test_story_server.py`. Also kept, as historical records: `docs/superpowers/plans/2026-09-17-story-server-*.md` and `2026-09-17-seed-image-vision-route-options.md`.

**Deletion method.** If the harness permission system blocks `rm` or `git rm`, the implementer STOPS and returns the exact list to the user. It must not overwrite files with stubs or redirect pointers: a stubbed `.py` would stay importable.

## 11. Test impact

All test scripts in scope follow the repo's pattern: a `check()` helper, a `__main__` block that calls every test, then `print("OK %d/%d")` and `sys.exit(0 if FAILED == 0 else 1)`. `test_ltx_movie_offline.py::test_main_block_completeness` enforces that the `__main__` block calls every test, so every new test function must be added there.

**Gate rule:** pytest's pass count is not a gate for these files. Pass/fail is decided by **direct invocation** (`python3 tests/<file>.py`) and its exit code, because `test_ltx_movie_offline.py` reports false greens under pytest.

**Kept-test rule:** every existing test not listed below as deleted or rewritten is kept unmodified. If a kept test fails after the change, the implementer reports it and does not edit it.

**Baseline rule:** before any edit, run every §12.1 gate file directly and record each exit code and `OK n/n` line in the implementation plan document under `docs/superpowers/plans/`, not in `/private/tmp`. Two known baseline failures:
- `tests/test_ltx_mlx_render.py` fails at import today (P1).
- `tests/test_ltx_story_video.py` fails today with an unrelated `TabError` raised during import. It is not a gate for this work and is not edited.

### 11.1 `tests/test_ltx_movie_offline.py`

**Delete:** `test_seed_preface_specifies_style_field`, `test_seed_preface_drops_verbatim_repetition`, `test_validate_story_md_require_style`, `test_require_style_call_site_guard`, `test_seed_preface_bans_restated_appearance`, `test_style_echo_warnings`, `test_style_echo_call_site_guard`, `test_style_content_warnings`, `test_band_prompt_and_content_call_site`, `test_comfyui_mlx_backend_flags`, `test_bridge_movie_preflight_precedes_all_work`, `test_bridge_movie_cli_without_pythonpath`.

**Rewrite:**
- `test_parser_defaults` (L1): `frames == 145`; `video_width is None`; `video_height is None`; no `image_width` attribute.
- `test_removed_flags_rejected` (L23): add `--image-width 1280`, `--image-height 704` and `--video-backend mlx` to the list of flags that must be rejected with rc 2.
- `test_dry_run_prints_phases_and_prompt`, `test_default_dry_run_plan_unchanged`, `test_dry_run_plan_targets_mlx_render` (L24f):
  - With no seed, the render flags are `--frames 145 --width 704 --height 448`.
  - Phase 2 is `--only 1 --width 1408 --height 896`.
  - Phase 3 is `--chain --image …/images/panel_01.png`.
  - No `--video-backend` token.
  - Phase 4 has `--on-panel-failure stop`.
- `test_no_stills_dry_run_plan`: Phase 4 keeps `--on-panel-failure skip`.
- `test_story_prompt_template`:
  - Seed-less rendered prompt, `seconds="6"`, 5 panels: contains `ONE continuous take`, `exact last frame`, `Panel 1 has exactly three fields`, `Every later panel has exactly two fields` and `15-35 words`.
  - It contains no `Style:`, `{` or `}`, and no `image_rules`.
  - All four combinations of (no_stills, seed_image) render without `KeyError`.
- `test_no_stills_story_prompt_template`: asserts `fill the full 6 seconds` when `seconds="6"`; the rest of the template is unchanged.
- `test_seed_prompt_preface` and `test_seed_postface_overrides_last`: the rendered prompt starts with `SEED_IMAGE_PREFACE` and ends with `SEED_IMAGE_POSTFACE`; the preface contains `IS the first frame`; neither contains `Style:` or `FAR BAND`.
- `test_validate_story_md_missing_motion`: updated to the §6.5 rules, with fixtures where panel 1 has three fields and panels 2+ have two. Plus new cases:
  - panel 2 missing `Motion:` → violation;
  - panel 1 missing `Image:` → violation;
  - panel 2 with `Image:` → no violation and one `_chain_image_warnings` entry;
  - any `Prompt:` in stills mode → violation.
- `test_resolve_length_math` / `test_length_*`: recompute expected panels with 145/24 (`--length 60` → 10).
- `test_phase0_seed_image` (L26):
  - L26a/b/c: same inputs and message substrings via `_prepare_seed_image(path, out)`.
  - L26d: a 4000x3000 source gives `geometry == (512, 384, 0)` and `seed_downscaled.png` is 1024x768 PNG.
  - L26e: 800x600 gives 1024x768.
  - L26f: 1024x1024 gives `(512, 512, 0)` and a 1024x1024 copy.
  - L26g: an RGBA input gives an RGB output.
  - New L26h: a 3001x1000 source gives a violation containing `1:3 to 3:1`, and no file is written.
  - New L26i: a JPEG stored 400x300 with EXIF Orientation=6 gives geometry `(384, 512, 0)`.
  - L26j is rewritten: for a 900x600 red source with a centred black square, `seed_downscaled.png` (1024x683) and the output of `bin/ltx-story-images::_write_seed_panel(src, out, 576, 384)` have equal aspect within 1 px of rounding, and the marker's bbox centre is at the image centre ±2 px in both.
  - The `phase0_seed` end-to-end part asserts `args.video_width, args.video_height` are set to the derived values.
- `test_seed_dry_run_plan`: a 1920x1080 seed prints `video geometry 576x320` and `--width 576 --height 320` in the Phase 3/4 commands, and the Phase 2 command has `--only 1 --width 576 --height 320 --seed-image`.
- `test_seed_source_guards` (L29):
  - L29a is kept: no top-level PIL in `bin/ltx-movie`.
  - L29b is replaced: `bin/ltx-movie` loads `ltx_image_fit.py` only inside a function body (a `SourceFileLoader` call whose path literal contains `ltx_image_fit.py` appears inside a `FunctionDef`), and `ltx_image_fit.py` has no top-level PIL import.
  - L29c-g are kept.

**New:**
- `test_seed_with_explicit_video_dims_rejected`: `--seed-image X --video-width 704 --dry-run` gives rc 2 and stderr contains `derived from --seed-image`.
- `test_video_dims_must_be_64_multiples`: `--video-width 736 --dry-run` gives rc 2.
- `test_out_of_range_seed_fails_before_phase1`: with a monkeypatched `phase1_story` that records calls, `main()` on a 3001x1000 seed with `--no-review` returns 2 and `phase1_story` was never called.
- `test_phase4_flags_policy_by_mode`.

### 11.2 `tests/test_ltx_mlx_render.py`

**Delete:** `test_comfyui_backend_preflight_and_fatal_stop`, `test_backend_clip_directories_estimates_and_sidecars`, `test_bridge_dry_actual_dispatch_and_unknown_direct_identity`.

**Rewrite:**
- `test_clip_provenance_contract`, `test_cached_model_metadata_and_io_failures`, `test_provenance_rejects_changes_during_generation`: remove the bridge/cctech halves; assert provenance schema_version 2 with the new keys (§8.3).
- `test_parser_defaults`: no `video_backend`.
- `test_load_manifest`: add v3 cases, one per §7.4 error message, plus v2 derivation (`image_path` → `still`, null → `t2v`).
- `test_build_units`: `conditioning`/`chain_source`/chainseed `image_path` for a still + chain + chain manifest.

**Kept unchanged, and must pass:** `test_render_script_has_no_heavy_imports` (R2a) and `test_jetsam_ladder_text` (R12n). `JETSAM_LADDER` is not edited.

**New:**
- `test_extract_last_frame_argv`: golden argv, with `subprocess.run` stubbed.
- `test_extract_last_frame_real_ffmpeg`:
  - Generate a 9-frame 64x64 h264 clip with ffmpeg `testsrc2`.
  - Extract with `frames=9`.
  - Compare against an independent `ffmpeg -vf select=eq(n\,8),format=rgb24 -f framemd5` of the clip and a `format=rgb24 -f framemd5` of the PNG; the md5s must match.
  - Skip with a printed `SKIP` only if ffmpeg is absent.
- `test_check_chain_seed`: black 64x64 PNG → degenerate; flat grey (Y≈128) → degenerate by range; testsrc2 frame → `[]`; wrong size → size violation. Real ffmpeg; SKIP if absent.
- `test_chain_manifest_rejects_skip_policy`: rc 2.
- `test_chain_loop_inline_retry_then_stop`: stub `render_panel` so that it fails twice on panel 2 → `stopped_reason == "chain_broken"`, panel 3 `not_attempted`, panel 1's clip concatenated, and the end-of-run retry pass not run.
- `test_chain_loop_seed_invalid_stops`.
- `test_chain_resume_cascade`:
  - Record provenance for three clips; change panel 2's prompt.
  - The in-order prediction reuses 1 and renders 2 and 3.
  - Unchanged prompts reuse all three.
  - Changing clip 1's bytes renders 2 and 3.
- `test_v3_still_aspect_preflight`: stub ffprobe reporting 1280x704 against `--width 704 --height 448` → rc 2 and no render spawned; 1408x896 passes.
- `test_dry_run_chain_lines`.

### 11.3 `tests/test_ltx_story_images.py`

- **Delete:** `test_resize_center_crop_geometry` (I9); its coverage moves to `tests/test_ltx_image_fit.py`.
- **Rewrite:** `test_write_seed_panel` (I10): a 900x900 source into 512x512 gives an exact 512x512 RGB PNG with no pad (corner pixel is the source colour); a 900x600 source into 512x512 gives black top and bottom rows and a source-coloured centre.
- **Kept:** all others, including the grounded/Style tests (the standalone tool keeps that mode).

### 11.4 `tests/test_ltx2_mlx_video_skill.py`

- M3a-g are kept.
- **New:** M3h `validate_geometry(736, 448, 145)` raises and the message contains `multiple of 64`; M3i `(704, 480, 145)` raises; M3j `(64, 64, 9)` is accepted.

### 11.5 New `tests/test_ltx_image_fit.py`

- The golden table in §5.2, every row.
- Every derived output is a multiple of 64, each edge is in [320, 960], and area is ≤ 77 cells, over 2001 log-spaced ratios from 1:3 to 3:1.
- Exactly 3:1 and 1:3 are accepted.
- `fit_letterbox` for sources 800x400, 400x800, 1000x1000, 2000x600 and 100x100 into 512x384:
  - output size is exact;
  - pad pixels are (0,0,0);
  - a centred square marker stays square (±2 px) and centred (±2 px);
  - markers placed at all four source edges survive (never cropped).
- `load_oriented_rgb` applies EXIF Orientation=6.
- The module has no top-level PIL import (AST).

### 11.6 New `tests/test_ltx_story_manifest_chain.py`

- A `--chain` 3-panel story.md gives schema_version 3 with conditioning `still`/`chain`/`chain`; panel 1 `panel_text == Image:`, `motion_prompt == Motion:`; panels 2-3 have `panel_text == motion_prompt == Motion:` and `image_path is None`.
- Each §7.2 error.
- The panel-2 `Image:` warning.
- `--glob` mode still writes schema_version 2 with no `conditioning` key.

### 11.7 Deliberate breakages (each must make at least one test fail)

The implementer applies each one alone, runs the owning test file directly, confirms exit 1, and reverts. Each result is recorded in the hand-back.

| Breakage | Must be caught by |
|---|---|
| `min` → `max` in `fit_pad_px` | test_ltx_image_fit |
| remove `ImageOps.exif_transpose` | test_ltx_image_fit, L26i |
| `GRID_PX` 64 → 32 | test_ltx_image_fit |
| `PAD_TOLERANCE_PX` 8 → 16 | test_ltx_image_fit (4:3 row becomes 576x448) |
| `validate_geometry` back to 32 | M3h |
| drop the v3 still-aspect preflight | test_v3_still_aspect_preflight |
| `frames - 1` → `frames - 2` in `extract_last_frame` | test_extract_last_frame_real_ffmpeg |
| remove the `chain_source_sha256` provenance key | test_chain_resume_cascade |
| re-enable the end-of-run retry for chain manifests | test_chain_loop_inline_retry_then_stop |
| reintroduce `{image_rules}` into `STORY_PROMPT_TEMPLATE` | test_story_prompt_template |

## 12. Acceptance criteria and success metrics

### 12.1 Offline gates (all required)

1. Each of these exits 0 when run as `python3 <file>` from `WS`, and prints `OK n/n`: `tests/test_ltx_movie_offline.py`, `tests/test_ltx_mlx_render.py`, `tests/test_ltx_story_images.py`, `tests/test_ltx2_mlx_video_skill.py`, `tests/test_ltx_image_fit.py`, `tests/test_ltx_story_manifest_chain.py`, `tests/check_ltx2_mlx_no_forbidden_imports.py`. `tests/test_ltx_story_video.py` is excluded (see the §11 baseline rule); the v2-unchanged guarantee it pinned (M4c) is covered by `tests/test_ltx_story_manifest_chain.py`. The counts are taken from the main thread's own run, not the implementer's report.
2. `python3 bin/ltx-mlx-render --help` exits 0 (P1 fixed).
3. `python3 bin/ltx-movie "a test narrative" --story-id gate-dry --dry-run --no-review` exits 0 and its rendered prompt contains no `{`/`}` (P2 fixed).
4. Every §11.7 breakage was caught.
5. Running `/usr/bin/grep -rlI -E "comfyui_|cctech_|wan_video_skill|wan-generate|COMFY_MLX|video_backend|video-backend" bin *.py tests scripts --exclude-dir=__pycache__` from `WS` lists only `tests/check_ltx_no_grad.py`, `tests/test_ltx_t2v_offline.py` and `tests/test_story_server.py`. Use `/usr/bin/grep`; the grep wrapper hides some paths.
6. Every path in §10 is gone (`test -e` false for each).

### 12.2 Hardware gate (REQUIRED; the work is not done without it)

Only 704x448 has ever rendered on the MLX path. Offline and stubbed checks have previously passed while a backend bug reproduced 100% on hardware, so this gate is not optional.

**Prerequisites:**
- Before **each** run, the multimodal story server is running. `--story-server-stop-after-story` stops it after every run's Phase 1, so start it again with `bin/story-server vision` and confirm with `bin/story-server status`.
- No other GPU job is running.
- Swap is under 3.0 GB before Phase 4.

**Seed fixtures.** Create them once, as test inputs only (the pipeline itself never crops), from the real still `generated/stories/final_e2e_verify/images/panel_01.png` (1280x704: an elderly bearded man in a flat cap and olive waxed coat at a lighthouse railing, with a stormy sea). Save them under `generated/hw_gate_seeds/`:

| Fixture | PIL crop box of the source | Size | Derived video |
|---|---|---|---|
| `portrait.png` | (622, 0, 1018, 704) | 396x704 | 320x576 |
| `wide3x1.png` | (0, 150, 1280, 577) | 1280x427 | 960x320 |
| `square.png` | (468, 0, 1172, 704) | 704x704 | 512x512 |

The implementer views each fixture before running, to confirm the man is visible in all three.

**Narrative for all four runs:** `An old fisherman in a flat cap and a waxed coat stands at a lighthouse railing as a storm rolls in over the sea. He grips the rail and watches the waves, then turns and walks toward the lighthouse door.`

**Runs.** Use a fresh story-id per run; `<ts>` is the output of `date +%Y%m%d%H%M%S` taken when that run starts. Reusing an id hangs on an overwrite-approval prompt that cannot be answered. Each run reuses nothing. All commands run from `WS`.

1. `bin/ltx-movie "<narrative>" --story-id hwgate-portrait-<ts> --panels 2 --seed-image generated/hw_gate_seeds/portrait.png --no-review --story-server-stop-after-story`
2. Same with `--story-id hwgate-wide-<ts> --seed-image generated/hw_gate_seeds/wide3x1.png`.
3. Same with `--story-id hwgate-square-<ts> --seed-image generated/hw_gate_seeds/square.png`.
4. No seed: `bin/ltx-movie "<narrative>" --story-id hwgate-noseed-<ts> --panels 2 --no-review --story-server-stop-after-story`. This exercises z_image at 1408x896 plus a 704x448 chain.

**Memory sampler.** Started alongside each run, with `PID` = the `ltx-movie` pid and `OUT` = `generated/stories/<story-id>/hw_gate.json`:

```bash
python3 - "$OUT" "$PID" <<'PY'
import glob, json, os, subprocess, sys, time, psutil
out, pid = sys.argv[1], int(sys.argv[2])
story_dir = os.path.dirname(out)
samples = []
while psutil.pid_exists(pid):
    vm, sw = psutil.virtual_memory(), psutil.swap_memory()
    lvl = subprocess.run(["sysctl", "-n", "kern.memorystatus_vm_pressure_level"],
                         capture_output=True, text=True).stdout.strip()
    samples.append({"t": time.time(), "avail_gib": vm.available / 2**30,
                    "swap_used_gib": sw.used / 2**30, "pressure": int(lvl or 0)})
    time.sleep(2)
runs = glob.glob(os.path.join(story_dir, "runs", "*"))
t4 = max(os.stat(r).st_birthtime for r in runs) if runs else samples[0]["t"]
p4 = [s for s in samples if s["t"] >= t4] or samples
json.dump({"phase4_start": t4,
           "phase4_min_avail_gib": min(s["avail_gib"] for s in p4),
           "phase4_peak_used_gib": 48.0 - min(s["avail_gib"] for s in p4),
           "phase4_max_pressure": max(s["pressure"] for s in p4),
           "phase4_swap_delta_gib": max(s["swap_used_gib"] for s in p4) - p4[0]["swap_used_gib"],
           "samples": samples}, open(out, "w"), indent=2)
PY
```

**Pass criteria. Every run must meet all of these:**

1. `ltx-movie` exits 0, and the newest `runs/*/story_summary.json` has `completed_units == requested_units == 2`.
2. `ffprobe` on `movie.mp4` reports width×height equal to the derived geometry (320x576, 960x320, 512x512, 704x448), exactly 290 video frames, h264 video and an aac stream.
3. `images/panel_01.png` is exactly the derived W×H in runs 1-3, and 1408x896 in run 4.
4. Chain exactness: the rgb24 framemd5 of `clips/panel_02.chainseed.png` equals the rgb24 framemd5 of frame 144 of `clips/panel_01.mp4`.
5. `hw_gate.json`: `phase4_max_pressure < 4` (never critical) and `phase4_swap_delta_gib <= 1.0`.
6. Recorded for every run, with no pass threshold: `phase4_peak_used_gib`, and seconds per panel from `story_summary.json` `units[].seconds`.

**Human sign-off (required).** The user watches all four `movie.mp4` files and confirms:
- the subject is not cropped relative to the seed;
- no black bar is visible beyond the computed residual pad (portrait 7 px, wide 1 px, square 0 px, no-seed 0 px);
- panel 2 continues from panel 1 without a scene change.

**Hand-back.** A table of the four runs: derived geometry, pad_px, seconds per panel for both units, peak used GiB, max pressure, swap delta, and pass/fail per criterion.

### 12.3 Success metrics

| Metric | Target |
|---|---|
| Crop layers acting on the seed | 0 (was 3) |
| Panels whose conditioning is not the previous clip's last frame (N ≥ 2) | exactly 1: panel 1 |
| story.md fields per panel after panel 1 | exactly 2 (`Motion:`, `Narration:`) |
| Residual pad | ≤ 8 px for ≥ 58% of aspect ratios; ≤ 29 px worst case |
| Pipeline runnable end to end | yes (P1, P2, P3 fixed) |
| Backends in the tree | 2 (`z_image_skill`, `ltx2_mlx_video_skill`) |

## 13. Out of scope for v1 (explicit follow-ups)

1. **Raising the resolution cap above 77 cells.** At 145 frames, a volume-equivalent cap (a·b ≤ 125, derived from token counts, **not measured**) would give 16:9 at 896x512 and 4:3 at 768x576. This is gated on hardware measurement at those sizes. It is not implemented in v1.
2. Removing the duplicated join frame and smoothing the audio at joins. Both require a re-encoding stitch instead of `-c copy`.
3. Anti-drift re-anchoring to panel 1, via ltx-2-mlx multi-`--image` keyframe conditioning.
4. A `--chain-frame-offset` option, if the literal last frame proves soft.
5. An advisory warning when a panel 2+ `Motion:` exceeds 40 words.
6. Updating `JETSAM_LADDER` rungs for the 145-frame `ltx-movie` default. The ladder text is unchanged in v1 because `bin/ltx-mlx-render`'s own default is still 241.
7. `ltx-2-mlx extend`, `keyframe` and `--segment` modes. `extend` is believed broken on the distilled-only pack and is not used.
8. Any change to `bin/ltx-story-video`, `bin/ltx-chain` or the old torch backend.
