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
# I10: _write_seed_panel fits (never crops) the seed into an exact RGB PNG
# ---------------------------------------------------------------------------

def test_write_seed_panel():
    from PIL import Image
    colour = (200, 30, 40)

    def _near(p, want):
        return all(abs(a - b) <= 2 for a, b in zip(p, want))

    with tempfile.TemporaryDirectory() as tmp:
        square = os.path.join(tmp, "square.png")
        Image.new("RGB", (900, 900), colour).save(square, format="PNG")
        out_sq = os.path.join(tmp, "out_sq.png")
        story_images._write_seed_panel(square, out_sq, 512, 512)
        check("I10a output file exists", os.path.isfile(out_sq))
        with Image.open(out_sq) as img:
            check("I10b format is PNG", img.format == "PNG", "got %r" % img.format)
            check("I10c size is exactly 512x512", img.size == (512, 512), "got %r" % (img.size,))
            check("I10d mode is RGB", img.mode == "RGB", "got %r" % img.mode)
            corner = img.getpixel((0, 0))
            check("I10e a same-aspect source has no pad: the corner is the source colour",
                  _near(corner, colour), "got %r" % (corner,))

        wide = os.path.join(tmp, "wide.png")
        Image.new("RGB", (900, 600), colour).save(wide, format="PNG")
        out_wide = os.path.join(tmp, "out_wide.png")
        story_images._write_seed_panel(wide, out_wide, 512, 512)
        with Image.open(out_wide) as img:
            check("I10f size is exactly 512x512", img.size == (512, 512), "got %r" % (img.size,))
            rows = [img.getpixel((x, 0)) for x in range(0, 512, 16)] + \
                   [img.getpixel((x, 511)) for x in range(0, 512, 16)]
            check("I10g a wider source is letterboxed: the top and bottom rows are black",
                  all(p == (0, 0, 0) for p in rows), "got %r" % rows[:4])
            check("I10h the centre is the source colour", _near(img.getpixel((256, 256)), colour),
                  "got %r" % (img.getpixel((256, 256)),))
            check("I10i the full source width survives: both edge pixels at mid-height are "
                  "source-coloured (nothing cropped)",
                  _near(img.getpixel((0, 256)), colour) and _near(img.getpixel((511, 256)), colour),
                  "got %r %r" % (img.getpixel((0, 256)), img.getpixel((511, 256))))


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


# ---------------------------------------------------------------------------
# I14: the parser reads Style:, back-compatibly
# ---------------------------------------------------------------------------

def test_style_field_parses_back_compatibly():
    with tempfile.TemporaryDirectory() as tmp:
        md_path = _write_three_panel_story_with_style(tmp)
        _narrative, panels = story_manifest._parse_prompts_md(md_path)
        check("I14 panel 1 style == STYLE_TEXT", panels[0]["style"] == STYLE_TEXT,
              "got %r" % panels[0]["style"])
        check("I14 panel 2 style == ''", panels[1]["style"] == "", "got %r" % panels[1]["style"])
        check("I14 panel 3 style == ''", panels[2]["style"] == "", "got %r" % panels[2]["style"])
        check("I14 panel 1 image unaffected", panels[0]["image"] == "a red ball on a table",
              "got %r" % panels[0]["image"])
        check("I14 panel 1 motion unaffected", panels[0]["motion"] == "camera zooms in",
              "got %r" % panels[0]["motion"])
        check("I14 panel 1 narration unaffected",
              panels[0]["narration"] == "the ball sits quietly", "got %r" % panels[0]["narration"])

    with tempfile.TemporaryDirectory() as tmp:
        md_path = os.path.join(tmp, "story.md")
        with open(md_path, "w") as f:
            f.write(
                "# Story\n\n"
                "## Panel 1 - First\n"
                "Image: a red ball on a table\n"
                "Motion: camera zooms in\n"
                "Narration: the ball sits quietly\n"
                "Style: first part\n"
                "second part\n"
            )
        _narrative, panels = story_manifest._parse_prompts_md(md_path)
        check("I14 wrapped Style: value space-joins",
              panels[0]["style"] == "first part second part", "got %r" % panels[0]["style"])

    with tempfile.TemporaryDirectory() as tmp:
        md_path = _write_three_panel_story(tmp)
        _narrative, panels = story_manifest._parse_prompts_md(md_path)
        check("I14 no Style: -> style == ''", panels[0]["style"] == "", "got %r" % panels[0]["style"])
        check("I14 no Style: -> image unaffected", panels[0]["image"] == "a red ball on a table",
              "got %r" % panels[0]["image"])


