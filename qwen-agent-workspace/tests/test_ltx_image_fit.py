"""Plain-python (no pytest) offline tests for ltx_image_fit.py.

Run: python3 tests/test_ltx_image_fit.py
Prints PASS/FAIL per case, then "OK n/n" and exits 0, or exits 1 on any
failure. Offline only. GOLDEN is spec 2026-09-24 section 5.2, verbatim.
"""

import ast
import math
import os
import sys
import tempfile

WS = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
sys.path.insert(0, WS)

import ltx_image_fit as fit  # noqa: E402

_MODULE_PATH = os.path.join(WS, "ltx_image_fit.py")

TOTAL = 0
FAILED = 0


def check(name, condition, detail=""):
    global TOTAL, FAILED
    TOTAL += 1
    if condition:
        print("PASS %s" % name)
    else:
        FAILED += 1
        print("FAIL %s %s" % (name, detail))


GOLDEN = (
    ((704, 448), (704, 448, 0)),
    ((1280, 704), (704, 384, 6)),
    ((1920, 1080), (576, 320, 7)),
    ((1080, 1920), (320, 576, 7)),
    ((4032, 3024), (512, 384, 0)),
    ((3024, 4032), (384, 512, 0)),
    ((6000, 4000), (576, 384, 0)),
    ((1024, 1024), (512, 512, 0)),
    ((2560, 1080), (768, 320, 9)),
    ((1170, 2532), (320, 704, 11)),
    ((3000, 1000), (960, 320, 0)),
    ((1000, 3000), (320, 960, 0)),
    ((935, 1000), (512, 576, 28)),
    ((4000, 3000), (512, 384, 0)),
    ((800, 600), (512, 384, 0)),
    ((396, 704), (320, 576, 7)),
    ((1280, 427), (960, 320, 1)),
    ((704, 704), (512, 512, 0)),
)

RANGE_MESSAGE_3001 = ("seed image is 3001x1000 (aspect ratio 3.001:1), outside the supported "
                      "range 1:3 to 3:1; supply a seed image whose width/height ratio is "
                      "between 0.333 and 3.0")


def _value_error(fn, *a):
    try:
        fn(*a)
    except ValueError as e:
        return str(e)
    return None


def test_constants():
    for name, want in (("GRID_PX", 64), ("MIN_CELLS", 5), ("MAX_CELLS", 15),
                       ("MAX_AREA_CELLS", 77), ("MIN_AREA_CELLS", 40),
                       ("PAD_TOLERANCE_PX", 8), ("DEFAULT_VIDEO_WIDTH", 704),
                       ("DEFAULT_VIDEO_HEIGHT", 448)):
        got = getattr(fit, name, None)
        check("F0 %s == %d" % (name, want), got == want, "got %r" % (got,))


def test_fit_pad_px():
    check("F1a 1280x704 into 704x384 fills the height and leaves 6 px of width",
          fit.fit_pad_px(1280, 704, 704, 384) == (698, 384, 6),
          "got %r" % (fit.fit_pad_px(1280, 704, 704, 384),))
    check("F1b an exact-aspect source has no pad",
          fit.fit_pad_px(4000, 3000, 512, 384) == (512, 384, 0),
          "got %r" % (fit.fit_pad_px(4000, 3000, 512, 384),))
    check("F1c a tall source fills the height and pads the width",
          fit.fit_pad_px(400, 800, 512, 384) == (192, 384, 320),
          "got %r" % (fit.fit_pad_px(400, 800, 512, 384),))


def test_golden_table():
    for (w, h), want in GOLDEN:
        try:
            got = fit.derive_video_dims(w, h)
        except ValueError as e:
            got = "ValueError: %s" % e
        check("F1 %dx%d -> %r" % (w, h, want), got == want, "got %r" % (got,))


