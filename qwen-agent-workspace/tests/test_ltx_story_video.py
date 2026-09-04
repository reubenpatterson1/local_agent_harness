"""Plain-python (no pytest) offline tests for bin/ltx-story-manifest and
bin/ltx-story-video.

Run: python3 tests/test_ltx_story_video.py
Prints PASS/FAIL per case, then "OK n/n" and exits 0, or exits 1 on any
failure. No GPU/torch/diffusers work is performed. bin/ltx-story-video's
main() is never invoked in these tests -- it spawns real ltx-host-prep and
stage subprocesses -- only its pure helper functions (build_parser,
load_manifest, build_units, build_frame_sequence) are exercised directly,
plus AST guards on its source text. bin/ltx-story-manifest's main() IS
called directly (it never touches the GPU/servers), but every test uses a
unique story-id under a cleaned-up generated/stories/<id>/ directory and
never writes fixtures (images, prompts.md) into the real generated/ tree.
"""

import ast
import contextlib
import importlib.machinery
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import types

from PIL import Image

WS = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
sys.path.insert(0, WS)

_MANIFEST_PATH = os.path.join(WS, "bin", "ltx-story-manifest")
_VIDEO_PATH = os.path.join(WS, "bin", "ltx-story-video")

story_manifest = importlib.machinery.SourceFileLoader("ltx_story_manifest", _MANIFEST_PATH).load_module()
story_video = importlib.machinery.SourceFileLoader("ltx_story_video", _VIDEO_PATH).load_module()

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


def _make_png(path, color=(120, 40, 200)):
    Image.new("RGB", (8, 8), color=color).save(path)


def _rm_story(story_id):
    shutil.rmtree(os.path.join(story_manifest.WS, "generated", "stories", story_id),
                  ignore_errors=True)


# ---------------------------------------------------------------------------
# T1: panel header variants (em dash, en dash, hyphen) parse index + title
# ---------------------------------------------------------------------------

def test_panel_header_variants():
    for dash, label in (("—", "em dash"), ("–", "en dash"), ("-", "hyphen")):
        with tempfile.TemporaryDirectory() as tmp:
            md_path = os.path.join(tmp, "prompts.md")
            with open(md_path, "w") as f:
                f.write("# Story\n\n## Panel 3 %s Some Title\nbody text\n" % dash)
            _narrative, panels = story_manifest._parse_prompts_md(md_path)
            check(
                "T1 %s: number == 3" % label,
                len(panels) == 1 and panels[0]["number"] == 3,
                "got %r" % panels,
            )
            check(
                "T1 %s: title == 'Some Title'" % label,
                len(panels) == 1 and panels[0]["title"] == "Some Title",
                "got %r" % panels,
            )


# ---------------------------------------------------------------------------
# T2: multi-line panel body joins with single spaces and is stripped
# ---------------------------------------------------------------------------

def test_multiline_body_joined():
    with tempfile.TemporaryDirectory() as tmp:
        md_path = os.path.join(tmp, "prompts.md")
        with open(md_path, "w") as f:
            f.write("# Story\n\n## Panel 1 - Title\n  line one  \n\nline two\nline three  \n\n## Panel 2 - Two\nx\n")
        _narrative, panels = story_manifest._parse_prompts_md(md_path)
        check(
            "T2 multi-line body joined with single spaces and stripped",
            panels[0]["text"] == "line one line two line three",
            "got %r" % panels[0]["text"],
        )


# ---------------------------------------------------------------------------
# M1: _parse_prompts_md accepts a Prompt: label, space-joins its wrapped
# continuation lines, and leaves image/motion empty (DR2)
# ---------------------------------------------------------------------------

def test_parse_prompts_md_prompt_label():
    with tempfile.TemporaryDirectory() as tmp:
        md = os.path.join(tmp, "story.md")
        with open(md, "w") as f:
            f.write(
                "# Story\n\nA short narrative line.\n\n"
                "## Panel 1 — Opening\n"
                "Prompt: a wide establishing shot of a stone courtyard,\n"
                "cold dawn light, slow drone push-in\n"
                "Narration: The courtyard woke slowly.\n"
            )
        _narrative, panels = story_manifest._parse_prompts_md(md)
        p = panels[0]
        check("M1a prompt joins wrapped lines with single spaces",
              p["prompt"] == "a wide establishing shot of a stone courtyard, "
                             "cold dawn light, slow drone push-in",
              "got %r" % p["prompt"])
        check("M1b image is empty", p["image"] == "", "got %r" % p["image"])
        check("M1c motion is empty", p["motion"] == "", "got %r" % p["motion"])
        check("M1d narration parsed", p["narration"] == "The courtyard woke slowly.",
              "got %r" % p["narration"])


# ---------------------------------------------------------------------------
# M2: back-compat -- an Image:/Motion: panel yields prompt == "" and
# unchanged image/motion/narration/text
# ---------------------------------------------------------------------------

def test_parse_prompts_md_prompt_backcompat():
    with tempfile.TemporaryDirectory() as tmp:
        md = os.path.join(tmp, "story.md")
        with open(md, "w") as f:
            f.write(
                "# Story\n\nA short narrative line.\n\n"
                "## Panel 1 — Opening\n"
                "Image: a stone courtyard at dawn\n"
                "Motion: slow drone push-in\n"
                "Narration: The courtyard woke slowly.\n"
            )
        _narrative, panels = story_manifest._parse_prompts_md(md)
        p = panels[0]
        check("M2a prompt is empty on an Image:/Motion: panel", p["prompt"] == "",
              "got %r" % p["prompt"])
        check("M2b image unchanged", p["image"] == "a stone courtyard at dawn",
              "got %r" % p["image"])
        check("M2c motion unchanged", p["motion"] == "slow drone push-in",
              "got %r" % p["motion"])
        check("M2d v1 whole-body text join preserved",
              p["text"] == "Image: a stone courtyard at dawn Motion: slow drone push-in "
                           "Narration: The courtyard woke slowly.",
              "got %r" % p["text"])


# ---------------------------------------------------------------------------
# T3: narrative extraction picks the first non-blank prose line after
# the leading "# " heading
# ---------------------------------------------------------------------------

def test_narrative_extraction():
    lines = [
        "# My Story Title",
        "",
        "# not this (starts with #)",
        "- not this either (starts with -)",
        "",
        "This is the real narrative line.",
        "",
        "## Panel 1 - Title",
    ]
    narrative = story_manifest._extract_narrative(lines)
    check(
        "T3 narrative extraction skips blank/#/- lines",
        narrative == "This is the real narrative line.",
        "got %r" % narrative,
    )


# ---------------------------------------------------------------------------
# T4: panel-10 sorts after panel-9 numerically (not lexicographically)
# ---------------------------------------------------------------------------

def test_glob_numeric_sort():
    with tempfile.TemporaryDirectory() as tmp:
        names = ["panel-1.png", "panel-2.png", "panel-9.png", "panel-10.png"]
        for n in names:
            _make_png(os.path.join(tmp, n))
        matched, err = story_manifest._select_images_glob(tmp, "*.png")
        check("T4 glob numeric sort: no error", err is None, "got %r" % err)
        basenames = [os.path.basename(p) for p in matched]
        check(
            "T4 glob numeric sort: panel-10 sorts after panel-9",
            basenames == ["panel-1.png", "panel-2.png", "panel-9.png", "panel-10.png"],
            "got %r" % basenames,
        )


# ---------------------------------------------------------------------------
# T5: no panel-N key -> mtime fallback ordering + printed NOTE
# ---------------------------------------------------------------------------

def test_glob_mtime_fallback():
    with tempfile.TemporaryDirectory() as tmp:
        names = ["alpha.png", "beta.png", "gamma.png"]
        paths = [os.path.join(tmp, n) for n in names]
        for i, p in enumerate(paths):
            _make_png(p)
            os.utime(p, (1000 + i * 10, 1000 + i * 10))
        # shuffle mtimes so filename order != mtime order
        os.utime(paths[0], (3000, 3000))
        os.utime(paths[1], (1000, 1000))
        os.utime(paths[2], (2000, 2000))

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            matched, err = story_manifest._select_images_glob(tmp, "*.png")
        check("T5 mtime fallback: no error", err is None, "got %r" % err)
        basenames = [os.path.basename(p) for p in matched]
        check(
            "T5 mtime fallback: ordered by mtime ascending",
            basenames == ["beta.png", "gamma.png", "alpha.png"],
            "got %r" % basenames,
        )
        check(
            "T5 mtime fallback: NOTE printed",
            "NOTE: no panel-N key in filenames; ordered by mtime" in buf.getvalue(),
            "got %r" % buf.getvalue(),
        )


# ---------------------------------------------------------------------------
# T6: prompts.md panel count mismatch vs image count -> exit 2
# ---------------------------------------------------------------------------

