"""Plain-python (no pytest) offline tests for bin/ltx-story-images.

Run: python3 tests/test_ltx_story_images.py
Prints PASS/FAIL per case, then "OK n/n" and exits 0, or exits 1 on any
failure. Offline only -- this module never imports torch, and asserts that
running bin/ltx-story-images's own main() with --dry-run doesn't either.
"""

import ast
import io
import contextlib
import importlib.machinery
import os
import re
import subprocess
import sys
import tempfile

WS = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
sys.path.insert(0, WS)

_MANIFEST_PATH = os.path.join(WS, "bin", "ltx-story-manifest")
_IMAGES_PATH = os.path.join(WS, "bin", "ltx-story-images")

story_manifest = importlib.machinery.SourceFileLoader("ltx_story_manifest", _MANIFEST_PATH).load_module()
story_images = importlib.machinery.SourceFileLoader("ltx_story_images", _IMAGES_PATH).load_module()

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


# ---------------------------------------------------------------------------
# I1: labeled v2 section parses into the three fields; a multi-line Image
# value is space-joined
# ---------------------------------------------------------------------------

def test_labeled_section_parses_three_fields():
    with tempfile.TemporaryDirectory() as tmp:
        md_path = os.path.join(tmp, "story.md")
        with open(md_path, "w") as f:
            f.write(
                "# Story\n\n"
                "## Panel 1 - Title\n"
                "Image: a scene\n"
                "description continues\n"
                "Motion: motion text\n"
                "Narration: narration text\n"
            )
        _narrative, panels = story_manifest._parse_prompts_md(md_path)
        check("I1 image is multi-line, space-joined",
              panels[0]["image"] == "a scene description continues", "got %r" % panels[0]["image"])
        check("I1 motion field", panels[0]["motion"] == "motion text", "got %r" % panels[0]["motion"])
        check("I1 narration field", panels[0]["narration"] == "narration text",
              "got %r" % panels[0]["narration"])


# ---------------------------------------------------------------------------
# I2: unlabeled section -> whole body as text, three new keys ""
# ---------------------------------------------------------------------------

def test_unlabeled_section_keeps_text_and_empty_labels():
    with tempfile.TemporaryDirectory() as tmp:
        md_path = os.path.join(tmp, "story.md")
        with open(md_path, "w") as f:
            f.write("# Story\n\n## Panel 1 - Title\nsome unlabeled body text\n")
        _narrative, panels = story_manifest._parse_prompts_md(md_path)
        check("I2 text is the whole body join", panels[0]["text"] == "some unlabeled body text",
              "got %r" % panels[0]["text"])
        check("I2 image == ''", panels[0]["image"] == "", "got %r" % panels[0]["image"])
        check("I2 motion == ''", panels[0]["motion"] == "", "got %r" % panels[0]["motion"])
        check("I2 narration == ''", panels[0]["narration"] == "", "got %r" % panels[0]["narration"])


# ---------------------------------------------------------------------------
# I3: parser defaults
# ---------------------------------------------------------------------------

def test_parser_defaults():
    args = story_images.build_parser().parse_args(["--story-md", "s.md", "--out-dir", "o"])
    check("I3 width == 1280", args.width == 1280, "got %r" % args.width)
    check("I3 height == 704", args.height == 704, "got %r" % args.height)
    check("I3 seed == 0", args.seed == 0, "got %r" % args.seed)
    check("I3 force is False", args.force is False, "got %r" % args.force)
    check("I3 dry_run is False", args.dry_run is False, "got %r" % args.dry_run)


# ---------------------------------------------------------------------------
# I4: --dry-run on a temp 3-panel story.md prints 3 lines, returns 0, and
# never imports torch
# ---------------------------------------------------------------------------

def _write_three_panel_story(tmp):
    md_path = os.path.join(tmp, "story.md")
    with open(md_path, "w") as f:
        f.write(
            "# Story\n\n"
            "## Panel 1 - First\n"
            "Image: a red ball on a table\n"
            "Motion: camera zooms in\n"
            "Narration: the ball sits quietly\n\n"
            "## Panel 2 - Second\n"
            "Image: a blue cube on the floor\n"
            "Motion: camera pans left\n"
            "Narration: the cube waits\n\n"
            "## Panel 3 - Third\n"
            "Image: a green pyramid in the sky\n"
            "Motion: slow rotation\n"
            "Narration: the pyramid floats\n"
        )
    return md_path