def test_range_errors():
    msg = _value_error(fit.derive_video_dims, 3001, 1000)
    check("F2a 3001x1000 (just wider than 3:1) raises ValueError", msg is not None)
    check("F2b the message is exactly the spec text", msg == RANGE_MESSAGE_3001, "got %r" % msg)
    msg = _value_error(fit.derive_video_dims, 1000, 3001)
    check("F2c 1000x3001 (just taller than 1:3) raises ValueError naming the range",
          msg is not None and "1:3 to 3:1" in msg and "1000x3001" in msg, "got %r" % msg)
    check("F2d exactly 3:1 is accepted", fit.derive_video_dims(3000, 1000) == (960, 320, 0))
    check("F2e exactly 1:3 is accepted", fit.derive_video_dims(1000, 3000) == (320, 960, 0))


def test_ratio_sweep():
    bad = []
    lo, hi = math.log(1 / 3.0), math.log(3.0)
    for i in range(2001):
        r = math.exp(lo + i * (hi - lo) / 2000)
        w, h = int(round(3000 * r)), 3000
        try:
            W, H, pad = fit.derive_video_dims(w, h)
        except ValueError as e:
            bad.append((w, h, "ValueError", str(e)))
            continue
        if (W % 64 or H % 64 or not 320 <= W <= 960 or not 320 <= H <= 960
                or (W // 64) * (H // 64) > 77 or pad < 0):
            bad.append((w, h, W, H, pad))
    check("F3 2001 log-spaced ratios 1:3..3:1: every size is a 64-multiple, each edge in "
          "[320, 960], area <= 77 cells", not bad, "first failures %r" % bad[:5])


def _letterbox_source(w, h):
    """Red field, a blue centred square, and a green marker touching the middle of
    each of the four edges."""
    from PIL import Image, ImageDraw
    img = Image.new("RGB", (w, h), (255, 0, 0))
    draw = ImageDraw.Draw(img)
    sq = max(4, min(w, h) // 5)
    left, top = (w - sq) // 2, (h - sq) // 2
    draw.rectangle([left, top, left + sq - 1, top + sq - 1], fill=(0, 0, 255))
    e = max(4, min(w, h) // 10)
    draw.rectangle([(w - e) // 2, 0, (w - e) // 2 + e - 1, e - 1], fill=(0, 255, 0))
    draw.rectangle([(w - e) // 2, h - e, (w - e) // 2 + e - 1, h - 1], fill=(0, 255, 0))
    draw.rectangle([0, (h - e) // 2, e - 1, (h - e) // 2 + e - 1], fill=(0, 255, 0))
    draw.rectangle([w - e, (h - e) // 2, w - 1, (h - e) // 2 + e - 1], fill=(0, 255, 0))
    return img


def _green(p):
    return p[1] > 128 and p[0] < 128 and p[2] < 128


def test_fit_letterbox():
    W, H = 512, 384
    for w, h in ((800, 400), (400, 800), (1000, 1000), (2000, 600), (100, 100)):
        label = "%dx%d" % (w, h)
        out = fit.fit_letterbox(_letterbox_source(w, h), W, H)
        check("F5a %s output is exactly 512x384 RGB" % label,
              out.size == (W, H) and out.mode == "RGB", "got %r %r" % (out.size, out.mode))
        new_w, new_h, _pad = fit.fit_pad_px(w, h, W, H)
        x0, y0 = (W - new_w) // 2, (H - new_h) // 2
        pad_ok = True
        blue_x, blue_y = [], []
        for idx, p in enumerate(out.getdata()):
            x, y = idx % W, idx // W
            inside = x0 <= x < x0 + new_w and y0 <= y < y0 + new_h
            if not inside and p != (0, 0, 0):
                pad_ok = False
            if p[2] > 128 and p[0] < 128 and p[1] < 128:
                blue_x.append(x)
                blue_y.append(y)
        check("F5b %s every pad pixel is (0,0,0)" % label, pad_ok)
        check("F5c %s the centred square marker survives" % label, bool(blue_x))
        if blue_x:
            bw = max(blue_x) - min(blue_x) + 1
            bh = max(blue_y) - min(blue_y) + 1
            cx = (min(blue_x) + max(blue_x) + 1) / 2.0
            cy = (min(blue_y) + max(blue_y) + 1) / 2.0
            check("F5d %s the marker stays square (+-2 px)" % label, abs(bw - bh) <= 2,
                  "got %dx%d" % (bw, bh))
            check("F5e %s the marker stays centred (+-2 px)" % label,
                  abs(cx - W / 2.0) <= 2 and abs(cy - H / 2.0) <= 2,
                  "got (%.1f, %.1f)" % (cx, cy))
        edges = (out.getpixel((x0 + new_w // 2, y0 + 1)),
                 out.getpixel((x0 + new_w // 2, y0 + new_h - 2)),
                 out.getpixel((x0 + 1, y0 + new_h // 2)),
                 out.getpixel((x0 + new_w - 2, y0 + new_h // 2)))
        check("F5f %s markers at all four source edges survive (never cropped)" % label,
              all(_green(p) for p in edges), "got %r" % (edges,))


def test_load_oriented_rgb():
    from PIL import Image
    with tempfile.TemporaryDirectory() as td:
        path = os.path.join(td, "exif6.jpg")
        img = Image.new("RGB", (400, 300), (200, 10, 10))
        exif = img.getexif()
        exif[0x0112] = 6
        img.save(path, format="JPEG", exif=exif)
        with Image.open(path) as raw:
            stored = raw.size
        out = fit.load_oriented_rgb(path)
        check("F7a the fixture JPEG is stored 400x300", stored == (400, 300), "got %r" % (stored,))
        check("F7b Orientation=6 is applied: 300x400", out.size == (300, 400),
              "got %r" % (out.size,))
        check("F7c the result is RGB", out.mode == "RGB", "got %r" % out.mode)
        check("F7d the oriented size derives the portrait geometry (384, 512, 0)",
              fit.derive_video_dims(*out.size) == (384, 512, 0),
              "got %r" % (fit.derive_video_dims(*out.size),))
        rgba = os.path.join(td, "rgba.png")
        Image.new("RGBA", (64, 64), (1, 2, 3, 128)).save(rgba, format="PNG")
        check("F7e an RGBA PNG loads as RGB", fit.load_oriented_rgb(rgba).mode == "RGB")


def test_no_toplevel_pil():
    with open(_MODULE_PATH) as f:
        tree = ast.parse(f.read(), filename=_MODULE_PATH)
    top = []
    for node in tree.body:
        if isinstance(node, ast.Import):
            top += [a.name for a in node.names if a.name.split(".")[0] == "PIL"]
        elif isinstance(node, ast.ImportFrom) and node.module and node.module.split(".")[0] == "PIL":
            top.append(node.module)
    check("F8a no top-level PIL import", not top, "found %r" % top)
    in_func = any(isinstance(sub, ast.ImportFrom) and sub.module == "PIL"
                  for node in tree.body if isinstance(node, ast.FunctionDef)
                  for sub in ast.walk(node))
    check("F8b PIL is imported inside a function body", in_func)
    doc = ast.get_docstring(tree) or ""
    check("F8c the docstring states the no-crop policy, the 64 px grid source and the "
          "only measured area",
          "No-crop policy" in doc and "snap_output_dimensions" in doc and "704x448" in doc,
          "docstring=%r" % doc[:300])


if __name__ == "__main__":
    test_constants()
    test_fit_pad_px()
    test_golden_table()
    test_range_errors()
    test_ratio_sweep()
    test_fit_letterbox()
    test_load_oriented_rgb()
    test_no_toplevel_pil()

    print("OK %d/%d" % (TOTAL - FAILED, TOTAL))
    sys.exit(0 if FAILED == 0 else 1)