def test_prompts_count_mismatch_exits_2():
    story_id = "unittest-ltx-story-video-mismatch"
    _rm_story(story_id)
    try:
        with tempfile.TemporaryDirectory() as tmp:
            img1 = os.path.join(tmp, "a.png")
            img2 = os.path.join(tmp, "b.png")
            _make_png(img1)
            _make_png(img2)
            md_path = os.path.join(tmp, "prompts.md")
            with open(md_path, "w") as f:
                f.write("# Story\n\n## Panel 1 - A\nx\n\n## Panel 2 - B\nx\n\n## Panel 3 - C\nx\n")
            rc = story_manifest.main([
                "--story-id", story_id,
                "--prompts-md", md_path,
                "--image", img1,
                "--image", img2,
            ])
            check("T6 prompts.md panel/image count mismatch exits 2", rc == 2, "got %r" % rc)
            manifest_path = os.path.join(story_manifest.WS, "generated", "stories",
                                         story_id, "manifest.json")
            check("T6 no manifest written on mismatch", not os.path.exists(manifest_path))
    finally:
        _rm_story(story_id)


# ---------------------------------------------------------------------------
# T7: existing manifest.json without --force exits 2; with --force overwrites
# ---------------------------------------------------------------------------

def test_overwrite_protection():
    story_id = "unittest-ltx-story-video-overwrite"
    _rm_story(story_id)
    try:
        with tempfile.TemporaryDirectory() as tmp:
            img1 = os.path.join(tmp, "a.png")
            _make_png(img1)
            rc1 = story_manifest.main(["--story-id", story_id, "--image", img1])
            check("T7 first write succeeds", rc1 == 0, "got %r" % rc1)

            manifest_path = os.path.join(story_manifest.WS, "generated", "stories",
                                         story_id, "manifest.json")
            with open(manifest_path) as f:
                first_content = f.read()

            rc2 = story_manifest.main(["--story-id", story_id, "--image", img1])
            check("T7 second write without --force exits 2", rc2 == 2, "got %r" % rc2)
            with open(manifest_path) as f:
                check("T7 manifest unchanged after refused overwrite", f.read() == first_content)

            img2 = os.path.join(tmp, "b.png")
            _make_png(img2)
            rc3 = story_manifest.main(["--story-id", story_id, "--image", img1, "--image", img2, "--force"])
            check("T7 write with --force succeeds", rc3 == 0, "got %r" % rc3)
            with open(manifest_path) as f:
                data = json.load(f)
            check("T7 --force overwrote with new content", len(data["panels"]) == 2,
                  "got %r" % data.get("panels"))
    finally:
        _rm_story(story_id)


def _write_prompt_story(path, n_panels, narrations=None):
    """Write a --no-stills-form story.md with n_panels Prompt:/Narration: panels."""
    lines = ["# Story", "", "A short narrative line.", ""]
    for i in range(1, n_panels + 1):
        narration = (narrations[i - 1] if narrations
                     else " ".join(["word"] * (5 + i)) + ".")
        lines += [
            "## Panel %d — Title %d" % (i, i),
            "Prompt: shot %d of a stone courtyard, cold dawn light, slow push-in" % i,
            "Narration: %s" % narration,
            "",
        ]
    with open(path, "w") as f:
        f.write("\n".join(lines))


def _write_label_story(path, n_panels, narrations=None):
    """Write today's Image:/Motion:/Narration: story.md with the same narrations."""
    lines = ["# Story", "", "A short narrative line.", ""]
    for i in range(1, n_panels + 1):
        narration = (narrations[i - 1] if narrations
                     else " ".join(["word"] * (5 + i)) + ".")
        lines += [
            "## Panel %d — Title %d" % (i, i),
            "Image: shot %d of a stone courtyard, cold dawn light" % i,
            "Motion: slow push-in",
            "Narration: %s" % narration,
            "",
        ]
    with open(path, "w") as f:
        f.write("\n".join(lines))


# ---------------------------------------------------------------------------
# M3: --no-images is mutually exclusive with --glob/--image and requires
# --prompts-md (all exit 2)
# ---------------------------------------------------------------------------

def test_no_images_argument_rejections():
    with tempfile.TemporaryDirectory() as tmp:
        img = os.path.join(tmp, "a.png")
        _make_png(img)
        md = os.path.join(tmp, "story.md")
        _write_prompt_story(md, 2)
        for argv, name in (
            (["--story-id", "unittest-noimg-x", "--prompts-md", md,
              "--no-images", "--glob", "*.png"], "M3a --no-images + --glob exits 2"),
            (["--story-id", "unittest-noimg-x", "--prompts-md", md,
              "--no-images", "--image", img], "M3b --no-images + --image exits 2"),
            (["--story-id", "unittest-noimg-x", "--no-images"],
             "M3c --no-images without --prompts-md exits 2"),
        ):
            rc = None
            try:
                rc = story_manifest.main(argv)
            except SystemExit as e:
                rc = e.code
            check(name, rc == 2, "got %r" % rc)


# ---------------------------------------------------------------------------
# M4: --no-images writes a v2 manifest with null image_path, panel_text ==
# motion_prompt == the collapsed prompt, and num_frames bit-identical to the
# image-driven run over the same narrations (spec criterion 4)
# ---------------------------------------------------------------------------

def test_no_images_manifest_shape_and_frames():
    narrations = ["One short line.", "A rather longer narration line with more words in it.",
                  "Middling length here now."]
    sid_a = "unittest-noimg-a"
    sid_b = "unittest-noimg-b"
    _rm_story(sid_a)
    _rm_story(sid_b)
    try:
        with tempfile.TemporaryDirectory() as tmp:
            md_prompt = os.path.join(tmp, "prompt_story.md")
            md_label = os.path.join(tmp, "label_story.md")
            _write_prompt_story(md_prompt, 3, narrations)
            _write_label_story(md_label, 3, narrations)
            imgs = []
            for i in (1, 2, 3):
                p = os.path.join(tmp, "panel_%d.png" % i)
                _make_png(p)
                imgs.append(p)

            common = ["--fps", "24", "--target-seconds", "6.0",
                      "--min-frames", "25", "--max-frames", "57", "--force"]
            rc_a = story_manifest.main(["--story-id", sid_a, "--prompts-md", md_prompt,
                                        "--no-images"] + common)
            check("M4a --no-images run succeeds", rc_a == 0, "got %r" % rc_a)
            rc_b = story_manifest.main(["--story-id", sid_b, "--prompts-md", md_label,
                                        "--images-dir", tmp, "--glob", "panel_*.png"] + common)
            check("M4b image-driven run succeeds", rc_b == 0, "got %r" % rc_b)

            def _load(sid):
                with open(os.path.join(story_manifest.WS, "generated", "stories", sid,
                                       "manifest.json")) as f:
                    return json.load(f)

            a = _load(sid_a)
            b = _load(sid_b)
            check("M4c schema_version stays 2", a["schema_version"] == 2,
                  "got %r" % a["schema_version"])
            check("M4d panel count equals the story's", len(a["panels"]) == 3,
                  "got %r" % len(a["panels"]))
            check("M4e every image_path is null",
                  all(p["image_path"] is None for p in a["panels"]),
                  "got %r" % [p["image_path"] for p in a["panels"]])
            check("M4f panel_text == motion_prompt == the collapsed prompt",
                  all(p["panel_text"] == p["motion_prompt"]
                      and p["panel_text"].startswith("shot ")
                      for p in a["panels"]),
                  "got %r" % [(p["panel_text"], p["motion_prompt"]) for p in a["panels"]])
            check("M4g num_frames bit-identical to the image-driven run",
                  [p["num_frames"] for p in a["panels"]] ==
                  [p["num_frames"] for p in b["panels"]],
                  "got %r vs %r" % ([p["num_frames"] for p in a["panels"]],
                                    [p["num_frames"] for p in b["panels"]]))
            check("M4h narration/narration_words preserved",
                  [p["narration"] for p in a["panels"]] == narrations,
                  "got %r" % [p["narration"] for p in a["panels"]])
    finally:
        _rm_story(sid_a)
        _rm_story(sid_b)


# ---------------------------------------------------------------------------
# M5: the two Section-8 error rows
# ---------------------------------------------------------------------------

