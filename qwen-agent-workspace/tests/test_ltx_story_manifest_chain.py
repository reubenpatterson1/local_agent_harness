"""Plain-python (no pytest) offline tests for bin/ltx-story-manifest --chain
(manifest schema_version 3), plus the guarantee that --glob / --image / --no-images
still write schema_version 2 with no "conditioning" key.

Run: python3 tests/test_ltx_story_manifest_chain.py
Every case writes to generated/stories/<a throwaway story id>/ and removes it.
"""

import contextlib
import importlib.machinery
import io
import json
import os
import re
import shutil
import sys
import tempfile

WS = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
sys.path.insert(0, WS)

_MANIFEST_PATH = os.path.join(WS, "bin", "ltx-story-manifest")
story_manifest = importlib.machinery.SourceFileLoader(
    "ltx_story_manifest_chain_test", _MANIFEST_PATH).load_module()

TOTAL = 0
FAILED = 0

_V2_PANEL_KEYS = {"index", "image_path", "title", "panel_text", "narration", "narration_words",
                  "num_frames", "duration_s", "motion_prompt", "transition_to_next"}


def check(name, condition, detail=""):
    global TOTAL, FAILED
    TOTAL += 1
    if condition:
        print("PASS %s" % name)
    else:
        FAILED += 1
        print("FAIL %s %s" % (name, detail))


def _png(path, size=(64, 64)):
    from PIL import Image
    Image.new("RGB", size, (10, 20, 30)).save(path, format="PNG")
    return path


def _story(td, panels, name="story.md"):
    """panels: one dict per panel mapping label -> text, for the labels Image, Motion,
    Narration and Prompt (written in that order)."""
    lines = ["# Story", "", "a narrative", ""]
    for i, fields in enumerate(panels, start=1):
        lines.append("## Panel %d — Title %d" % (i, i))
        for label in ("Image", "Motion", "Narration", "Prompt"):
            if label in fields:
                lines.append("%s: %s" % (label, fields[label]))
        lines.append("")
    path = os.path.join(td, name)
    with open(path, "w") as f:
        f.write("\n".join(lines))
    return path


def _run(argv):
    """main(argv) with stdout/stderr captured. parser.error's SystemExit becomes rc."""
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            rc = story_manifest.main(argv)
        except SystemExit as e:
            rc = e.code
    return rc, out.getvalue(), err.getvalue()


def _sid(tag):
    return "_test_manifest_chain_%s_%d" % (tag, os.getpid())


def _manifest_path(story_id):
    return os.path.join(WS, "generated", "stories", story_id, "manifest.json")


def _load(story_id):
    with open(_manifest_path(story_id)) as f:
        return json.load(f)


def _cleanup(story_id):
    shutil.rmtree(os.path.join(WS, "generated", "stories", story_id), ignore_errors=True)


def _frame_args(n):
    return ["--fps", "24", "--target-seconds", str(n * 145 / 24.0),
            "--min-frames", "145", "--max-frames", "145", "--force"]


_THREE = [{"Image": "the opening frame", "Motion": "she turns", "Narration": "One."},
          {"Motion": "she walks to the door", "Narration": "Two."},
          {"Motion": "she opens it", "Narration": "Three."}]

# Golden text for test_v2_golden_byte_identical: the full manifest.json text
# written by --image (non-chain, schema_version 2) for a fixed two-panel input,
# with the only run-varying fields (story_id, created_at, the tempdir prefix of
# image_path) masked to fixed placeholders. A field-by-field check (like C7a/b/c)
# would miss a regression that swaps panel_text/motion_prompt, reorders keys, or
# drops a fallback value; this full-text compare catches all of those.
_V2_GOLDEN = """{
  "schema_version": 2,
  "story_id": "STORY_ID",
  "title": "",
  "narrative": "a narrative",
  "created_at": "TIMESTAMP",
  "fps": 24,
  "target_seconds": 12.083333333333334,
  "pace": "proportional",
  "total_num_frames": 290,
  "total_duration_s": 12.083,
  "panels": [
    {
      "index": 1,
      "image_path": "TMPDIR/panel_01.png",
      "title": "Title 1",
      "panel_text": "i1",
      "narration": "n1",
      "narration_words": 1,
      "num_frames": 145,
      "duration_s": 6.042,
      "motion_prompt": "m1",
      "transition_to_next": null
    },
    {
      "index": 2,
      "image_path": "TMPDIR/panel_02.png",
      "title": "Title 2",
      "panel_text": "i2",
      "narration": "n2",
      "narration_words": 1,
      "num_frames": 145,
      "duration_s": 6.042,
      "motion_prompt": "m2",
      "transition_to_next": null
    }
  ]
}"""