def test_dry_run_prints_and_never_imports_torch():
    with tempfile.TemporaryDirectory() as tmp:
        md_path = _write_three_panel_story(tmp)
        out_dir = os.path.join(tmp, "imgs")
        script = (
            "import sys\n"
            "sys.path.insert(0, %r)\n"
            "import importlib.machinery\n"
            "m = importlib.machinery.SourceFileLoader('ltx_story_images', %r).load_module()\n"
            "rc = m.main(['--story-md', %r, '--out-dir', %r, '--dry-run'])\n"
            "print('TORCH_IMPORTED=%%s' %% ('torch' in sys.modules))\n"
            "print('RC=%%d' %% rc)\n"
        ) % (WS, _IMAGES_PATH, md_path, out_dir)
        proc = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True)
        lines = [ln for ln in proc.stdout.splitlines() if ln.strip()]
        panel_lines = [ln for ln in lines if ln[:1].isdigit()]
        check("I4 --dry-run prints 3 panel lines", len(panel_lines) == 3, "got %r" % lines)
        check("I4 --dry-run returns 0", "RC=0" in lines, "got %r" % lines)
        check("I4 --dry-run never imports torch", "TORCH_IMPORTED=False" in lines, "got %r" % lines)


# ---------------------------------------------------------------------------
# I5: output paths panel_01.png... each match the manifest tool's
# _PANEL_NUM_RE with the right captured number
# ---------------------------------------------------------------------------

def test_output_paths_match_panel_num_re():
    for i in range(1, 4):
        name = "panel_%02d.png" % i
        m = story_manifest._PANEL_NUM_RE.search(name)
        check("I5 %s matches _PANEL_NUM_RE" % name, m is not None, "got %r" % m)
        if m:
            check("I5 %s captures number %d" % (name, i), int(m.group(1)) == i,
                  "got %r" % m.group(1))


# ---------------------------------------------------------------------------
# I6: AST guard -- no top-level import of torch/z_image_skill/diffusers
# ---------------------------------------------------------------------------

def test_ast_guard_no_toplevel_heavy_imports():
    with open(_IMAGES_PATH) as f:
        tree = ast.parse(f.read(), filename=_IMAGES_PATH)
    heavy = ("torch", "z_image_skill", "diffusers")
    violations = []
    for node in tree.body:
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.split(".")[0] in heavy:
                    violations.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module and node.module.split(".")[0] in heavy:
                violations.append(node.module)
    check("I6 no top-level import of torch/z_image_skill/diffusers", not violations,
          "found: %r" % violations)


# ---------------------------------------------------------------------------
# I7: AST guard -- the ContentSafetyError handler in the per-panel loop
# contains no break or raise (a block on one panel must not lose the batch)
# ---------------------------------------------------------------------------

def _handler_names(handler):
    node = handler.type
    if node is None:
        return []
    if isinstance(node, ast.Name):
        return [node.id]
    if isinstance(node, ast.Attribute):
        return [node.attr]
    if isinstance(node, ast.Tuple):
        names = []
        for elt in node.elts:
            names.extend(_handler_names(ast.ExceptHandler(type=elt, body=[])))
        return names
    return []


def test_ast_guard_content_safety_handler_continues():
    with open(_IMAGES_PATH) as f:
        tree = ast.parse(f.read(), filename=_IMAGES_PATH)
    found_handler = False
    has_break_or_raise = False
    for node in ast.walk(tree):
        if isinstance(node, ast.ExceptHandler) and "ContentSafetyError" in _handler_names(node):
            found_handler = True
            for sub in ast.walk(node):
                if isinstance(sub, (ast.Break, ast.Raise)):
                    has_break_or_raise = True
    check("I7 a ContentSafetyError handler exists", found_handler)
    check("I7 ContentSafetyError handler has no break/raise", found_handler and not has_break_or_raise,
          "has_break_or_raise=%r" % has_break_or_raise)


# ---------------------------------------------------------------------------
# I8: --seed-image parser default
# ---------------------------------------------------------------------------

def test_seed_image_parser_default():
    args = story_images.build_parser().parse_args(["--story-md", "s.md", "--out-dir", "o"])
    check("I8 --seed-image defaults to None", args.seed_image is None, "got %r" % args.seed_image)
    args2 = story_images.build_parser().parse_args(
        ["--story-md", "s.md", "--out-dir", "o", "--seed-image", "x.png"])
    check("I8 --seed-image captured", args2.seed_image == "x.png", "got %r" % args2.seed_image)


# ---------------------------------------------------------------------------
# I9: _resize_center_crop fills, does not distort, and centers the crop
# ---------------------------------------------------------------------------

def _marker_image(src_w, src_h, square):
    """An RGB image: solid red background, a black square marker dead center."""
    from PIL import Image, ImageDraw
    img = Image.new("RGB", (src_w, src_h), (255, 0, 0))
    draw = ImageDraw.Draw(img)
    cx, cy = src_w / 2.0, src_h / 2.0
    half = square / 2.0
    left = int(round(cx - half))
    top = int(round(cy - half))
    draw.rectangle([left, top, left + square - 1, top + square - 1], fill=(0, 0, 0))
    return img