def test_no_images_panel_errors():
    sid = "unittest-noimg-err"
    _rm_story(sid)
    try:
        with tempfile.TemporaryDirectory() as tmp:
            md = os.path.join(tmp, "missing_prompt.md")
            with open(md, "w") as f:
                f.write("# Story\n\nnarr\n\n"
                        "## Panel 1 — A\nPrompt: shot one\nNarration: one.\n\n"
                        "## Panel 2 — B\nNarration: two.\n")
            buf = io.StringIO()
            with contextlib.redirect_stderr(buf):
                rc = story_manifest.main(["--story-id", sid, "--prompts-md", md,
                                          "--no-images", "--force"])
            check("M5a missing Prompt: exits 2", rc == 2, "got %r" % rc)
            check("M5b message names panel 2 and the Prompt: requirement",
                  "--no-images requires every panel to have a non-empty Prompt: field; "
                  "panel 2 has none" in buf.getvalue(),
                  "got %r" % buf.getvalue())

            md2 = os.path.join(tmp, "both_forms.md")
            with open(md2, "w") as f:
                f.write("# Story\n\nnarr\n\n"
                        "## Panel 1 — A\nPrompt: shot one\nImage: also an image\n"
                        "Narration: one.\n")
            buf2 = io.StringIO()
            with contextlib.redirect_stderr(buf2):
                rc2 = story_manifest.main(["--story-id", sid, "--prompts-md", md2,
                                           "--no-images", "--force"])
            check("M5c both Prompt: and Image: exits 2", rc2 == 2, "got %r" % rc2)
            check("M5d message names panel 1 and both forms",
                  "panel 1 has both a Prompt: field and an Image:/Motion: field; "
                  "use one form or the other" in buf2.getvalue(),
                  "got %r" % buf2.getvalue())

            # The both-forms check must fire in image-driven mode too (no
            # --no-images), not just under --no-images -- it is unconditional
            # inside `if args.prompts_md:`, ahead of the `if args.no_images:`
            # branch, and a regression that moved it inside that branch
            # would otherwise go undetected.
            img = os.path.join(tmp, "a.png")
            _make_png(img)
            buf3 = io.StringIO()
            with contextlib.redirect_stderr(buf3):
                rc3 = story_manifest.main(["--story-id", sid, "--prompts-md", md2,
                                           "--image", img, "--force"])
            check("M5e both Prompt: and Image: exits 2 in image-driven mode",
                  rc3 == 2, "got %r" % rc3)
            check("M5f image-driven message names panel 1 and both forms",
                  "panel 1 has both a Prompt: field and an Image:/Motion: field; "
                  "use one form or the other" in buf3.getvalue(),
                  "got %r" % buf3.getvalue())
    finally:
        _rm_story(sid)


# ---------------------------------------------------------------------------
# T8: build_parser() defaults
# ---------------------------------------------------------------------------

def test_video_parser_defaults():
    args = story_video.build_parser().parse_args(["m.json", "o.mp4", "--mode", "per-panel"])
    check("T8 width == 512", args.width == 512, "got %r" % args.width)
    check("T8 height == 512", args.height == 512, "got %r" % args.height)
    check("T8 num_frames == 49", args.num_frames == 49, "got %r" % args.num_frames)
    check("T8 fps == 24", args.fps == 24, "got %r" % args.fps)
    check("T8 frame_rate == 24", args.frame_rate == 24, "got %r" % args.frame_rate)
    check("T8 seed == 0", args.seed == 0, "got %r" % args.seed)
    check("T8 hold_frames == 30", args.hold_frames == 30, "got %r" % args.hold_frames)
    check("T8 settle == 6", args.settle == 6, "got %r" % args.settle)
    check("T8 on_unit_failure == 'stop'", args.on_unit_failure == "stop", "got %r" % args.on_unit_failure)
    for flag in ("wide", "allow_override", "relax_supply", "no_prep", "keep_down",
                 "force", "dry_run", "skip_input_screen"):
        value = getattr(args, flag)
        check("T8 %s defaults to False" % flag, value is False, "got %r" % value)
    check("T8 max_consecutive_failures == 3", args.max_consecutive_failures == 3,
          "got %r" % args.max_consecutive_failures)
    check("T8 retry_failed == 0", args.retry_failed == 0, "got %r" % args.retry_failed)
    check("T8 retry_idle == 120", args.retry_idle == 120, "got %r" % args.retry_idle)
    check("T8 unit_pause == 0", args.unit_pause == 0, "got %r" % args.unit_pause)


# ---------------------------------------------------------------------------
# T9: script's own width/height defaults != ltx_video_skill's DEFAULT_WIDTH/HEIGHT
# ---------------------------------------------------------------------------

def test_defaults_not_refused_geometry():
    args = story_video.build_parser().parse_args(["m.json", "o.mp4", "--mode", "per-panel"])
    check(
        "T9 default width != L.DEFAULT_WIDTH",
        args.width != story_video.L.DEFAULT_WIDTH,
        "got %r == %r" % (args.width, story_video.L.DEFAULT_WIDTH),
    )
    check(
        "T9 default height != L.DEFAULT_HEIGHT",
        args.height != story_video.L.DEFAULT_HEIGHT,
        "got %r == %r" % (args.height, story_video.L.DEFAULT_HEIGHT),
    )


# ---------------------------------------------------------------------------
# fixtures shared by build_units / build_frame_sequence tests
# ---------------------------------------------------------------------------

def _fake_panels(n, motion_prompts=None, transitions=None):
    motion_prompts = motion_prompts or [None] * n
    transitions = transitions or [None] * n
    panels = []
    for i in range(1, n + 1):
        panels.append({
            "index": i,
            "image_path": "/fake/panel%d.png" % i,
            "title": "",
            "panel_text": "panel text %d" % i,
            "motion_prompt": motion_prompts[i - 1],
            "transition_to_next": transitions[i - 1],
        })
    return panels


# ---------------------------------------------------------------------------
# T10: build_units per-panel mode over a 3-panel fixture
# ---------------------------------------------------------------------------

def test_build_units_per_panel():
    panels = _fake_panels(3)
    units = story_video.build_units(panels, "per-panel", num_frames=49, seed=10)
    check("T10 3 units", len(units) == 3, "got %r" % len(units))
    for i, unit in enumerate(units, start=1):
        check("T10 unit %d has 1 condition" % i, len(unit["conditions"]) == 1)
        check("T10 unit %d condition frame_index == 0" % i, unit["conditions"][0]["frame_index"] == 0)
        check("T10 unit %d seed == 10+%d" % (i, i), unit["seed"] == 10 + i, "got %r" % unit["seed"])


# ---------------------------------------------------------------------------
# T11: build_units transitions mode over the same 3-panel fixture
# ---------------------------------------------------------------------------

def test_build_units_transitions():
    panels = _fake_panels(3)
    units = story_video.build_units(panels, "transitions", num_frames=49, seed=0)
    check("T11 2 units", len(units) == 2, "got %r" % len(units))
    for unit in units:
        check("T11 unit has 2 conditions", len(unit["conditions"]) == 2)
        frame_indices = [c["frame_index"] for c in unit["conditions"]]
        check(
            "T11 conditions at frame_index 0 and num_frames-1",
            frame_indices == [0, 48],
            "got %r" % frame_indices,
        )


# ---------------------------------------------------------------------------
# T12: motion_prompt overrides panel_text; null falls back to panel_text
# ---------------------------------------------------------------------------

def test_motion_prompt_override_and_fallback():
    panels = _fake_panels(2, motion_prompts=["custom motion prompt", None])
    units = story_video.build_units(panels, "per-panel", num_frames=49, seed=0)
    check(
        "T12 motion_prompt overrides panel_text",
        units[0]["prompt"] == "custom motion prompt",
        "got %r" % units[0]["prompt"],
    )
    check(
        "T12 null motion_prompt falls back to panel_text",
        units[1]["prompt"] == "panel text 2",
        "got %r" % units[1]["prompt"],
    )


# ---------------------------------------------------------------------------
# T13: transition_to_next: null produces the documented template string
# ---------------------------------------------------------------------------

def test_transition_template_fallback():
    panels = _fake_panels(2)
    units = story_video.build_units(panels, "transitions", num_frames=49, seed=0)
    expected = "panel text 1 The scene transitions smoothly into: panel text 2"
    check(
        "T13 transition_to_next null -> documented template",
        units[0]["prompt"] == expected,
        "got %r" % units[0]["prompt"],
    )


# ---------------------------------------------------------------------------
# T14: transitions mode with only 1 panel raises the documented error
# ---------------------------------------------------------------------------

def test_transitions_single_panel_rejected():
    panels = _fake_panels(1)
    raised = False
    try:
        story_video.build_units(panels, "transitions", num_frames=49, seed=0)
    except ValueError:
        raised = True
    check("T14 transitions mode with 1 panel raises ValueError", raised)


# ---------------------------------------------------------------------------
# T15: manifest loader rejects a gap in index (1, 2, 4)
# ---------------------------------------------------------------------------