def test_chain_three_panels():
    sid = _sid("three")
    try:
        with tempfile.TemporaryDirectory() as td:
            still = _png(os.path.join(td, "panel_01.png"))
            md = _story(td, _THREE)
            rc, out, err = _run(["--story-id", sid, "--prompts-md", md, "--chain",
                                 "--image", still] + _frame_args(3))
            check("C1a rc 0", rc == 0, "rc=%r err=%r" % (rc, err))
            m = _load(sid)
            p = m["panels"]
            check("C1b schema_version 3", m["schema_version"] == 3, "got %r" % m["schema_version"])
            check("C1c conditioning still/chain/chain",
                  [x.get("conditioning") for x in p] == ["still", "chain", "chain"],
                  "got %r" % [x.get("conditioning") for x in p])
            check("C1d panel 1 image_path is the absolute still",
                  p[0]["image_path"] == os.path.abspath(still), "got %r" % p[0]["image_path"])
            check("C1e panel 1 panel_text is Image:, motion_prompt is Motion:",
                  p[0]["panel_text"] == "the opening frame" and p[0]["motion_prompt"] == "she turns",
                  "got %r" % p[0])
            check("C1f panels 2-3 carry panel_text == motion_prompt == Motion:",
                  [(x["panel_text"], x["motion_prompt"]) for x in p[1:]]
                  == [("she walks to the door", "she walks to the door"),
                      ("she opens it", "she opens it")], "got %r" % p[1:])
            check("C1g panels 2-3 have image_path None",
                  all(x["image_path"] is None for x in p[1:]))
            check("C1h narration is carried", [x["narration"] for x in p] == ["One.", "Two.", "Three."])
            check("C1i every panel is 145 frames", [x["num_frames"] for x in p] == [145, 145, 145])
            check("C1j the summary table marks chained panels",
                  out.count("(chained)") == 2 and "panel_01.png" in out, "got %r" % out)
            check("C1k a v3 panel is the v2 key set plus conditioning",
                  all(set(x) == _V2_PANEL_KEYS | {"conditioning"} for x in p))
    finally:
        _cleanup(sid)


def test_chain_argument_errors():
    sid = _sid("argerr")
    try:
        with tempfile.TemporaryDirectory() as td:
            still = _png(os.path.join(td, "panel_01.png"))
            md = _story(td, _THREE)
            cases = (
                ("C2a --chain + --no-images",
                 ["--prompts-md", md, "--chain", "--image", still, "--no-images"],
                 "--chain is mutually exclusive with --glob and --no-images"),
                ("C2b --chain + --glob",
                 ["--prompts-md", md, "--chain", "--glob", "panel_*.png", "--images-dir", td],
                 "--chain is mutually exclusive with --glob and --no-images"),
                ("C2c --chain without --prompts-md", ["--chain", "--image", still],
                 "--chain requires --prompts-md"),
                ("C2d --chain with no --image", ["--prompts-md", md, "--chain"],
                 "--chain requires exactly one --image (panel 1's still)"),
                ("C2e --chain with two --image",
                 ["--prompts-md", md, "--chain", "--image", still, "--image", still],
                 "--chain requires exactly one --image (panel 1's still)"),
            )
            for label, extra, message in cases:
                rc, out, err = _run(["--story-id", sid] + extra + _frame_args(3))
                check("%s exits 2 with %r" % (label, message), rc == 2 and message in err,
                      "rc=%r err=%r" % (rc, err))
            check("C2f no manifest was written by any of them",
                  not os.path.exists(_manifest_path(sid)))
    finally:
        _cleanup(sid)


