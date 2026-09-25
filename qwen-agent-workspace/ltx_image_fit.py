"""ltx_image_fit -- derive the ltx-2-mlx video geometry from a seed image, and fit
images into it without ever cropping them.

No-crop policy. Nothing in the ltx-movie pipeline crops the seed image. The video's
width and height are derived from the seed's own aspect ratio (derive_video_dims),
and the seed is then scaled to FIT inside that size with one uniform factor and
centred on a black canvas (fit_letterbox). The only padding is the residual gap the
64 px grid cannot close; up to PAD_TOLERANCE_PX of it counts as "no bar".

The 64 px grid. ltx-2-mlx's distilled pipeline is two-stage, and it calls
snap_output_dimensions(height, width, two_stage=True)
(ltx-core-mlx/src/ltx_core_mlx/components/patchifiers.py:127-177), which silently
floors both width and height to multiples of 64. Every size this module returns is a
multiple of GRID_PX, so the snap is a no-op, and ltx-2-mlx's two I2V conditioning
resizes (half size and full size) are exact scalings of a W x H still: its
resize_and_center_crop crops nothing.

The area cap. 704x448 (77 cells of 64x64) is the ONLY resolution ever measured on the
MLX path (acceptance run A1: 704x448 x 241 frames, 160 s per panel, 13.5 GiB), so
derived sizes never exceed that area. Raising the cap is a follow-up gated on a
hardware measurement.

Stdlib-only at import time: PIL is imported inside the functions that need it, so
bin/ltx-movie --dry-run and the offline tests can load this module without Pillow.
"""

GRID_PX = 64            # ltx-2-mlx two-stage snap modulus (patchifiers.py snap_output_dimensions)
MIN_CELLS = 5           # 320 px minimum edge; stage-1 half-size edge 160 px = 5 latent cells
MAX_CELLS = 15          # 960 px maximum edge; with MIN_CELLS this bounds aspect to [1:3, 3:1]
MAX_AREA_CELLS = 77     # 704*448 / 64**2 -- the only MLX-measured area (acceptance run A1)
MIN_AREA_CELLS = 40     # 163,840 px = 0.52x of 704x448; resolution floor
PAD_TOLERANCE_PX = 8    # total residual pad (width deficit + height deficit) treated as "no bar"
DEFAULT_VIDEO_WIDTH = 704
DEFAULT_VIDEO_HEIGHT = 448


def load_oriented_rgb(path):
    """Open path, apply its EXIF orientation, and return it as an RGB image.

    Every exception (missing file, not an image, Pillow not importable) propagates
    to the caller, which owns the error message."""
    from PIL import Image, ImageOps
    with Image.open(path) as img:
        img.load()
        out = ImageOps.exif_transpose(img).convert("RGB")
    return out


def fit_pad_px(src_w, src_h, width, height):
    """(new_w, new_h, pad_px) for scaling src_w x src_h to FIT inside width x height
    with one uniform factor. pad_px is the total residual gap: the width deficit plus
    the height deficit. Pure."""
    s = min(width / src_w, height / src_h)
    new_w = min(width, max(1, round(src_w * s)))
    new_h = min(height, max(1, round(src_h * s)))
    return new_w, new_h, (width - new_w) + (height - new_h)


def derive_video_dims(src_w, src_h):
    """(W, H, pad_px): the video geometry for a src_w x src_h seed. Pure and
    deterministic.

    Candidates are every (a, b) cell pair with MIN_CELLS <= a, b <= MAX_CELLS and
    MIN_AREA_CELLS <= a*b <= MAX_AREA_CELLS, at W = a*GRID_PX, H = b*GRID_PX. If any
    candidate leaves at most PAD_TOLERANCE_PX of residual pad, the largest area wins
    (ties: smaller pad, then larger a). Otherwise the smallest pad wins (ties: larger
    area, then larger a). Raises ValueError for a seed outside 1:3 .. 3:1; exactly
    3:1 and exactly 1:3 are accepted (integer comparison, no float rounding)."""
    if src_w * MIN_CELLS > src_h * MAX_CELLS or src_w * MAX_CELLS < src_h * MIN_CELLS:
        raise ValueError(
            "seed image is %dx%d (aspect ratio %.3f:1), outside the supported range 1:3 to "
            "3:1; supply a seed image whose width/height ratio is between 0.333 and 3.0"
            % (src_w, src_h, src_w / src_h))
    candidates = []
    for a in range(MIN_CELLS, MAX_CELLS + 1):
        for b in range(MIN_CELLS, MAX_CELLS + 1):
            if MIN_AREA_CELLS <= a * b <= MAX_AREA_CELLS:
                width, height = a * GRID_PX, b * GRID_PX
                pad = fit_pad_px(src_w, src_h, width, height)[2]
                candidates.append((a, b, width, height, pad))
    within = [c for c in candidates if c[4] <= PAD_TOLERANCE_PX]
    if within:
        best = min(within, key=lambda c: (-(c[0] * c[1]), c[4], -c[0]))
    else:
        best = min(candidates, key=lambda c: (c[4], -(c[0] * c[1]), -c[0]))
    return best[2], best[3], best[4]


def fit_letterbox(img, width, height):
    """img scaled to fit width x height (LANCZOS, one uniform factor) and pasted,
    centred, onto a black RGB width x height canvas. Never crops: the only non-image
    pixels are the residual gap fit_pad_px reports."""
    from PIL import Image
    new_w, new_h, _pad = fit_pad_px(img.width, img.height, width, height)
    resized = img.resize((new_w, new_h), Image.Resampling.LANCZOS)
    canvas = Image.new("RGB", (width, height), (0, 0, 0))
    canvas.paste(resized, ((width - new_w) // 2, (height - new_h) // 2))
    return canvas