def test_load_manifest_rejects_index_gap():
    with tempfile.TemporaryDirectory() as tmp:
        img_paths = []
        for i in (1, 2, 3):
            p = os.path.join(tmp, "img%d.png" % i)
            _make_png(p)
            img_paths.append(p)
        manifest = {
            "schema_version": 1,
            "story_id": "x",
            "title": "",
            "narrative": "",
            "created_at": "2026-01-01T00:00:00+00:00",
            "panels": [
                {"index": 1, "image_path": img_paths[0], "title": "", "panel_text": "a",
                 "motion_prompt": None, "transition_to_next": None},
                {"index": 2, "image_path": img_paths[1], "title": "", "panel_text": "b",
                 "motion_prompt": None, "transition_to_next": None},
                {"index": 4, "image_path": img_paths[2], "title": "", "panel_text": "c",
                 "motion_prompt": None, "transition_to_next": None},
            ],
        }
        manifest_path = os.path.join(tmp, "manifest.json")
        with open(manifest_path, "w") as f:
            json.dump(manifest, f)
        raised = False
        try:
            story_video.load_manifest(manifest_path)
        except ValueError:
            raised = True
        check("T15 index gap (1,2,4) rejected", raised)


# ---------------------------------------------------------------------------
# T16: AST guard -- signal.signal(signal.SIGTERM, ...) present, and a
# try/finally whose finally block calls a _restore-named function
# ---------------------------------------------------------------------------

def _has_sigterm_signal_call(tree):
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            if (isinstance(func, ast.Attribute) and func.attr == "signal"
                    and isinstance(func.value, ast.Name) and func.value.id == "signal"
                    and node.args):
                arg0 = node.args[0]
                if isinstance(arg0, ast.Attribute) and arg0.attr == "SIGTERM":
                    return True
    return False


def _finally_calls_restore(tree):
    for node in ast.walk(tree):
        if isinstance(node, ast.Try):
            for stmt in node.finalbody:
                for sub in ast.walk(stmt):
                    if isinstance(sub, ast.Call):
                        func = sub.func
                        name = None
                        if isinstance(func, ast.Attribute):
                            name = func.attr
                        elif isinstance(func, ast.Name):
                            name = func.id
                        if name and "_restore" in name:
                            return True
    return False


def test_ast_guard_signal_and_restore():
    with open(_VIDEO_PATH) as f:
        tree = ast.parse(f.read(), filename=_VIDEO_PATH)
    check("T16a signal.signal(signal.SIGTERM, ...) present", _has_sigterm_signal_call(tree))
    check("T16b try/finally's finally block calls a _restore-named function",
          _finally_calls_restore(tree))


# ---------------------------------------------------------------------------
# T17: AST guard -- L._release_page_cache is called inside a for-loop
# (the per-unit loop), not just once at module scope
# ---------------------------------------------------------------------------

def _contains_release_page_cache_call(node):
    for child in ast.walk(node):
        if isinstance(child, ast.Call):
            func = child.func
            if isinstance(func, ast.Attribute) and func.attr == "_release_page_cache":
                return True
    return False


def test_ast_guard_release_page_cache_in_loop():
    with open(_VIDEO_PATH) as f:
        tree = ast.parse(f.read(), filename=_VIDEO_PATH)
    found_in_loop = any(
        isinstance(node, ast.For) and _contains_release_page_cache_call(node)
        for node in ast.walk(tree)
    )
    check("T17 _release_page_cache is called inside a for-loop", found_in_loop)


# ---------------------------------------------------------------------------
# T18: AST guard -- no top-level `import torch` / `import diffusers` /
# `from diffusers import ...`
# ---------------------------------------------------------------------------

def test_ast_guard_no_toplevel_heavy_imports():
    with open(_VIDEO_PATH) as f:
        tree = ast.parse(f.read(), filename=_VIDEO_PATH)
    violations = []
    for node in tree.body:
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.split(".")[0] in ("torch", "diffusers"):
                    violations.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module and node.module.split(".")[0] in ("torch", "diffusers"):
                violations.append(node.module)
    check("T18 no top-level import of torch/diffusers", not violations, "found: %r" % violations)


# ---------------------------------------------------------------------------
# T19: frame-assembly ordering (transitions mode with holds, and hold=0)
# ---------------------------------------------------------------------------

def test_build_frame_sequence_ordering():
    unit1_frames = ["u1f0", "u1f1"]
    unit2_frames = ["u2f0", "u2f1", "u2f2"]
    holds = ["H1", "H2", "H3"]

    sequence = story_video.build_frame_sequence([unit1_frames, unit2_frames], "transitions", 30, holds)
    expected = ["H1"] * 30 + unit1_frames + ["H2"] * 30 + unit2_frames + ["H3"] * 30
    check("T19 transitions with hold_frames=30", sequence == expected, "got %r" % sequence)

    sequence0 = story_video.build_frame_sequence([unit1_frames, unit2_frames], "transitions", 0, holds)
    expected0 = unit1_frames + unit2_frames
    check("T19 transitions with hold_frames=0 collapses to unit frames", sequence0 == expected0,
          "got %r" % sequence0)


# ---------------------------------------------------------------------------
# T20: AST guard -- the concat input is rebuilt by iterating `units` and
# indexing a dict (unit_frames_by_index), never by list-append ordering
# ---------------------------------------------------------------------------

def test_ast_guard_order_safe_concat():
    with open(_VIDEO_PATH) as f:
        source = f.read()
    tree = ast.parse(source, filename=_VIDEO_PATH)

    check("T20a no all_unit_frames.append( in source", "all_unit_frames.append(" not in source)

    found = False
    for node in ast.walk(tree):
        if isinstance(node, (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp, ast.For)):
            for sub in ast.walk(node):
                if isinstance(sub, ast.Subscript) and isinstance(sub.value, ast.Name) \
                        and "unit_frames_by_index" in sub.value.id:
                    found = True
    check("T20b Subscript on unit_frames_by_index appears inside a comprehension/for", found)


# ---------------------------------------------------------------------------
# T21: AST guard -- _release_page_cache is called in >= 2 distinct for-loops
# (the main loop and the retry pass)
# ---------------------------------------------------------------------------

def test_ast_guard_release_page_cache_two_loops():
    with open(_VIDEO_PATH) as f:
        tree = ast.parse(f.read(), filename=_VIDEO_PATH)
    count = sum(
        1 for node in ast.walk(tree)
        if isinstance(node, ast.For) and _contains_release_page_cache_call(node)
    )
    check("T21 _release_page_cache called in >= 2 distinct for-loops", count >= 2, "got %r" % count)


# ---------------------------------------------------------------------------
# T22: AST guard -- the retry block's guarding if-test references
# content_blocked (retry never runs when content-blocked)
# ---------------------------------------------------------------------------

def test_ast_guard_retry_guard_references_content_blocked():
    with open(_VIDEO_PATH) as f:
        tree = ast.parse(f.read(), filename=_VIDEO_PATH)
    found = False
    for node in ast.walk(tree):
        if isinstance(node, ast.If):
            dumped = ast.dump(node.test)
            if "retry_failed" in dumped and "content_blocked" in dumped:
                found = True
    check("T22 retry guard if-test references content_blocked", found)


# ---------------------------------------------------------------------------
# M1: _snap_frames -- nearest n with (n-1)%8==0, n>=9; exact ties resolve DOWN
# ---------------------------------------------------------------------------

def test_snap_frames():
    cases = [(8.9, 9), (20.9, 17), (21.0, 17), (21.1, 25), (48, 49), (4, 9)]
    for x, expected in cases:
        got = story_manifest._snap_frames(x)
        check("M1 _snap_frames(%r) == %d" % (x, expected), got == expected, "got %r" % got)


# ---------------------------------------------------------------------------
# M2: _allocate_frames basic envelope (equal weights)
# ---------------------------------------------------------------------------

def test_allocate_frames_basic_envelope():
    f = story_manifest._allocate_frames([1] * 15, 720, 25, 57)
    check("M2 every value == 1 mod 8", all((v - 1) % 8 == 0 for v in f), "got %r" % f)
    check("M2 every value in [25, 57]", all(25 <= v <= 57 for v in f), "got %r" % f)
    check("M2 sum within 8 of target", abs(720 - sum(f)) <= 8, "got sum=%r" % sum(f))


# ---------------------------------------------------------------------------
# M3: _allocate_frames weighted ordering (heavier weight -> more frames)
# ---------------------------------------------------------------------------

def test_allocate_frames_weighted_ordering():
    f = story_manifest._allocate_frames([30, 10, 10], 240, 9, 121)
    check("M3 f[0] > f[1] == f[2]", f[0] > f[1] == f[2], "got %r" % f)


# ---------------------------------------------------------------------------
# M4: _allocate_frames with min==max==33 clamps every panel to 33 (not
# achievable within 8 of 720); the CLI must reject this combination
# ---------------------------------------------------------------------------