def test_chain_content_errors():
    sid = _sid("content")
    try:
        with tempfile.TemporaryDirectory() as td:
            still = _png(os.path.join(td, "panel_01.png"))
            cases = (
                ("C3a zero panels", [],
                 "Error: --chain requires --prompts-md to contain at least one panel section; found 0"),
                ("C3b panel 1 without Image:",
                 [{"Motion": "m", "Narration": "n"}],
                 "Error: --chain requires panel 1 to have a non-empty Image: field"),
                ("C3c panel 2 without Motion:",
                 [{"Image": "i", "Motion": "m", "Narration": "n"}, {"Narration": "n2"}],
                 "Error: --chain requires every panel to have a non-empty Motion: field; panel 2 has none"),
                ("C3d panel 2 with Prompt:",
                 [{"Image": "i", "Motion": "m", "Narration": "n"},
                  {"Motion": "m2", "Narration": "n2", "Prompt": "p"}],
                 "Error: --chain does not accept Prompt: fields; panel 2 has one"),
            )
            for n, (label, panels, message) in enumerate(cases):
                md = _story(td, panels, name="story_%d.md" % n)
                rc, out, err = _run(["--story-id", sid, "--prompts-md", md, "--chain",
                                     "--image", still] + _frame_args(max(1, len(panels))))
                check("%s exits 2 with the spec message" % label, rc == 2 and message in err,
                      "rc=%r err=%r" % (rc, err))
    finally:
        _cleanup(sid)


def test_chain_panel2_image_warning():
    sid = _sid("warn")
    try:
        with tempfile.TemporaryDirectory() as td:
            still = _png(os.path.join(td, "panel_01.png"))
            md = _story(td, [{"Image": "i1", "Motion": "m1", "Narration": "n1"},
                             {"Image": "an old-format picture", "Motion": "m2", "Narration": "n2"}])
            rc, out, err = _run(["--story-id", sid, "--prompts-md", md, "--chain",
                                 "--image", still] + _frame_args(2))
            check("C4a a panel-2 Image: is a warning, not an error", rc == 0, "rc=%r err=%r" % (rc, err))
            check("C4b the warning text is the spec text",
                  "WARNING: panel 2 has an Image: field; --chain ignores it (the panel continues "
                  "from the previous clip's last frame)" in out, "got %r" % out)
            p = _load(sid)["panels"]
            check("C4c panel 2's Image: text is ignored (panel_text is its Motion:)",
                  p[1]["panel_text"] == "m2" and p[1]["image_path"] is None, "got %r" % p[1])
    finally:
        _cleanup(sid)


def test_chain_single_panel():
    sid = _sid("single")
    try:
        with tempfile.TemporaryDirectory() as td:
            still = _png(os.path.join(td, "panel_01.png"))
            md = _story(td, _THREE[:1])
            rc, out, err = _run(["--story-id", sid, "--prompts-md", md, "--chain",
                                 "--image", still] + _frame_args(1))
            m = _load(sid) if rc == 0 else {}
            check("C5 a one-panel --chain story is a v3 manifest with a single still panel",
                  rc == 0 and m.get("schema_version") == 3
                  and [x["conditioning"] for x in m["panels"]] == ["still"],
                  "rc=%r err=%r m=%r" % (rc, err, m))
    finally:
        _cleanup(sid)


def test_chain_length_warning_uses_motion():
    sid = _sid("length")
    try:
        with tempfile.TemporaryDirectory() as td:
            still = _png(os.path.join(td, "panel_01.png"))
            md = _story(td, [{"Image": " ".join(["word"] * 200), "Motion": "she turns",
                              "Narration": "n1"},
                             {"Motion": " ".join(["step"] * 160), "Narration": "n2"}])
            rc, out, err = _run(["--story-id", sid, "--prompts-md", md, "--chain",
                                 "--image", still] + _frame_args(2))
            check("C6a a long panel-1 Image: does not warn (the video model receives Motion:)",
                  rc == 0 and "WARNING: unit 1 prompt" not in out, "got %r" % out)
            check("C6b a long panel-2 Motion: does warn",
                  "WARNING: unit 2 prompt is 160 words" in out, "got %r" % out)
    finally:
        _cleanup(sid)


