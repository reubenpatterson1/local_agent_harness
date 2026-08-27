"""Plain-python (no pytest) offline tests for the LTX-Video text-to-video
(T2V, no conditioning image) addition to ltx_video_skill.py.

Run: python3 tests/test_ltx_t2v_offline.py
Prints PASS/FAIL per case, then "OK n/n" and exits 0, or exits 1 on any
failure. No GPU/torch/diffusers work is performed.

generate_video() spawns real subprocess stages (stage1/2/3), so -- same
policy as tests/test_ltx_multiframe.py's own T27-T30 -- it is never driven
end-to-end here. Every case below either raises before any run dir is
created / any subprocess is spawned, or is a source-level proof (via
inspect.getsource) of a specific, load-bearing line.
"""

import inspect
import os
import subprocess
import sys

sys.path.insert(0, "/Users/reubenpatterson/qwen-agent-workspace")

import ltx_video_skill  # noqa: E402

WORKSPACE = "/Users/reubenpatterson/qwen-agent-workspace"

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


def _runs_dir_snapshot():
    runs_dir = os.path.join(WORKSPACE, ltx_video_skill.RUNS_SUBDIR)
    return set(os.listdir(runs_dir)) if os.path.isdir(runs_dir) else set()


# ---------------------------------------------------------------------------
# generate_video(None, ...) -- empty prompt refusal (mirrors wan_video_skill's
# equivalent T2V test). Must fail before any run dir creation or torch import.
# ---------------------------------------------------------------------------

def test_empty_prompt_raises():
    before = _runs_dir_snapshot()

    try:
        ltx_video_skill.generate_video(None, "")
        check("T1.1 generate_video(None, '') raises ValueError", False, "no exception raised")
    except ValueError as e:
        check("T1.1 generate_video(None, '') raises ValueError", "prompt" in str(e), str(e))
    except Exception as e:
        check("T1.1 generate_video(None, '') raises ValueError", False, "wrong type %s" % type(e))

    try:
        ltx_video_skill.generate_video(None, "   ")
        check("T1.2 generate_video(None, '   ') raises ValueError", False, "no exception raised")
    except ValueError as e:
        check("T1.2 generate_video(None, '   ') raises ValueError", "prompt" in str(e), str(e))
    except Exception as e:
        check("T1.2 generate_video(None, '   ') raises ValueError", False, "wrong type %s" % type(e))

    check("T1.3 torch not imported by the empty-prompt check", "torch" not in sys.modules)
    check("T1.4 diffusers not imported by the empty-prompt check", "diffusers" not in sys.modules)

    after = _runs_dir_snapshot()
    check("T1.5 no run dir created", before == after, "before=%r after=%r" % (before, after))


# ---------------------------------------------------------------------------
# generate_video(None, "<prompt>", last_frame_path=...) / keyframes=[...] --
# refused: no conditioning images at all are supported in T2V mode.
# ---------------------------------------------------------------------------

def test_last_frame_and_keyframes_refused():
    before = _runs_dir_snapshot()

    try:
        ltx_video_skill.generate_video(None, "a prompt", last_frame_path="/x/last.png")
        check("T2.1 last_frame_path refused when image_path is None", False, "no exception raised")
    except ValueError as e:
        check(
            "T2.1 last_frame_path refused when image_path is None",
            "last_frame_path" in str(e) or "keyframes" in str(e),
            str(e),
        )
    except Exception as e:
        check("T2.1 last_frame_path refused when image_path is None", False, "wrong type %s" % type(e))

    try:
        ltx_video_skill.generate_video(
            None, "a prompt", keyframes=[{"image_path": "/x/kf.png", "frame_index": 16}]
        )
        check("T2.2 keyframes refused when image_path is None", False, "no exception raised")
    except ValueError as e:
        check(
            "T2.2 keyframes refused when image_path is None",
            "last_frame_path" in str(e) or "keyframes" in str(e),
            str(e),
        )
    except Exception as e:
        check("T2.2 keyframes refused when image_path is None", False, "wrong type %s" % type(e))

    after = _runs_dir_snapshot()
    check("T2.3 no run dir created", before == after, "before=%r after=%r" % (before, after))