def test_allocate_frames_infeasible_envelope_and_cli_rejects():
    f = story_manifest._allocate_frames([1] * 15, 720, 33, 33)
    check("M4 every value == 33", all(v == 33 for v in f), "got %r" % f)
    check("M4 not achievable within 8 of target", abs(720 - sum(f)) > 8, "got sum=%r" % sum(f))

    with tempfile.TemporaryDirectory() as tmp:
        lines = ["# Story", ""]
        imgs = []
        for i in range(1, 16):
            p = os.path.join(tmp, "panel-%d.png" % i)
            _make_png(p)
            imgs.append(p)
            lines.append("## Panel %d - Scene %d" % (i, i))
            lines.append("Image: image %d" % i)
            lines.append("Motion: motion %d" % i)
            lines.append("Narration: %s" % ("word " * i).strip())
            lines.append("")
        md_path = os.path.join(tmp, "story.md")
        with open(md_path, "w") as fh:
            fh.write("\n".join(lines))

        story_id = "unittest-m4-infeasible"
        _rm_story(story_id)
        try:
            argv = ["--story-id", story_id, "--prompts-md", md_path]
            for im in imgs:
                argv += ["--image", im]
            argv += ["--min-frames", "33", "--max-frames", "33", "--target-seconds", "30"]
            buf = io.StringIO()
            with contextlib.redirect_stderr(buf):
                rc = story_manifest.main(argv)
            check("M4 CLI exits 2 on an infeasible min==max envelope", rc == 2, "got %r" % rc)
            check("M4 CLI error names the achievable range [495, 495]",
                  "[495, 495]" in buf.getvalue(), "got %r" % buf.getvalue())
        finally:
            _rm_story(story_id)


# ---------------------------------------------------------------------------
# M5: _allocate_frames is deterministic
# ---------------------------------------------------------------------------

def test_allocate_frames_determinism():
    results = {tuple(story_manifest._allocate_frames([1, 3, 5, 2], 200, 9, 121)) for _ in range(100)}
    check("M5 deterministic across 100 calls", len(results) == 1, "got %r distinct results" % len(results))


# ---------------------------------------------------------------------------
# V1/V2/V3: per-unit variable frames in build_units (schema_version 2
# per-panel num_frames vs. schema_version 1 fallback)
# ---------------------------------------------------------------------------

def _fake_panels_v2(frames_list):
    panels = []
    for i, nf in enumerate(frames_list, start=1):
        panels.append({
            "index": i,
            "image_path": "/fake/panel%d.png" % i,
            "title": "",
            "panel_text": "panel text %d" % i,
            "motion_prompt": None,
            "transition_to_next": None,
            "num_frames": nf,
        })
    return panels


def test_build_units_v2_per_panel_num_frames():
    panels = _fake_panels_v2([41, 33, 57])
    units = story_video.build_units(panels, "per-panel", num_frames=49, seed=0)
    got = [u["num_frames"] for u in units]
    check("V1 per-panel units use each panel's own num_frames", got == [41, 33, 57], "got %r" % got)


def test_build_units_v1_fallback_num_frames():
    panels = _fake_panels(3)  # no num_frames key at all (schema_version 1)
    units = story_video.build_units(panels, "per-panel", num_frames=49, seed=0)
    got = [u["num_frames"] for u in units]
    check("V2 v1 manifest (no num_frames) falls back to the global default",
          got == [49, 49, 49], "got %r" % got)


def test_build_units_transitions_v2_frame_index():
    panels = _fake_panels_v2([41, 33, 57])
    units = story_video.build_units(panels, "transitions", num_frames=49, seed=0)
    frame_indices = [u["conditions"][1]["frame_index"] for u in units]
    check(
        "V3 transitions 2nd condition frame_index == earlier panel's num_frames - 1",
        frame_indices == [40, 32],
        "got %r" % frame_indices,
    )


# ---------------------------------------------------------------------------
# V4: load_manifest rejects a schema_version 2 panel with a num_frames that
# fails the (n-1)%8==0 rule, naming the panel and the rule
# ---------------------------------------------------------------------------

def test_load_manifest_rejects_bad_num_frames_v2():
    with tempfile.TemporaryDirectory() as tmp:
        img_paths = []
        for i in (1, 2):
            p = os.path.join(tmp, "img%d.png" % i)
            _make_png(p)
            img_paths.append(p)
        manifest = {
            "schema_version": 2,
            "story_id": "x",
            "title": "",
            "narrative": "",
            "created_at": "2026-01-01T00:00:00+00:00",
            "panels": [
                {"index": 1, "image_path": img_paths[0], "title": "", "panel_text": "a",
                 "narration": "", "narration_words": 0, "num_frames": 49, "duration_s": 2.042,
                 "motion_prompt": None, "transition_to_next": None},
                {"index": 2, "image_path": img_paths[1], "title": "", "panel_text": "b",
                 "narration": "", "narration_words": 0, "num_frames": 50, "duration_s": 2.083,
                 "motion_prompt": None, "transition_to_next": None},
            ],
        }
        manifest_path = os.path.join(tmp, "manifest.json")
        with open(manifest_path, "w") as f:
            json.dump(manifest, f)
        raised = False
        message = ""
        try:
            story_video.load_manifest(manifest_path)
        except ValueError as e:
            raised = True
            message = str(e)
        check("V4 schema_version 2 rejects num_frames=50", raised)
        check("V4 error names panel 2 and the %8 rule", "panel 2" in message and "%" in message,
              "got %r" % message)


# ---------------------------------------------------------------------------
# C1: --engine/--reanchor-every defaults, and the two parse-time rejections
# ---------------------------------------------------------------------------

def test_engine_flag_defaults_and_rejections():
    args = story_video.build_parser().parse_args(["m.json", "o.mp4", "--mode", "per-panel"])
    check("C1a engine default is per-panel", args.engine == "per-panel", "got %r" % args.engine)
    check("C1b reanchor_every default is 5", args.reanchor_every == 5,
          "got %r" % args.reanchor_every)

    args = story_video.build_parser().parse_args(
        ["m.json", "o.mp4", "--mode", "per-panel", "--engine", "chain",
         "--reanchor-every", "3"])
    check("C1c engine parses to chain", args.engine == "chain", "got %r" % args.engine)
    check("C1d reanchor_every parses to 3", args.reanchor_every == 3,
          "got %r" % args.reanchor_every)

    for argv, name in (
        (["m.json", "o.mp4", "--mode", "transitions", "--engine", "chain"],
         "C1e --engine chain + --mode transitions exits 2"),
        (["m.json", "o.mp4", "--mode", "per-panel", "--engine", "chain",
          "--reanchor-every", "0"], "C1f --reanchor-every 0 exits 2"),
    ):
        rc = None
        try:
            rc = story_video.main(argv)
        except SystemExit as e:
            rc = e.code
        check(name, rc == 2, "got %r" % rc)


# ---------------------------------------------------------------------------
# C2: load_manifest(allow_null_image_path=True) accepts null image_path but
# keeps every other check; the default still rejects null
# ---------------------------------------------------------------------------

def _v2_manifest(tmp, panels):
    path = os.path.join(tmp, "manifest.json")
    with open(path, "w") as f:
        json.dump({"schema_version": 2, "story_id": "x", "title": "", "narrative": "",
                   "created_at": "2026-01-01T00:00:00+00:00", "fps": 24,
                   "panels": panels}, f)
    return path


def _null_panel(index, panel_text="a shot", num_frames=25):
    return {"index": index, "image_path": None, "title": "", "panel_text": panel_text,
            "narration": "", "narration_words": 0, "num_frames": num_frames,
            "duration_s": 1.0, "motion_prompt": panel_text, "transition_to_next": None}


def test_load_manifest_allow_null_image_path():
    with tempfile.TemporaryDirectory() as tmp:
        ok = _v2_manifest(tmp, [_null_panel(1), _null_panel(2)])
        data = story_video.load_manifest(ok, allow_null_image_path=True)
        check("C2a null image_path accepted when allowed",
              [p["image_path"] for p in data["panels"]] == [None, None],
              "got %r" % [p["image_path"] for p in data["panels"]])

        raised = False
        try:
            story_video.load_manifest(ok)
        except ValueError as e:
            raised = "image_path does not exist or is not readable" in str(e)
        check("C2b default still rejects null with today's message", raised)

        gap = _v2_manifest(tmp, [_null_panel(1), _null_panel(3)])
        raised = False
        try:
            story_video.load_manifest(gap, allow_null_image_path=True)
        except ValueError as e:
            raised = "indexed contiguously" in str(e)
        check("C2c index gap still rejected when null is allowed", raised)

        empty_text = _v2_manifest(tmp, [_null_panel(1, panel_text="   ")])
        raised = False
        try:
            story_video.load_manifest(empty_text, allow_null_image_path=True)
        except ValueError as e:
            raised = "panel_text is required" in str(e)
        check("C2d empty panel_text still rejected", raised)

        bad_frames = _v2_manifest(tmp, [_null_panel(1, num_frames=50)])
        raised = False
        try:
            story_video.load_manifest(bad_frames, allow_null_image_path=True)
        except ValueError as e:
            raised = "% 8 == 0" in str(e)
        check("C2e bad v2 num_frames still rejected", raised)

        img = os.path.join(tmp, "real.png")
        _make_png(img)
        mixed_ok = _v2_manifest(tmp, [_null_panel(1),
                                      dict(_null_panel(2), image_path=img)])
        data = story_video.load_manifest(mixed_ok, allow_null_image_path=True)
        check("C2f a mixed manifest is legal and the string path is kept",
              data["panels"][1]["image_path"] == img,
              "got %r" % data["panels"][1]["image_path"])

        mixed_bad = _v2_manifest(tmp, [_null_panel(1),
                                       dict(_null_panel(2),
                                            image_path=os.path.join(tmp, "nope.png"))])
        raised = False
        try:
            story_video.load_manifest(mixed_bad, allow_null_image_path=True)
        except ValueError as e:
            raised = "image_path does not exist or is not readable" in str(e)
        check("C2g a non-null path is still fully validated", raised)