# ---------------------------------------------------------------------------
# I15: _compose_prompt
# ---------------------------------------------------------------------------

def test_compose_prompt():
    check("I15 image + style, one space",
          story_images._compose_prompt("a red ball", "teal palette") == "a red ball teal palette",
          "got %r" % story_images._compose_prompt("a red ball", "teal palette"))
    check("I15 empty style returns image unchanged",
          story_images._compose_prompt("a red ball", "") == "a red ball",
          "got %r" % story_images._compose_prompt("a red ball", ""))
    check("I15 whitespace-only style returns image unchanged",
          story_images._compose_prompt("a red ball", "   ") == "a red ball",
          "got %r" % story_images._compose_prompt("a red ball", "   "))
    check("I15 empty image returns style unchanged",
          story_images._compose_prompt("", "teal palette") == "teal palette",
          "got %r" % story_images._compose_prompt("", "teal palette"))
    check("I15 both sides stripped",
          story_images._compose_prompt("  a red ball  ", "  teal palette  ") == "a red ball teal palette",
          "got %r" % story_images._compose_prompt("  a red ball  ", "  teal palette  "))
    result = story_images._compose_prompt("a red ball", "teal palette")
    check("I15 style is a suffix, not a prefix",
          result.startswith("a red ball") and result.endswith("teal palette"), "got %r" % result)


# ---------------------------------------------------------------------------
# I16: _style_text
# ---------------------------------------------------------------------------

def test_style_text():
    check("I16 no panels -> ''", story_images._style_text([]) == "")
    check("I16 strips whitespace", story_images._style_text([{"style": "  abc  "}]) == "abc")
    check("I16 missing key tolerated", story_images._style_text([{}]) == "")
    check("I16 only panel 1 is read",
          story_images._style_text([{"style": ""}, {"style": "later"}]) == "")


# ---------------------------------------------------------------------------
# I17: _panel_seed
# ---------------------------------------------------------------------------

def test_panel_seed():
    check("I17 ungrounded seed 0 index 1", story_images._panel_seed(0, 1, False) == 1)
    check("I17 ungrounded seed 0 index 5", story_images._panel_seed(0, 5, False) == 5)
    check("I17 ungrounded seed 7 index 3", story_images._panel_seed(7, 3, False) == 10)
    check("I17 grounded seed 0 index 1", story_images._panel_seed(0, 1, True) == 0)
    check("I17 grounded seed 0 index 5", story_images._panel_seed(0, 5, True) == 0)
    check("I17 grounded seed 7 index 3", story_images._panel_seed(7, 3, True) == 7)


# ---------------------------------------------------------------------------
# I18: grounded --dry-run output
# ---------------------------------------------------------------------------

def test_grounded_dry_run_output():
    with tempfile.TemporaryDirectory() as tmp:
        md_path = _write_three_panel_story_with_style(tmp)
        out_dir = os.path.join(tmp, "imgs")
        script = (
            "import sys\n"
            "sys.path.insert(0, %r)\n"
            "import importlib.machinery\n"
            "m = importlib.machinery.SourceFileLoader('ltx_story_images', %r).load_module()\n"
            "rc = m.main(['--story-md', %r, '--out-dir', %r, '--seed', '4', '--dry-run'])\n"
            "print('TORCH_IMPORTED=%%s' %% ('torch' in sys.modules))\n"
            "print('RC=%%d' %% rc)\n"
        ) % (WS, _IMAGES_PATH, md_path, out_dir)
        proc = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True)
        lines = [ln for ln in proc.stdout.splitlines() if ln.strip()]
        panel_lines = [ln for ln in lines if ln[:1].isdigit()]
        check("I18 rc == 0", "RC=0" in lines, "got %r" % lines)
        check("I18 torch never imported", "TORCH_IMPORTED=False" in lines, "got %r" % lines)
        check("I18 style line present", ("style: " + STYLE_TEXT) in lines, "got %r" % lines)
        check("I18 pinned-seed line present",
              "seed: pinned to 4 for every generated panel (grounded mode)" in lines,
              "got %r" % lines)
        check("I18 three panel lines", len(panel_lines) == 3, "got %r" % panel_lines)
        check("I18 every panel line has rng 4",
              all("| rng 4 |" in ln for ln in panel_lines), "got %r" % panel_lines)
        check("I18 every panel line has +style",
              all("| +style |" in ln for ln in panel_lines), "got %r" % panel_lines)
        check("I18 every panel line's prompt actually carries the style text",
              all("weathered brass fittings" in ln for ln in panel_lines),
              "got %r" % panel_lines)
        check("I18 no ascending rng offsets",
              not any(("rng 5" in ln or "rng 6" in ln or "rng 7" in ln) for ln in panel_lines),
              "got %r" % panel_lines)
        panel2_line = next((ln for ln in panel_lines if ln.startswith("2 |")), "")
        panel3_line = next((ln for ln in panel_lines if ln.startswith("3 |")), "")
        check("I18 panel 2 still shows its own content", "blue cube" in panel2_line,
              "got %r" % panel2_line)
        check("I18 panel 3 still shows its own content", "green pyramid" in panel3_line,
              "got %r" % panel3_line)


