"""Plain-python (no pytest) offline tests for wan_video_skill.

Run: python3 tests/test_wan_video_skill_offline.py
Prints PASS/FAIL per case, then "OK n/n" and exits 0, or exits 1 on any
failure. No GPU/torch/diffusers work is performed...
"""

import os
import sys
import subprocess

sys.path.insert(0, "/Users/reubenpatterson/qwen-agent-workspace")

import wan_video_skill
import mps_guard

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


def T1():
    # Valid geometry should not raise
    try:
        wan_video_skill._validate_geometry(512, 512, 49)
        check("T1.1", True)
    except Exception as e:
        check("T1.1", False, "Unexpected exception %s" % e)

    # Width not divisible by 32
    try:
        wan_video_skill._validate_geometry(511, 512, 49)
        check("T1.2", False, "Expected ValueError")
    except ValueError as e:
        check("T1.2", "32" in str(e), "Message does not contain '32'")
    except Exception as e:
        check("T1.2", False, "Wrong exception type %s" % type(e))

    # Height not divisible by 32
    try:
        wan_video_skill._validate_geometry(512, 511, 49)
        check("T1.3", False, "Expected ValueError")
    except ValueError as e:
        check("T1.3", "32" in str(e), "Message does not contain '32'")
    except Exception as e:
        check("T1.3", False, "Wrong exception type %s" % type(e))

    # (num_frames - 1) % 4 != 0
    try:
        wan_video_skill._validate_geometry(512, 512, 50)
        check("T1.4", False, "Expected ValueError")
    except ValueError as e:
        check("T1.4", "4" in str(e), "Message does not contain '4'")
    except Exception as e:
        check("T1.4", False, "Wrong exception type %s" % type(e))


def T2():
    # Valid case
    try:
        wan_video_skill._check_ceiling(256, 256, 9, False)
        check("T2.1", True)
    except Exception as e:
        check("T2.1", False, "Unexpected exception %s" % e)

    # Frame count above the resolution's ceiling
    try:
        wan_video_skill._check_ceiling(256, 256, 13, False)
        check("T2.2", False, "Expected HostSafetyError")
    except mps_guard.HostSafetyError as e:
        check("T2.2", "9" in str(e), "Message does not contain '9'")
    except Exception as e:
        check("T2.2", False, "Wrong exception type %s" % type(e))

    # Resolution not in the table
    try:
        wan_video_skill._check_ceiling(704, 480, 49, False)
        check("T2.3", False, "Expected HostSafetyError")
    except mps_guard.HostSafetyError as e:
        check("T2.3", "256x256" in str(e), "Message does not contain '256x256'")
    except Exception as e:
        check("T2.3", False, "Wrong exception type %s" % type(e))

    # allow_override bypasses the check, even for an unlisted resolution
    try:
        wan_video_skill._check_ceiling(704, 480, 49, True)
        check("T2.4", True)
    except Exception as e:
        check("T2.4", False, "Unexpected exception %s" % e)


def T3():
    original_path = wan_video_skill.CEILING_TABLE_PATH
    try:
        wan_video_skill.CEILING_TABLE_PATH = "/nonexistent/wan_ceiling_does_not_exist.json"
        try:
            wan_video_skill._check_ceiling(512, 512, 49, False)
            check("T3.1", False, "Expected HostSafetyError due to missing table")
        except mps_guard.HostSafetyError:
            check("T3.1", True)
        except Exception as e:
            check("T3.1", False, "Wrong exception type %s" % type(e))
    finally:
        wan_video_skill.CEILING_TABLE_PATH = original_path


def T4():
    turbo_expected = {
        "model_id": "yetter-ai/Wan2.2-TI2V-5B-Turbo-Diffusers",
        "num_inference_steps": 4,
        "guidance_scale": 1.0,
        "negative_prompt": "",
    }
    base_expected = {
        "model_id": "Wan-AI/Wan2.2-TI2V-5B-Diffusers",
        "num_inference_steps": 50,
        "guidance_scale": 5.0,
        "negative_prompt": '色调艳丽，过曝，静态，细节模糊不清，字幕，风格，作品，画作，画面，静止，整体发灰，最差质量，低质量，JPEG压缩残留，丑陋的，残缺的，多余的手指，画得不好的手部，画得不好的脸部，畸形的，毁容的，形态畸形的肢体，手指融合，静止不动的画面，杂乱的背景，三条腿，背景人很多，倒着走',
    }
    check(
        "T4.1",
        wan_video_skill.MODEL_PRESETS.get("turbo") == turbo_expected,
        "turbo preset mismatch",
    )
    check(
        "T4.2",
        wan_video_skill.MODEL_PRESETS.get("base") == base_expected,
        "base preset mismatch",
    )