def test_v2_modes_unchanged():
    sid = _sid("v2")
    try:
        with tempfile.TemporaryDirectory() as td:
            imgs = os.path.join(td, "images")
            os.makedirs(imgs)
            a = _png(os.path.join(imgs, "panel_01.png"))
            b = _png(os.path.join(imgs, "panel_02.png"))
            md = _story(td, [{"Image": "i1", "Motion": "m1", "Narration": "n1"},
                             {"Image": "i2", "Motion": "m2", "Narration": "n2"}])
            rc, out, err = _run(["--story-id", sid, "--prompts-md", md, "--glob", "panel_*.png",
                                 "--images-dir", imgs] + _frame_args(2))
            m = _load(sid) if rc == 0 else {}
            check("C7a --glob still writes schema_version 2 with the exact v2 panel keys",
                  rc == 0 and m.get("schema_version") == 2
                  and all(set(x) == _V2_PANEL_KEYS for x in m["panels"]),
                  "rc=%r err=%r" % (rc, err))
            rc, out, err = _run(["--story-id", sid, "--prompts-md", md, "--image", a,
                                 "--image", b] + _frame_args(2))
            m = _load(sid) if rc == 0 else {}
            check("C7b --image without --chain still writes schema_version 2, no conditioning",
                  rc == 0 and m.get("schema_version") == 2
                  and not any("conditioning" in x for x in m["panels"]),
                  "rc=%r err=%r" % (rc, err))
            nost = _story(td, [{"Prompt": "p1", "Narration": "n1"}], name="nost.md")
            rc, out, err = _run(["--story-id", sid, "--prompts-md", nost, "--no-images"]
                                + _frame_args(1))
            m = _load(sid) if rc == 0 else {}
            check("C7c --no-images still writes schema_version 2, no conditioning",
                  rc == 0 and m.get("schema_version") == 2
                  and not any("conditioning" in x for x in m["panels"]),
                  "rc=%r err=%r" % (rc, err))
    finally:
        _cleanup(sid)


def test_v2_golden_byte_identical():
    """Regression lock (not covered by C7a/b/c): --image (non-chain) writes a v2
    manifest whose full JSON text, after masking story_id/created_at/the tempdir
    prefix of image_path, is byte-for-byte identical to a checked-in golden
    string. Manually verified this catches a real regression: with the v2 branch
    of the panel-assembly loop mutated to swap panel_text and motion_prompt
    (panel_text = pt["motion"] or ("panel %d" % i); motion_prompt = pt["image"] or
    None), this test failed (C8b) while C7a/b/c still passed unchanged -- the
    mutation was reverted afterward."""
    sid = _sid("golden")
    try:
        with tempfile.TemporaryDirectory() as td:
            a = _png(os.path.join(td, "panel_01.png"))
            b = _png(os.path.join(td, "panel_02.png"))
            md = _story(td, [{"Image": "i1", "Motion": "m1", "Narration": "n1"},
                             {"Image": "i2", "Motion": "m2", "Narration": "n2"}])
            rc, out, err = _run(["--story-id", sid, "--prompts-md", md, "--image", a,
                                 "--image", b] + _frame_args(2))
            check("C8a rc 0", rc == 0, "rc=%r err=%r" % (rc, err))
            with open(_manifest_path(sid)) as f:
                text = f.read()
            masked = text.replace(sid, "STORY_ID").replace(td, "TMPDIR")
            masked = re.sub(r'"created_at": "[^"]*"', '"created_at": "TIMESTAMP"', masked)
            check("C8b full v2 manifest.json text is byte-for-byte the checked-in "
                  "golden (after masking story_id/created_at/tmpdir)",
                  masked == _V2_GOLDEN, "got %r" % masked)
    finally:
        _cleanup(sid)


if __name__ == "__main__":
    test_chain_three_panels()
    test_chain_argument_errors()
    test_chain_content_errors()
    test_chain_panel2_image_warning()
    test_chain_single_panel()
    test_chain_length_warning_uses_motion()
    test_v2_modes_unchanged()
    test_v2_golden_byte_identical()

    print("OK %d/%d" % (TOTAL - FAILED, TOTAL))
    sys.exit(0 if FAILED == 0 else 1)