# ---------------------------------------------------------------------------
# Source-level proof that stage 2 passes conditions=None (never an empty
# list) for t2v, and leaves the i2v conditions=[...] construction unchanged.
# conditions=[] would crash inside LTXConditionPipeline.__call__ (an empty
# `image`/`video` list makes is_conditioning_image_or_video True, while
# prepare_latents still sets conditioning_mask=None, so the denoising loop's
# `1 - conditioning_mask` raises TypeError) -- see the comment this mirrors
# in ltx_video_skill.py's _stage2_denoise.
# ---------------------------------------------------------------------------

def test_stage2_t2v_uses_conditions_none():
    src = inspect.getsource(ltx_video_skill._stage2_denoise)

    check(
        "T3.1 _stage2_denoise branches on request mode",
        'mode = request.get("mode", "i2v")' in src,
        "source:\n%s" % src,
    )
    check(
        "T3.2 t2v branch passes conditions=None (not an empty list)",
        "conditions=None," in src,
        "source:\n%s" % src,
    )
    check(
        "T3.3 i2v branch's conditions=[LTXVideoCondition(...)] construction is unchanged",
        "conditions=[\n                    LTXVideoCondition(" in src,
        "source:\n%s" % src,
    )


# ---------------------------------------------------------------------------
# Source-level proof that a fresh request.json records mode/image_path
# correctly for both branches.
# ---------------------------------------------------------------------------

def test_generate_video_request_has_mode():
    src = inspect.getsource(ltx_video_skill.generate_video)
    check(
        "T4.1 request.json mode field derived from image_path",
        '"mode": "t2v" if image_path is None else "i2v"' in src,
        "source:\n%s" % src,
    )
    check(
        "T4.2 request.json image_path is None for t2v",
        '"image_path": None if image_path is None else conditions[0]["image_path"]' in src,
        "source:\n%s" % src,
    )


# ---------------------------------------------------------------------------
# --t2v CLI wiring (help-level / no-generation checks, via subprocess so the
# real __main__ argument parsing runs, same style as test_ltx_chain.py).
# ---------------------------------------------------------------------------

def test_cli_t2v_no_prompt_prints_usage():
    before = _runs_dir_snapshot()
    result = subprocess.run(
        [sys.executable, "ltx_video_skill.py", "--t2v"],
        cwd=WORKSPACE,
        capture_output=True,
        text=True,
    )
    cond = result.returncode == 1 and "--t2v" in result.stdout
    check(
        "T5.1 --t2v with no prompt prints USAGE mentioning --t2v and exits 1",
        cond,
        "rc=%r stdout=%r stderr=%r" % (result.returncode, result.stdout, result.stderr),
    )
    after = _runs_dir_snapshot()
    check("T5.2 no run dir created", before == after, "before=%r after=%r" % (before, after))


def test_cli_t2v_empty_prompt_raises():
    before = _runs_dir_snapshot()
    result = subprocess.run(
        [sys.executable, "ltx_video_skill.py", "--t2v", ""],
        cwd=WORKSPACE,
        capture_output=True,
        text=True,
    )
    cond = (
        result.returncode != 0
        and "ValueError" in result.stderr
        and "prompt" in result.stderr
    )
    check(
        "T6.1 --t2v \"\" reaches generate_video(None, \"\", ...) and raises ValueError",
        cond,
        "rc=%r stdout=%r stderr=%r" % (result.returncode, result.stdout, result.stderr),
    )
    after = _runs_dir_snapshot()
    check("T6.2 no run dir created", before == after, "before=%r after=%r" % (before, after))


if __name__ == "__main__":
    test_empty_prompt_raises()
    test_last_frame_and_keyframes_refused()
    test_stage2_t2v_uses_conditions_none()
    test_generate_video_request_has_mode()
    test_cli_t2v_no_prompt_prints_usage()
    test_cli_t2v_empty_prompt_raises()
    print("OK %d/%d" % (TOTAL - FAILED, TOTAL))
    sys.exit(0 if FAILED == 0 else 1)