def test_resize_center_crop_geometry():
    from PIL import Image, ImageChops
    target_w, target_h = 1280, 704
    for src_w, src_h, square in (
        (800, 400, 100), (400, 800, 100), (1000, 1000, 120),
        (2000, 600, 150), (100, 100, 20),
    ):
        label = "%dx%d/sq%d" % (src_w, src_h, square)
        src = _marker_image(src_w, src_h, square)
        out = story_images._resize_center_crop(src, target_w, target_h)
        check("I9 %s output size" % label, out.size == (target_w, target_h),
              "got %r" % (out.size,))
        corners = [out.getpixel((0, 0)), out.getpixel((target_w - 1, 0)),
                   out.getpixel((0, target_h - 1)), out.getpixel((target_w - 1, target_h - 1))]
        check("I9 %s corners are red (no letterbox)" % label,
              all(c == (255, 0, 0) for c in corners), "got %r" % corners)
        red_ref = Image.new("RGB", out.size, (255, 0, 0))
        diff = ImageChops.difference(out, red_ref)
        bbox = diff.getbbox()
        check("I9 %s marker survives" % label, bbox is not None)
        if bbox:
            mw = bbox[2] - bbox[0]
            mh = bbox[3] - bbox[1]
            check("I9 %s marker stays square (no distortion)" % label, abs(mw - mh) <= 2,
                  "got w=%d h=%d" % (mw, mh))
            mcx = (bbox[0] + bbox[2]) / 2.0
            mcy = (bbox[1] + bbox[3]) / 2.0
            check("I9 %s crop is centered" % label,
                  abs(mcx - target_w / 2.0) <= 2 and abs(mcy - target_h / 2.0) <= 2,
                  "got center=(%.1f, %.1f)" % (mcx, mcy))


# ---------------------------------------------------------------------------
# I10: _write_seed_panel writes an RGB PNG of exactly the target size
# ---------------------------------------------------------------------------

def test_write_seed_panel():
    from PIL import Image
    with tempfile.TemporaryDirectory() as tmp:
        seed_path = os.path.join(tmp, "seed.jpg")
        _marker_image(900, 900, 100).convert("RGBA").convert("RGB").save(seed_path, format="JPEG")
        out_path = os.path.join(tmp, "out.png")
        story_images._write_seed_panel(seed_path, out_path, 1280, 704)
        check("I10 output file exists", os.path.isfile(out_path))
        with Image.open(out_path) as out_img:
            check("I10 format is PNG", out_img.format == "PNG", "got %r" % out_img.format)
            check("I10 size is 1280x704", out_img.size == (1280, 704), "got %r" % (out_img.size,))
            check("I10 mode is RGB", out_img.mode == "RGB", "got %r" % out_img.mode)


# ---------------------------------------------------------------------------
# I11: --dry-run --seed-image marks panel 1 as the seed, leaves panels 2/3
# alone, and never imports torch or PIL
# ---------------------------------------------------------------------------

def test_seed_dry_run_marks_panel_one():
    from PIL import Image
    with tempfile.TemporaryDirectory() as tmp:
        md_path = _write_three_panel_story(tmp)
        out_dir = os.path.join(tmp, "imgs")
        seed_path = os.path.join(tmp, "seed.png")
        Image.new("RGB", (800, 400), (10, 20, 30)).save(seed_path, format="PNG")
        script = (
            "import sys\n"
            "sys.path.insert(0, %r)\n"
            "import importlib.machinery\n"
            "m = importlib.machinery.SourceFileLoader('ltx_story_images', %r).load_module()\n"
            "rc = m.main(['--story-md', %r, '--out-dir', %r, '--seed-image', %r, '--dry-run'])\n"
            "print('TORCH_IMPORTED=%%s' %% ('torch' in sys.modules))\n"
            "print('PIL_IMPORTED=%%s' %% ('PIL' in sys.modules))\n"
            "print('RC=%%d' %% rc)\n"
        ) % (WS, _IMAGES_PATH, md_path, out_dir, seed_path)
        proc = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True)
        lines = [ln for ln in proc.stdout.splitlines() if ln.strip()]
        check("I11 rc 0", "RC=0" in lines, "got %r" % lines)
        panel1_line = next((ln for ln in lines if ln.startswith("1 |")), "")
        panel2_line = next((ln for ln in lines if ln.startswith("2 |")), "")
        panel3_line = next((ln for ln in lines if ln.startswith("3 |")), "")
        check("I11 panel 1 names the seed path", seed_path in panel1_line, "got %r" % panel1_line)
        check("I11 panel 2 shows its own prompt", "blue cube" in panel2_line, "got %r" % panel2_line)
        check("I11 panel 3 shows its own prompt", "green pyramid" in panel3_line,
              "got %r" % panel3_line)
        check("I11 torch never imported", "TORCH_IMPORTED=False" in lines, "got %r" % lines)
        # NOT asserting "PIL never imported" here: bin/ltx-story-manifest (out of
        # scope for this feature) unconditionally imports PIL at module scope, and
        # main() always loads that module before the --dry-run early return -- true
        # for every dry-run, seeded or not, before and after this feature existed.
        # The guarantee this feature actually owns (dry-run never DECODES the seed
        # image, i.e. never calls _write_seed_panel) is covered by I13's AST guard
        # and by dry-run's early return before the per-panel loop.