# ---------------------------------------------------------------------------
# C3: chain-engine grouping arithmetic (spec criterion 5) and per-panel parity
# ---------------------------------------------------------------------------

def test_build_units_chain_grouping():
    panels = _fake_panels_v2([41, 33, 49, 41, 33, 41, 33, 49, 41, 33, 41, 33])
    chain = story_video.build_units(panels, "per-panel", 49, 0,
                                    engine="chain", reanchor_every=5)
    per = story_video.build_units(panels, "per-panel", 49, 0)

    check("C3a openers are exactly {1, 6, 11}",
          [u["index"] for u in chain if u["role"] == "opener"] == [1, 6, 11],
          "got %r" % [u["index"] for u in chain if u["role"] == "opener"])
    check("C3b group numbers", [u["group"] for u in chain] ==
          [1, 1, 1, 1, 1, 2, 2, 2, 2, 2, 3, 3],
          "got %r" % [u["group"] for u in chain])
    check("C3c continue_from_index is None for openers, i-1 for followers",
          all((u["continue_from_index"] is None) if u["role"] == "opener"
              else (u["continue_from_index"] == u["index"] - 1) for u in chain))
    check("C3d every unit's conditions == []",
          all(u["conditions"] == [] for u in chain),
          "got %r" % [u["conditions"] for u in chain])
    for key in ("label", "seed", "prompt", "num_frames"):
        check("C3e %s identical to the per-panel engine" % key,
              [u[key] for u in chain] == [u[key] for u in per],
              "got %r vs %r" % ([u[key] for u in chain], [u[key] for u in per]))

    one = story_video.build_units(_fake_panels_v2([25] * 4), "per-panel", 49, 0,
                                  engine="chain", reanchor_every=1)
    check("C3f reanchor_every=1 makes every panel an opener",
          all(u["role"] == "opener" and u["continue_from_index"] is None for u in one))
    check("C3g reanchor_every=1 group numbers are 1..N",
          [u["group"] for u in one] == [1, 2, 3, 4], "got %r" % [u["group"] for u in one])

    exact = story_video.build_units(_fake_panels_v2([25] * 5), "per-panel", 49, 0,
                                    engine="chain", reanchor_every=5)
    check("C3h 5 panels at R=5 is exactly one group",
          [u["group"] for u in exact] == [1, 1, 1, 1, 1], "got %r" % [u["group"] for u in exact])

    short = story_video.build_units(_fake_panels_v2([25] * 6), "per-panel", 49, 0,
                                    engine="chain", reanchor_every=5)
    check("C3i 6 panels at R=5 gives a 1-panel final group",
          [u["group"] for u in short] == [1, 1, 1, 1, 1, 2] and short[5]["role"] == "opener",
          "got %r" % [(u["group"], u["role"]) for u in short])


def test_build_units_per_panel_has_no_chain_keys():
    per = story_video.build_units(_fake_panels_v2([25, 33]), "per-panel", 49, 0)
    check("C4a per-panel units carry no role/group/continue_from_index keys",
          all(not ({"role", "group", "continue_from_index"} & set(u)) for u in per),
          "got %r" % [sorted(u) for u in per])
    trans = story_video.build_units(_fake_panels_v2([25, 33]), "transitions", 49, 0)
    check("C4b transitions units carry no chain keys",
          all(not ({"role", "group", "continue_from_index"} & set(u)) for u in trans),
          "got %r" % [sorted(u) for u in trans])


def test_chain_groups_descriptors():
    units = story_video.build_units(_fake_panels_v2([25] * 12), "per-panel", 49, 0,
                                    engine="chain", reanchor_every=5)
    groups = story_video._chain_groups(units)
    check("C5a three groups", [g["group"] for g in groups] == [1, 2, 3],
          "got %r" % groups)
    check("C5b panel membership",
          [g["panels"] for g in groups] == [[1, 2, 3, 4, 5], [6, 7, 8, 9, 10], [11, 12]],
          "got %r" % [g["panels"] for g in groups])
    check("C5c openers", [g["opener"] for g in groups] == [1, 6, 11],
          "got %r" % [g["opener"] for g in groups])


# ---------------------------------------------------------------------------
# C6: _build_request(mode_field=) -- opener vs today's shape
# ---------------------------------------------------------------------------

def test_build_request_mode_field():
    opener = story_video._build_request(
        "a shot", "neg", 512, 512, 25, 24, 24, False, False, 1, [], mode_field="t2v")
    check("C6a opener image_path is None", opener["image_path"] is None,
          "got %r" % opener["image_path"])
    check("C6b opener mode == t2v", opener["mode"] == "t2v", "got %r" % opener.get("mode"))
    check("C6c opener conditions == []", opener["conditions"] == [],
          "got %r" % opener["conditions"])
    check("C6d opener prompt/seed/num_frames unchanged",
          (opener["prompt"], opener["seed"], opener["num_frames"]) == ("a shot", 1, 25),
          "got %r" % [opener["prompt"], opener["seed"], opener["num_frames"]])

    cond = [{"image_path": "/x/a.png", "frame_index": 0, "strength": 1.0}]
    today = story_video._build_request(
        "a shot", "neg", 512, 512, 25, 24, 24, False, False, 1, cond)
    check("C6e no mode key without mode_field", "mode" not in today,
          "got keys %r" % sorted(today))
    check("C6f image_path still index-0s the conditions list",
          today["image_path"] == "/x/a.png", "got %r" % today["image_path"])
    check("C6g explicit mode_field=None also omits the key",
          "mode" not in story_video._build_request(
              "a shot", "neg", 512, 512, 25, 24, 24, False, False, 1, cond,
              mode_field=None))


# ---------------------------------------------------------------------------
# C7: --engine chain --dry-run prints the group/role table and touches nothing
# ---------------------------------------------------------------------------

def test_chain_dry_run_output():
    sid = "unittest-chain-dryrun"
    with tempfile.TemporaryDirectory() as tmp:
        panels = [_null_panel(i, panel_text="shot %d" % i,
                              num_frames=[41, 33, 49, 41, 33, 41][i - 1])
                  for i in range(1, 7)]
        manifest_path = _v2_manifest(tmp, panels)
        out_mp4 = os.path.join(tmp, "out.mp4")
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = story_video.main([manifest_path, out_mp4, "--mode", "per-panel",
                                   "--engine", "chain", "--reanchor-every", "5",
                                   "--dry-run"])
        text = buf.getvalue()
        check("C7a exits 0", rc == 0, "got %r" % rc)
        check("C7b header names the engine and group size",
              "=== dry run: 6 unit(s), mode=per-panel, engine=chain, reanchor-every=5 ===" in text,
              "got %r" % text)
        check("C7c group 1 header spans panels 1-5", "--- group 1 (panels 1-5) ---" in text)
        check("C7d short final group prints its real range",
              "--- group 2 (panels 6-6) ---" in text)
        check("C7e panel 1 is a T2V opener",
              "1 | panel-1 | seed=1 | frames=41 (1.71s) | T2V opener | prompt=" in text,
              "got %r" % text)
        check("C7f panel 2 names the panel it continues from",
              "2 | panel-2 | seed=2 | frames=33 (1.38s) | chain follower <- panel-1 | prompt=" in text)
        check("C7g panel 6 is an opener again",
              "6 | panel-6 | seed=6 | frames=41 (1.71s) | T2V opener | prompt=" in text)
        check("C7h TOTAL line unchanged", "TOTAL 238 frames, 9.92s" in text,
              "got %r" % text)
        check("C7i conditions=[...] is dropped in this engine",
              "conditions=[" not in text, "got %r" % text)
        check("C7j no output file was written", not os.path.exists(out_mp4))
    _rm_story(sid)


