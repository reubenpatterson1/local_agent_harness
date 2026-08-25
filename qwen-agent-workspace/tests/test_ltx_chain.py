"""Plain-python (no pytest) offline tests for bin/ltx-chain.

Run: python3 tests/test_ltx_chain.py
Prints PASS/FAIL per case, then "OK n/n" and exits 0, or exits 1 on any
failure. No GPU/torch/diffusers work is performed, and ltx-chain's main()
is never run end-to-end (it spawns real stage subprocesses) -- only the
pure argument-parsing and per-segment helper pieces are exercised, plus a
single early-exit path (--segments 0) that returns before any subprocess
is spawned.
"""

import importlib.machinery
import os
import sys
import tempfile

sys.path.insert(0, "/Users/reubenpatterson/qwen-agent-workspace")

_CHAIN_PATH = "/Users/reubenpatterson/qwen-agent-workspace/bin/ltx-chain"
chain = importlib.machinery.SourceFileLoader("ltx_chain", _CHAIN_PATH).load_module()

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
# argparse defaults
# ---------------------------------------------------------------------------

def test_argparse_defaults():
    args = chain.build_parser().parse_args(["img.png", "a prompt", "out.mp4"])
    check("T1 default segments == 3", args.segments == 3, "got %r" % args.segments)
    check("T2 default width == 704", args.width == 704, "got %r" % args.width)
    check("T3 default height == 480", args.height == 480, "got %r" % args.height)
    check("T4 default fps == 24", args.fps == 24, "got %r" % args.fps)
    check("T5 default frame_rate == 24", args.frame_rate == 24, "got %r" % args.frame_rate)
    check("T6 default seed == 0", args.seed == 0, "got %r" % args.seed)
    check("T7 wide is bool False", args.wide is False, "got %r" % args.wide)
    check("T8 allow_override is bool False", args.allow_override is False, "got %r" % args.allow_override)
    check("T9 relax_supply is bool False", args.relax_supply is False, "got %r" % args.relax_supply)
    check("T10 no_prep is bool False", args.no_prep is False, "got %r" % args.no_prep)
    check("T11 keep_down is bool False", args.keep_down is False, "got %r" % args.keep_down)
    check("T12 force is bool False", args.force is False, "got %r" % args.force)
    check(
        "T13 default negative_prompt matches skill default",
        args.negative_prompt == chain.L.DEFAULT_NEGATIVE_PROMPT,
        "got %r" % args.negative_prompt,
    )


# ---------------------------------------------------------------------------
# argparse builds the expected namespace for a representative argv
# ---------------------------------------------------------------------------

def test_argparse_representative():
    args = chain.build_parser().parse_args([
        "img.png", "a dance routine", "out.mp4",
        "--segments", "5",
        "--width", "512",
        "--height", "512",
        "--seed", "7",
        "--wide",
        "--allow-override",
        "--relax-supply",
    ])
    check("T14 image_path", args.image_path == "img.png", "got %r" % args.image_path)
    check("T15 prompt", args.prompt == "a dance routine", "got %r" % args.prompt)
    check("T16 output_path", args.output_path == "out.mp4", "got %r" % args.output_path)
    check("T17 segments == 5", args.segments == 5, "got %r" % args.segments)
    check("T18 width == 512", args.width == 512, "got %r" % args.width)
    check("T19 height == 512", args.height == 512, "got %r" % args.height)
    check("T20 seed == 7", args.seed == 7, "got %r" % args.seed)
    check("T21 wide is True", args.wide is True, "got %r" % args.wide)
    check("T22 allow_override is True", args.allow_override is True, "got %r" % args.allow_override)
    check("T23 relax_supply is True", args.relax_supply is True, "got %r" % args.relax_supply)


# ---------------------------------------------------------------------------
# per-segment seed rule: segment i uses seed S+i
# ---------------------------------------------------------------------------

def test_segment_seed():
    check("T24 seed(0,1) == 1", chain._segment_seed(0, 1) == 1)
    check("T25 seed(0,3) == 3", chain._segment_seed(0, 3) == 3)
    check("T26 seed(5,1) == 6", chain._segment_seed(5, 1) == 6)
    check("T27 seed(5,3) == 8", chain._segment_seed(5, 3) == 8)


