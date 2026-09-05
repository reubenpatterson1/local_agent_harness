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
    check("I3 width == 1024", args.width == 1024, "got %r" % args.width)
    check("I3 height == 1024", args.height == 1024, "got %r" % args.height)
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


if __name__ == "__main__":
    test_labeled_section_parses_three_fields()
    test_unlabeled_section_keeps_text_and_empty_labels()
    test_parser_defaults()
    test_dry_run_prints_and_never_imports_torch()
    test_output_paths_match_panel_num_re()
    test_ast_guard_no_toplevel_heavy_imports()
    test_ast_guard_content_safety_handler_continues()

    print("OK %d/%d" % (TOTAL - FAILED, TOTAL))
    sys.exit(0 if FAILED == 0 else 1)