def test_per_panel_dry_run_unchanged():
    with tempfile.TemporaryDirectory() as tmp:
        img = os.path.join(tmp, "p1.png")
        _make_png(img)
        manifest_path = _v2_manifest(
            tmp, [dict(_null_panel(1, panel_text="shot 1", num_frames=25),
                       image_path=img)])
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = story_video.main([manifest_path, os.path.join(tmp, "o.mp4"),
                                   "--mode", "per-panel", "--dry-run"])
        text = buf.getvalue()
        check("C8a per-panel dry-run exits 0", rc == 0, "got %r" % rc)
        check("C8b per-panel header is unchanged",
              "=== dry run: 1 unit(s), mode=per-panel ===" in text, "got %r" % text)
        check("C8c per-panel line still shows conditions=[...]",
              "conditions=[" in text and "T2V opener" not in text, "got %r" % text)


# ---------------------------------------------------------------------------
# C9: nested ltx-chain command line (I4 + DR4) -- exact argv
# ---------------------------------------------------------------------------

def test_build_chain_follower_cmd():
    args = story_video.build_parser().parse_args(
        ["m.json", "o.mp4", "--mode", "per-panel", "--engine", "chain",
         "--width", "512", "--height", "512", "--fps", "24", "--frame-rate", "24",
         "--seed", "0", "--settle", "6", "--negative-prompt", "neg"])
    unit = {"index": 3, "label": "panel-3", "seed": 3, "prompt": "shot three",
            "num_frames": 49, "conditions": [], "role": "follower", "group": 1,
            "continue_from_index": 2}
    cmd = story_video._build_chain_follower_cmd(
        args, unit, "/base/dir", "/base/dir/frames/frame_00032.png", "/cell/_chain_scratch.mp4")
    check("C9a resolves ltx-chain next to this tool, not via WS",
          cmd[1] == os.path.join(os.path.dirname(os.path.realpath(_VIDEO_PATH)), "ltx-chain"),
          "got %r" % cmd[1])
    for flag in ("--continue-from", "--segments", "--no-prep", "--keep-down", "--force"):
        check("C9b %s present" % flag, flag in cmd, "got %r" % cmd)
    check("C9c --segments is 1", cmd[cmd.index("--segments") + 1] == "1", "got %r" % cmd)
    check("C9d --num-frames is the FOLLOWER's own length",
          cmd[cmd.index("--num-frames") + 1] == "49", "got %r" % cmd)
    check("C9e --seed is the PREDECESSOR's seed (args.seed + continue_from_index)",
          cmd[cmd.index("--seed") + 1] == "2", "got %r" % cmd)
    check("C9f --negative-prompt is passed explicitly",
          cmd[cmd.index("--negative-prompt") + 1] == "neg", "got %r" % cmd)
    check("C9g positionals are last: last frame, prompt, scratch mp4",
          cmd[-3:] == ["/base/dir/frames/frame_00032.png", "shot three",
                       "/cell/_chain_scratch.mp4"], "got %r" % cmd[-3:])
    check("C9h --wide/--allow-override/--relax-supply absent when off",
          not ({"--wide", "--allow-override", "--relax-supply"} & set(cmd)), "got %r" % cmd)

    args2 = story_video.build_parser().parse_args(
        ["m.json", "o.mp4", "--mode", "per-panel", "--engine", "chain",
         "--wide", "--allow-override", "--relax-supply"])
    cmd2 = story_video._build_chain_follower_cmd(args2, unit, "/b", "/b/f.png", "/c/s.mp4")
    check("C9i pass-through flags forwarded when set",
          {"--wide", "--allow-override", "--relax-supply"} <= set(cmd2), "got %r" % cmd2)


# ---------------------------------------------------------------------------
# C10: run-root parsing and stdout marker extraction
# ---------------------------------------------------------------------------

def test_chain_run_root_parsing():
    out = ("=== prep ===\nrun root: /a/generated/ltx_chains/first\n"
           "some noise\nrun root: /a/generated/ltx_chains/second\nDONE\n")
    check("C10a the LAST run root wins",
          story_video._chain_run_root_from_stdout(out) == "/a/generated/ltx_chains/second",
          "got %r" % story_video._chain_run_root_from_stdout(out))
    check("C10b None when absent",
          story_video._chain_run_root_from_stdout("no root here\n") is None)
    check("C10c marker line extracted",
          story_video._find_stdout_line(
              "x\nError: --continue-from base run width=512 does not match requested "
              "width=704 (continuation must use the same settings as the base)\ny",
              "does not match requested").startswith("Error: --continue-from base run width"))
    check("C10d absent marker reports itself",
          "not found" in story_video._find_stdout_line("nothing", "does not match requested"))


# ---------------------------------------------------------------------------
# C11: AST guards -- the I4 invariant and the seg1-only harvest (spec 9.1
# items 13 and 14)
# ---------------------------------------------------------------------------

def _func_def(tree, name):
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    return None


def test_ast_guard_chain_follower_invocation():
    with open(_VIDEO_PATH) as f:
        source = f.read()
    tree = ast.parse(source, filename=_VIDEO_PATH)
    fn = _func_def(tree, "_build_chain_follower_cmd")
    check("C11a _build_chain_follower_cmd exists", fn is not None)
    consts = {n.value for n in ast.walk(fn)
              if isinstance(n, ast.Constant) and isinstance(n.value, str)}
    for flag in ("--no-prep", "--keep-down", "--segments", "--continue-from"):
        check("C11b %s is a literal in the nested argv (I4)" % flag, flag in consts,
              "got %r" % sorted(consts))


def test_ast_guard_follower_harvests_seg1_only():
    with open(_VIDEO_PATH) as f:
        source = f.read()
    tree = ast.parse(source, filename=_VIDEO_PATH)
    fn = _func_def(tree, "_render_chain_follower")
    check("C11c _render_chain_follower exists", fn is not None)
    body = ast.get_source_segment(source, fn) or ""
    check("C11d the base for the NEXT follower is the seg1 dir",
          'seg_dir = os.path.join(chain_run_root, "seg1")' in body, "got %r" % body[:400])
    check("C11e frames are globbed from seg1/frames only",
          'glob.glob(os.path.join(seg_dir, "frames", "frame_*.png"))' in body)
    check("C11f the throwaway mp4 is never a frame source",
          "_chain_scratch.mp4" in body and ".mp4" not in body.split("frames")[0][-40:],
          "got %r" % body[:400])
    check("C11g the scratch mp4 is deleted on both paths",
          body.count("os.remove(scratch_mp4)") >= 2, "got %r" % body.count("os.remove(scratch_mp4)"))


# ---------------------------------------------------------------------------
# C12: _render_chain_follower behavioral tests (real exercise of spec
# correction C5, the plan's highest-risk correctness property: a follower
# must read its predecessor's ACTUAL base -- an opener's own cell, or an
# earlier follower's nested seg1/ dir -- never a panel-<k> path that a
# follower predecessor never writes). No real subprocess is spawned:
# story_video.subprocess is swapped for a fake module object whose .run
# returns a canned CompletedProcess, then restored in a finally.
# ---------------------------------------------------------------------------

def _make_base_cell(tmp, name, num_frames):
    """Build a fake completed unit cell: embeds.pt + request.json + frames/,
    exactly what an opener's in-process cell (or a nested chain's seg1/
    cell) looks like once a unit has finished."""
    cell = os.path.join(tmp, name)
    os.makedirs(os.path.join(cell, "frames"))
    with open(os.path.join(cell, "embeds.pt"), "w") as f:
        f.write("fake")
    with open(os.path.join(cell, "request.json"), "w") as f:
        json.dump({}, f)
    for i in range(num_frames):
        _make_png(os.path.join(cell, "frames", "frame_%05d.png" % i))
    return cell


def _canned_chain_run(tmp, name, num_frames):
    """Build a fake nested-ltx-chain run root with a seg1/ cell (what a real
    `ltx-chain --continue-from ... --segments 1` invocation writes on disk --
    embeds.pt, request.json AND frames/, so a LATER follower's own
    --continue-from validation against this seg1/ dir succeeds), and return
    (chain_run_root, canned child stdout)."""
    chain_run_root = os.path.join(tmp, name)
    seg_dir = os.path.join(chain_run_root, "seg1")
    os.makedirs(os.path.join(seg_dir, "frames"))
    with open(os.path.join(seg_dir, "embeds.pt"), "w") as f:
        f.write("fake")
    with open(os.path.join(seg_dir, "request.json"), "w") as f:
        json.dump({}, f)
    for i in range(num_frames):
        _make_png(os.path.join(seg_dir, "frames", "frame_%05d.png" % i))
    stdout = "=== prep ===\nrun root: %s\nDONE\n" % chain_run_root
    return chain_run_root, stdout