def T5():
    check("T5.1", wan_video_skill.FRACTION_STAGE1 == 0.40, "FRACTION_STAGE1 mismatch")
    check("T5.2", wan_video_skill.FRACTION_STAGE2 == 0.65, "FRACTION_STAGE2 mismatch")
    check("T5.3", wan_video_skill.FRACTION_STAGE3 == 0.65, "FRACTION_STAGE3 mismatch")
    check(
        "T5.4",
        wan_video_skill.MAX_SEQUENCE_LENGTH == 512,
        "MAX_SEQUENCE_LENGTH mismatch",
    )


def T6():
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import wan_video_skill; import sys; "
                "assert 'torch' not in sys.modules; "
                "assert 'diffusers' not in sys.modules; "
                "assert 'transformers' not in sys.modules; "
                "assert 'content_safety' not in sys.modules; "
                "print('OK')"
            ),
        ],
        cwd="/Users/reubenpatterson/qwen-agent-workspace",
        capture_output=True,
        text=True,
    )
    cond = result.returncode == 0 and "OK" in result.stdout
    check(
        "T6.1",
        cond,
        "Subprocess failed rc=%r, out=%r, err=%r" % (result.returncode, result.stdout, result.stderr),
    )


def T7():
    # T2V mode: generate_video(None, "") and generate_video(None, "   ") must
    # raise ValueError about an empty prompt, BEFORE any run dir is created
    # and BEFORE torch/diffusers are imported -- checked directly via a
    # module-level call (not a subprocess) so sys.modules reflects this
    # process's own imports.
    runs_dir = os.path.join(WORKSPACE, wan_video_skill.RUNS_SUBDIR)
    before = set(os.listdir(runs_dir)) if os.path.isdir(runs_dir) else set()

    try:
        wan_video_skill.generate_video(None, "")
        check("T7.1", False, "Expected ValueError")
    except ValueError as e:
        check("T7.1", "prompt" in str(e), "Message does not mention 'prompt'")
    except Exception as e:
        check("T7.1", False, "Wrong exception type %s" % type(e))

    try:
        wan_video_skill.generate_video(None, "   ")
        check("T7.2", False, "Expected ValueError")
    except ValueError as e:
        check("T7.2", "prompt" in str(e), "Message does not mention 'prompt'")
    except Exception as e:
        check("T7.2", False, "Wrong exception type %s" % type(e))

    check("T7.3", "torch" not in sys.modules, "torch was imported before prompt validation raised")
    check("T7.4", "diffusers" not in sys.modules, "diffusers was imported before prompt validation raised")

    after = set(os.listdir(runs_dir)) if os.path.isdir(runs_dir) else set()
    check("T7.5", before == after, "generate_video(None, ...) created a run dir before validating prompt")


def T8():
    # --t2v with no prompt/output at all: falls through to the
    # len(sys.argv) < 2 usage-and-exit path, which now mentions --t2v. No
    # run dir is created and no heavy imports happen.
    runs_dir = os.path.join(WORKSPACE, wan_video_skill.RUNS_SUBDIR)
    before = set(os.listdir(runs_dir)) if os.path.isdir(runs_dir) else set()

    result = subprocess.run(
        [sys.executable, "wan_video_skill.py", "--t2v"],
        cwd=WORKSPACE,
        capture_output=True,
        text=True,
    )
    cond = result.returncode == 1 and "--t2v" in result.stdout
    check("T8.1", cond, "rc=%r stdout=%r stderr=%r" % (result.returncode, result.stdout, result.stderr))

    after = set(os.listdir(runs_dir)) if os.path.isdir(runs_dir) else set()
    check("T8.2", before == after, "--t2v with no prompt created a run dir")


def T9():
    # --t2v wired through to generate_video(None, prompt, ...): an empty
    # prompt positional reaches the same ValueError as T7, proving the CLI
    # correctly threads image_path=None/prompt through, still with no run
    # dir and no torch/diffusers import (the traceback is the uncaught
    # ValueError, not an import error).
    runs_dir = os.path.join(WORKSPACE, wan_video_skill.RUNS_SUBDIR)
    before = set(os.listdir(runs_dir)) if os.path.isdir(runs_dir) else set()

    result = subprocess.run(
        [sys.executable, "wan_video_skill.py", "--t2v", ""],
        cwd=WORKSPACE,
        capture_output=True,
        text=True,
    )
    cond = (
        result.returncode != 0
        and "ValueError" in result.stderr
        and "prompt" in result.stderr
    )
    check("T9.1", cond, "rc=%r stdout=%r stderr=%r" % (result.returncode, result.stdout, result.stderr))

    after = set(os.listdir(runs_dir)) if os.path.isdir(runs_dir) else set()
    check("T9.2", before == after, "--t2v \"\" created a run dir before validating prompt")


if __name__ == "__main__":
    T1()
    T2()
    T3()
    T4()
    T5()
    T6()
    T7()
    T8()
    T9()
    print("OK %d/%d" % (TOTAL - FAILED, TOTAL))
    sys.exit(0 if FAILED == 0 else 1)