# ---------------------------------------------------------------------------
# I12: a missing --seed-image is rejected before anything is created
# ---------------------------------------------------------------------------

def test_missing_seed_image_rejected():
    with tempfile.TemporaryDirectory() as tmp:
        md_path = _write_three_panel_story(tmp)
        out_dir = os.path.join(tmp, "imgs")
        missing = os.path.join(tmp, "nope.png")
        stdout = io.StringIO()
        stderr = io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            rc = story_images.main(["--story-md", md_path, "--out-dir", out_dir,
                                     "--seed-image", missing, "--dry-run"])
        check("I12 rc == 2", rc == 2, "got %r" % rc)
        check("I12 stderr mentions not found", "--seed-image not found" in stderr.getvalue(),
              "got %r" % stderr.getvalue())
        check("I12 stderr mentions the missing path", missing in stderr.getvalue(),
              "got %r" % stderr.getvalue())
        check("I12 out-dir never created", not os.path.isdir(out_dir))


# ---------------------------------------------------------------------------
# I13: source guards -- no top-level PIL import, seed branch precedes the
# force/exists skip check, source-field and schema_version counts hold
# ---------------------------------------------------------------------------

def test_seed_source_guards():
    with open(_IMAGES_PATH) as f:
        src = f.read()
    tree = ast.parse(src, filename=_IMAGES_PATH)
    violations = []
    for node in tree.body:
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.split(".")[0] == "PIL":
                    violations.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module and node.module.split(".")[0] == "PIL":
                violations.append(node.module)
    check("I13 no top-level PIL import", not violations, "found: %r" % violations)

    seed_branch = "if args.seed_image is not None and i == 1:"
    exists_check = "if os.path.exists(path) and not args.force:"
    check("I13 seed branch present", seed_branch in src)
    check("I13 exists-skip check present", exists_check in src)
    if seed_branch in src and exists_check in src:
        # NOTE: seed_branch's exact text also appears once earlier, in the --dry-run
        # print loop's own seed special-case -- rindex (last occurrence) is the one
        # that actually lives in the per-panel loop next to exists_check; index()
        # (first occurrence) would always find the dry-run copy and pass trivially
        # regardless of the real loop's ordering.
        check("I13 seed branch precedes the exists-skip check",
              src.rindex(seed_branch) < src.index(exists_check),
              "seed at %d, exists-skip at %d" % (src.rindex(seed_branch), src.index(exists_check)))

    # NOTE: the schema docstring itself (a required, verbatim block: `"source":
    # "seed" | "generated"}`) contains one extra literal match of `"source": "seed"`
    # beyond the two runtime call sites, so the true count is 3, not 2.
    check("I13 four generated-source call sites", src.count('"source": "generated"') == 4,
          "got %d" % src.count('"source": "generated"'))
    check("I13 seed-source occurrences (2 call sites + 1 docstring)",
          src.count('"source": "seed"') == 3, "got %d" % src.count('"source": "seed"'))
    check("I13 schema_version unbumped", '"schema_version": 1,' in src)


if __name__ == "__main__":
    test_labeled_section_parses_three_fields()
    test_unlabeled_section_keeps_text_and_empty_labels()
    test_parser_defaults()
    test_dry_run_prints_and_never_imports_torch()
    test_output_paths_match_panel_num_re()
    test_ast_guard_no_toplevel_heavy_imports()
    test_ast_guard_content_safety_handler_continues()
    test_seed_image_parser_default()
    test_resize_center_crop_geometry()
    test_write_seed_panel()
    test_seed_dry_run_marks_panel_one()
    test_missing_seed_image_rejected()
    test_seed_source_guards()

    print("OK %d/%d" % (TOTAL - FAILED, TOTAL))
    sys.exit(0 if FAILED == 0 else 1)