def test_render_chain_follower_single_hop():
    with tempfile.TemporaryDirectory() as tmp:
        base_dir = _make_base_cell(tmp, "panel-2", num_frames=9)
        chain_run_root, stdout = _canned_chain_run(tmp, "chain-3", num_frames=9)

        real_subprocess = story_video.subprocess

        def fake_run(cmd, **kwargs):
            return subprocess.CompletedProcess(args=cmd, returncode=0, stdout=stdout)

        story_video.subprocess = types.SimpleNamespace(
            run=fake_run, PIPE=subprocess.PIPE, STDOUT=subprocess.STDOUT)
        try:
            args = story_video.build_parser().parse_args(
                ["m.json", "o.mp4", "--mode", "per-panel", "--engine", "chain"])
            unit = {"index": 3, "label": "panel-3", "seed": 3, "prompt": "shot three",
                    "num_frames": 9, "conditions": [], "role": "follower", "group": 1,
                    "continue_from_index": 2}
            cell = os.path.join(tmp, "panel-3")
            chain_base_by_index = {2: base_dir}
            outcome = story_video._render_chain_follower(args, unit, cell, chain_base_by_index)
        finally:
            story_video.subprocess = real_subprocess

        check("C12a single-hop follower returns ok",
              outcome["status"] == "ok", "got %r" % outcome)
        check("C12b base_for_next is the nested chain's seg1 dir",
              outcome.get("base_for_next") == os.path.join(chain_run_root, "seg1"),
              "got %r" % outcome.get("base_for_next"))
        check("C12c frames harvested from seg1/frames only",
              len(outcome.get("frames") or []) == 9 and
              all(os.path.join(chain_run_root, "seg1", "frames") in p for p in outcome["frames"]),
              "got %r" % outcome.get("frames"))

        # mirror what main()'s follower branch does on an "ok" outcome
        chain_base_by_index[unit["index"]] = outcome["base_for_next"]
        check("C12d chain_base_by_index gets populated for the follower's own index",
              chain_base_by_index[3] == os.path.join(chain_run_root, "seg1"),
              "got %r" % chain_base_by_index)


def test_render_chain_follower_two_hop_uses_predecessor_seg1():
    """Group-size >= 3 case: panel 3 continues from panel 2, and panel 2 is
    ITSELF a follower -- so panel 3's --continue-from base must be panel 2's
    nested-chain seg1/ dir, never a <run_root>/panel-2 path (panel 2's own
    request.json/embeds.pt/frames/ were never written there)."""
    with tempfile.TemporaryDirectory() as tmp:
        opener_cell = _make_base_cell(tmp, "panel-1", num_frames=9)
        chain_run_root_2, stdout_2 = _canned_chain_run(tmp, "chain-2", num_frames=9)
        chain_run_root_3, stdout_3 = _canned_chain_run(tmp, "chain-3", num_frames=9)
        never_written_run_root_panel_2 = os.path.join(tmp, "run_root", "panel-2")

        real_subprocess = story_video.subprocess
        calls = []

        def fake_run(cmd, **kwargs):
            calls.append(cmd)
            stdout = stdout_2 if len(calls) == 1 else stdout_3
            return subprocess.CompletedProcess(args=cmd, returncode=0, stdout=stdout)

        story_video.subprocess = types.SimpleNamespace(
            run=fake_run, PIPE=subprocess.PIPE, STDOUT=subprocess.STDOUT)
        try:
            args = story_video.build_parser().parse_args(
                ["m.json", "o.mp4", "--mode", "per-panel", "--engine", "chain"])
            chain_base_by_index = {1: opener_cell}

            unit2 = {"index": 2, "label": "panel-2", "seed": 2, "prompt": "shot two",
                     "num_frames": 9, "conditions": [], "role": "follower", "group": 1,
                     "continue_from_index": 1}
            cell2 = os.path.join(tmp, "panel-2")
            outcome2 = story_video._render_chain_follower(args, unit2, cell2, chain_base_by_index)
            check("C12e panel-2 (follower of the opener) returns ok",
                  outcome2["status"] == "ok", "got %r" % outcome2)
            # mirror what main()'s follower branch does on an "ok" outcome
            chain_base_by_index[2] = outcome2["base_for_next"]

            unit3 = {"index": 3, "label": "panel-3", "seed": 3, "prompt": "shot three",
                     "num_frames": 9, "conditions": [], "role": "follower", "group": 1,
                     "continue_from_index": 2}
            cell3 = os.path.join(tmp, "panel-3")
            outcome3 = story_video._render_chain_follower(args, unit3, cell3, chain_base_by_index)
        finally:
            story_video.subprocess = real_subprocess

        check("C12f panel-3 nests exactly 2 subprocess calls (panel-2 then panel-3)",
              len(calls) == 2, "got %r" % len(calls))
        check("C12g panel-3's --continue-from argv is panel-2's seg1 dir, "
              "NOT <run_root>/panel-2",
              calls[1][calls[1].index("--continue-from") + 1] == os.path.join(chain_run_root_2, "seg1")
              and calls[1][calls[1].index("--continue-from") + 1] != never_written_run_root_panel_2,
              "got %r" % calls[1])
        check("C12h panel-3 returns ok",
              outcome3["status"] == "ok", "got %r" % outcome3)
        check("C12i panel-3's own base_for_next is ITS OWN nested chain's seg1 "
              "(not panel-2's)",
              outcome3.get("base_for_next") == os.path.join(chain_run_root_3, "seg1"),
              "got %r" % outcome3.get("base_for_next"))


# ---------------------------------------------------------------------------
# C12: source guard -- the retry pass branches on role before touching the
# in-process stage machinery, and a skipped_no_base follower becomes
# retry-eligible only once its base has completed
# ---------------------------------------------------------------------------

def test_ast_guard_retry_pass_follower_branch():
    with open(_VIDEO_PATH) as f:
        source = f.read()
    tree = ast.parse(source, filename=_VIDEO_PATH)
    calls = [n for n in ast.walk(tree)
             if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
             and n.func.id == "_render_chain_follower"]
    check("C12a _render_chain_follower is called from two places "
          "(main loop + retry pass)", len(calls) == 2, "got %r" % len(calls))
    check("C12b the retry pass still rmtree's frames/ only for in-process units",
          source.count('shutil.rmtree(os.path.join(cell, "frames"), ignore_errors=True)') == 1)
    check("C12c a retried follower records attempts=2",
          'result["attempts"] = 2' in source)


if __name__ == "__main__":
    test_panel_header_variants()
    test_multiline_body_joined()
    test_parse_prompts_md_prompt_label()
    test_parse_prompts_md_prompt_backcompat()
    test_narrative_extraction()
    test_glob_numeric_sort()
    test_glob_mtime_fallback()
    test_prompts_count_mismatch_exits_2()
    test_overwrite_protection()
    test_no_images_argument_rejections()
    test_no_images_manifest_shape_and_frames()
    test_no_images_panel_errors()
    test_video_parser_defaults()
    test_defaults_not_refused_geometry()
    test_build_units_per_panel()
    test_build_units_transitions()
    test_motion_prompt_override_and_fallback()
    test_transition_template_fallback()
    test_transitions_single_panel_rejected()
    test_load_manifest_rejects_index_gap()
    test_ast_guard_signal_and_restore()
    test_ast_guard_release_page_cache_in_loop()
    test_ast_guard_no_toplevel_heavy_imports()
    test_build_frame_sequence_ordering()
    test_ast_guard_order_safe_concat()
    test_ast_guard_release_page_cache_two_loops()
    test_ast_guard_retry_guard_references_content_blocked()
    test_snap_frames()
    test_allocate_frames_basic_envelope()
    test_allocate_frames_weighted_ordering()
    test_allocate_frames_infeasible_envelope_and_cli_rejects()
    test_allocate_frames_determinism()
    test_build_units_v2_per_panel_num_frames()
    test_build_units_v1_fallback_num_frames()
    test_build_units_transitions_v2_frame_index()
    test_load_manifest_rejects_bad_num_frames_v2()
    test_engine_flag_defaults_and_rejections()
    test_load_manifest_allow_null_image_path()
    test_build_units_chain_grouping()
    test_build_units_per_panel_has_no_chain_keys()
    test_chain_groups_descriptors()
    test_build_request_mode_field()
    test_chain_dry_run_output()
    test_per_panel_dry_run_unchanged()
    test_build_chain_follower_cmd()
    test_chain_run_root_parsing()
    test_ast_guard_chain_follower_invocation()
    test_ast_guard_follower_harvests_seg1_only()
    test_render_chain_follower_single_hop()
    test_render_chain_follower_two_hop_uses_predecessor_seg1()
    test_ast_guard_retry_pass_follower_branch()

    print("OK %d/%d" % (TOTAL - FAILED, TOTAL))
    sys.exit(0 if FAILED == 0 else 1)