# ---------------------------------------------------------------------------
# --segments 0 is rejected
# ---------------------------------------------------------------------------

def test_segments_zero_rejected():
    with tempfile.TemporaryDirectory() as tmp:
        image_path = os.path.join(tmp, "fake.png")
        with open(image_path, "wb") as f:
            f.write(b"not a real png, just needs to exist")
        output_path = os.path.join(tmp, "out.mp4")

        argv = [image_path, "a prompt", output_path, "--segments", "0", "--no-prep"]
        exit_code = None
        try:
            chain.main(argv)
        except SystemExit as e:
            exit_code = e.code
        check(
            "T28 --segments 0 raises SystemExit(2) before any subprocess is spawned",
            exit_code == 2,
            "got exit_code=%r" % exit_code,
        )


# ---------------------------------------------------------------------------
# _segment_image: which image conditions segment i
# ---------------------------------------------------------------------------

def test_segment_image():
    input_image = "/x/input.png"
    prev_last = "/x/seg1/frames/frame_00048.png"
    check(
        "T29 segment 1 conditions on the input image",
        chain._segment_image(1, input_image, prev_last) == input_image,
    )
    check(
        "T30 segment 2 conditions on the previous segment's last frame",
        chain._segment_image(2, input_image, prev_last) == prev_last,
    )
    check(
        "T31 segment 3 conditions on the previous segment's last frame",
        chain._segment_image(3, input_image, prev_last) == prev_last,
    )


# ---------------------------------------------------------------------------
# --continue-from: argparse default and representative parsing
# ---------------------------------------------------------------------------

def test_continue_from_argparse():
    args = chain.build_parser().parse_args(["img.png", "a prompt", "out.mp4"])
    check("T32 continue_from default is None", args.continue_from is None,
          "got %r" % args.continue_from)

    args = chain.build_parser().parse_args([
        "img.png", "a prompt", "out.mp4",
        "--continue-from", "/x/generated/ltx_runs/20260101T000000Z-abcd1234",
    ])
    check(
        "T33 continue_from parses to the given path",
        args.continue_from == "/x/generated/ltx_runs/20260101T000000Z-abcd1234",
        "got %r" % args.continue_from,
    )


# ---------------------------------------------------------------------------
# _continue_settings_mismatch: pure settings-match check against a
# --continue-from base run's request.json
# ---------------------------------------------------------------------------

def _make_args(**overrides):
    argv = ["img.png", "a prompt", "out.mp4"]
    args = chain.build_parser().parse_args(argv)
    for key, value in overrides.items():
        setattr(args, key, value)
    return args


def _matching_base_request():
    args = _make_args(prompt="a prompt")
    return {
        "prompt": args.prompt,
        "negative_prompt": args.negative_prompt,
        "width": args.width,
        "height": args.height,
        "num_frames": args.num_frames,
        "fps": args.fps,
        "frame_rate": args.frame_rate,
        "wide": args.wide,
        "seed": args.seed,
    }


def test_continue_settings_mismatch():
    args = _make_args(prompt="a prompt")
    base_request = _matching_base_request()
    check(
        "T34 matching settings -> None",
        chain._continue_settings_mismatch(base_request, args) is None,
    )

    mismatched_args = _make_args(prompt="a prompt", width=999)
    result = chain._continue_settings_mismatch(base_request, mismatched_args)
    check(
        "T35 width mismatch names the field and both values",
        result is not None and "width" in result and "999" in result
        and str(base_request["width"]) in result,
        "got %r" % result,
    )

    mismatched_seed = _make_args(prompt="a prompt", seed=42)
    result2 = chain._continue_settings_mismatch(base_request, mismatched_seed)
    check(
        "T36 seed mismatch names the field",
        result2 is not None and "seed" in result2,
        "got %r" % result2,
    )


if __name__ == "__main__":
    test_argparse_defaults()
    test_argparse_representative()
    test_segment_seed()
    test_segments_zero_rejected()
    test_segment_image()
    test_continue_from_argparse()
    test_continue_settings_mismatch()

    print("OK %d/%d" % (TOTAL - FAILED, TOTAL))
    sys.exit(0 if FAILED == 0 else 1)
