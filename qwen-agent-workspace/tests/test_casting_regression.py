"""Byte-identical goldens for UNCAST runs (spec docs/superpowers/specs/
2026-10-05-character-library-design.md Section 9.7, B1-B3).

Capture once, before any production change, and commit the result:
    python3 tests/test_casting_regression.py --capture
Compare (every later run):
    python3 -m pytest tests/test_casting_regression.py

Normalization: the fixture image path becomes <IMAGE>, sys.executable becomes <PY>, the
workspace root becomes <WS> (replaced in that order), and the manifest's created_at is
removed.
"""

import contextlib
import importlib.machinery
import io
import json
import os
import subprocess
import sys
import tempfile

WS = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
sys.path.insert(0, WS)

import ltx2_mlx_video_skill as SKILL  # noqa: E402

story_manifest = importlib.machinery.SourceFileLoader(
    "ltx_story_manifest_casting_regression",
    os.path.join(WS, "bin", "ltx-story-manifest")).load_module()

FIXTURES = os.path.join(WS, "tests", "fixtures", "casting_baseline")
STORY_MD = os.path.join(FIXTURES, "story.md")
GOLDEN_B1 = os.path.join(FIXTURES, "ltx_movie_dry_run.txt")
GOLDEN_B2 = os.path.join(FIXTURES, "manifest.json")
GOLDEN_B3 = os.path.join(FIXTURES, "build_command.json")
MODEL_25 = "/Users/reubenpatterson/ltx-2-mlx/models/ltx-2.5-mlx-q8"


def _normalize(text, image=None):
    if image is not None:
        text = text.replace(image, "<IMAGE>")
    return text.replace(sys.executable, "<PY>").replace(WS, "<WS>")


def b1_text():
    proc = subprocess.run(
        [sys.executable, "bin/ltx-movie", "a test narrative", "--story-id",
         "casting-baseline-dry", "--dry-run", "--no-review", "--model", MODEL_25],
        cwd=WS, env=dict(os.environ, STORY_PIPELINE_LOGGED="1"), capture_output=True,
        text=True)
    assert proc.returncode == 0, proc.stderr
    return _normalize(proc.stdout)


def b2_text(tmpdir):
    from PIL import Image
    image = os.path.join(tmpdir, "panel_01.png")
    Image.new("RGB", (64, 64), (90, 90, 90)).save(image)
    saved = story_manifest.WS
    story_manifest.WS = tmpdir
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            rc = story_manifest.main([
                "--story-id", "casting-baseline-manifest", "--prompts-md", STORY_MD, "--chain",
                "--image", image, "--fps", "24", "--target-seconds", "18.125",
                "--min-frames", "145", "--max-frames", "145", "--force"])
    finally:
        story_manifest.WS = saved
    assert rc == 0
    path = os.path.join(tmpdir, "generated", "stories", "casting-baseline-manifest",
                        "manifest.json")
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    del data["created_at"]
    return _normalize(json.dumps(data, indent=2, ensure_ascii=False) + "\n", image=image)


def b3_text():
    saved = SKILL.LTX2_MLX_BIN
    SKILL.LTX2_MLX_BIN = "/bin/ltx"
    try:
        cmd = SKILL.build_command(prompt="p", output_path="/o.mp4", image_path="/i.png",
                                  width=704, height=448, num_frames=145, frame_rate=24, seed=1,
                                  model="M", gemma="G")
    finally:
        SKILL.LTX2_MLX_BIN = saved
    return _normalize(json.dumps(cmd, indent=2) + "\n")


def _read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def test_b1_ltx_movie_dry_run_is_unchanged():
    assert b1_text() == _read(GOLDEN_B1)


def test_b2_chain_manifest_is_unchanged(tmp_path):
    assert b2_text(str(tmp_path)) == _read(GOLDEN_B2)


def test_b3_build_command_is_unchanged():
    assert b3_text() == _read(GOLDEN_B3)


def capture():
    with tempfile.TemporaryDirectory() as tmpdir:
        texts = {GOLDEN_B1: b1_text(), GOLDEN_B2: b2_text(tmpdir), GOLDEN_B3: b3_text()}
    for path, text in texts.items():
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        print("wrote %s (%d bytes)" % (path, len(text.encode("utf-8"))))
    return 0


if __name__ == "__main__":
    if sys.argv[1:] != ["--capture"]:
        print("usage: python3 tests/test_casting_regression.py --capture "
              "(compare with: python3 -m pytest tests/test_casting_regression.py)",
              file=sys.stderr)
        sys.exit(2)
    sys.exit(capture())