# ---------------------------------------------------------------------------
# I19: ungrounded --dry-run output is unchanged
# ---------------------------------------------------------------------------

def test_ungrounded_dry_run_output_unchanged():
    with tempfile.TemporaryDirectory() as tmp:
        md_path = _write_three_panel_story(tmp)
        out_dir = os.path.join(tmp, "imgs")
        script = (
            "import sys\n"
            "sys.path.insert(0, %r)\n"
            "import importlib.machinery\n"
            "m = importlib.machinery.SourceFileLoader('ltx_story_images', %r).load_module()\n"
            "rc = m.main(['--story-md', %r, '--out-dir', %r, '--seed', '4', '--dry-run'])\n"
            "print('RC=%%d' %% rc)\n"
        ) % (WS, _IMAGES_PATH, md_path, out_dir)
        proc = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True)
        lines = [ln for ln in proc.stdout.splitlines() if ln.strip()]
        panel_lines = [ln for ln in lines if ln[:1].isdigit()]
        check("I19 exactly 3 panel lines", len(panel_lines) == 3, "got %r" % panel_lines)
        check("I19 no panel line has +style",
              not any("+style" in ln for ln in panel_lines), "got %r" % panel_lines)
        check("I19 no panel line has 'rng '",
              not any("rng " in ln for ln in panel_lines), "got %r" % panel_lines)
        check("I19 no panel line has 'pinned to'",
              not any("pinned to" in ln for ln in panel_lines), "got %r" % panel_lines)
        check("I19 no line starts with 'style: '",
              not any(ln.startswith("style: ") for ln in lines), "got %r" % lines)
        pattern = re.compile(r"^\d+ \| .+ \| '.*'$")
        check("I19 each panel line matches the plain format",
              all(pattern.match(ln) for ln in panel_lines), "got %r" % panel_lines)


# ---------------------------------------------------------------------------
# I20: source guards for the seed change
# ---------------------------------------------------------------------------

def test_seed_and_style_source_guards():
    with open(_IMAGES_PATH) as f:
        src = f.read()
    check("I20 _panel_seed(args.seed, i, grounded) appears twice",
          src.count("_panel_seed(args.seed, i, grounded)") == 2,
          "got %d" % src.count("_panel_seed(args.seed, i, grounded)"))
    check("I20 manual_seed(seed_used) present", "manual_seed(seed_used)" in src)
    check("I20 old per-panel offset gone from the call site",
          "manual_seed(args.seed + i)" not in src)
    check("I20 _compose_prompt( appears three times",
          src.count("_compose_prompt(") == 3, "got %d" % src.count("_compose_prompt("))
    check("I20 grounded = bool(style) present", "grounded = bool(style)" in src)


if __name__ == "__main__":
    test_labeled_section_parses_three_fields()
    test_unlabeled_section_keeps_text_and_empty_labels()
    test_parser_defaults()
    test_dry_run_prints_and_never_imports_torch()
    test_output_paths_match_panel_num_re()
    test_ast_guard_no_toplevel_heavy_imports()
    test_ast_guard_content_safety_handler_continues()
    test_seed_image_parser_default()
    test_write_seed_panel()
    test_seed_dry_run_marks_panel_one()
    test_missing_seed_image_rejected()
    test_seed_source_guards()
    test_style_field_parses_back_compatibly()
    test_compose_prompt()
    test_style_text()
    test_panel_seed()
    test_grounded_dry_run_output()
    test_ungrounded_dry_run_output_unchanged()
    test_seed_and_style_source_guards()

    print("OK %d/%d" % (TOTAL - FAILED, TOTAL))
    sys.exit(0 if FAILED == 0 else 1)
