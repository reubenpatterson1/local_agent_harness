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
import sys
import tempfile

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

    print("OK %d/%d" % (TOTAL - FAILED, TOTAL))
    sys.exit(0 if FAILED == 0 else 1)
