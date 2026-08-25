"""Plain-python (no pytest) offline tests for the LTX-Video multi-frame
conditioning + ceiling-gate additions to ltx_video_skill.py.

Run: python3 tests/test_ltx_multiframe.py
Prints PASS/FAIL per case, then "OK n/n" and exits 0, or exits 1 on any
failure. No GPU/torch/diffusers work is performed.
"""

import inspect
import json
import os
import sys
import tempfile

sys.path.insert(0, "/Users/reubenpatterson/qwen-agent-workspace")

import ltx_video_skill  # noqa: E402
import mps_guard  # noqa: E402

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
# _normalized_conditions -- back-compat (acceptance check 2)
# ---------------------------------------------------------------------------

def test_normalized_conditions():
    legacy = {"image_path": "/x/a.png"}
    got = ltx_video_skill._normalized_conditions(legacy)
    check(
        "T1 back-compat: legacy request synthesizes a single frame-0 condition",
        got == [{"image_path": "/x/a.png", "frame_index": 0, "strength": 1.0}],
        "got %r" % got,
    )
    check("T2 back-compat: legacy request is not mutated", "conditions" not in legacy, "got %r" % legacy)

    with_conditions = {
        "image_path": "/x/a.png",
        "conditions": [
            {"image_path": "/x/a.png", "frame_index": 0, "strength": 1.0},
            {"image_path": "/x/b.png", "frame_index": 48, "strength": 1.0},
        ],
    }
    got2 = ltx_video_skill._normalized_conditions(with_conditions)
    check(
        "T3 a request with conditions returns it verbatim",
        got2 == with_conditions["conditions"],
        "got %r" % got2,
    )


# ---------------------------------------------------------------------------
# _parse_keyframe_spec (acceptance check 3)
# ---------------------------------------------------------------------------

def test_parse_keyframe_spec():
    got = ltx_video_skill._parse_keyframe_spec("a/b.png:16")
    check(
        "T4 PATH:INDEX",
        got == {"image_path": "a/b.png", "frame_index": 16, "strength": 1.0},
        "got %r" % got,
    )

    got = ltx_video_skill._parse_keyframe_spec("a/b.png:16:0.7")
    check(
        "T5 PATH:INDEX:STRENGTH",
        got == {"image_path": "a/b.png", "frame_index": 16, "strength": 0.7},
        "got %r" % got,
    )

    got = ltx_video_skill._parse_keyframe_spec("x:y/z.png:16:0.7")
    check(
        "T6 PATH containing ':' is preserved",
        got == {"image_path": "x:y/z.png", "frame_index": 16, "strength": 0.7},
        "got %r" % got,
    )

    try:
        ltx_video_skill._parse_keyframe_spec("bad")
        check("T7 malformed spec raises ValueError", False, "did not raise")
    except ValueError:
        check("T7 malformed spec raises ValueError", True)


# ---------------------------------------------------------------------------
# _validate_conditions (acceptance check 4)
# ---------------------------------------------------------------------------

_REAL_IMAGE = "/Users/reubenpatterson/qwen-agent-workspace/z_image_test.png"


def _raises_value_error(fn):
    try:
        fn()
        return False
    except ValueError:
        return True


def test_validate_conditions():
    num_frames = 49

    check(
        "T8 frame_index=-1 raises",
        _raises_value_error(
            lambda: ltx_video_skill._validate_conditions(
                [{"image_path": _REAL_IMAGE, "frame_index": -1, "strength": 1.0}], num_frames
            )
        ),
    )

    check(
        "T9 frame_index==num_frames raises",
        _raises_value_error(
            lambda: ltx_video_skill._validate_conditions(
                [{"image_path": _REAL_IMAGE, "frame_index": num_frames, "strength": 1.0}],
                num_frames,
            )
        ),
    )

    check(
        "T10 strength=1.5 raises",
        _raises_value_error(
            lambda: ltx_video_skill._validate_conditions(
                [{"image_path": _REAL_IMAGE, "frame_index": 0, "strength": 1.5}], num_frames
            )
        ),
    )

    check(
        "T11 nonexistent local file raises",
        _raises_value_error(
            lambda: ltx_video_skill._validate_conditions(
                [{"image_path": "/nonexistent/path/xyz.png", "frame_index": 0, "strength": 1.0}],
                num_frames,
            )
        ),
    )

    check(
        "T12 duplicate frame_index=0 raises",
        _raises_value_error(
            lambda: ltx_video_skill._validate_conditions(
                [
                    {"image_path": _REAL_IMAGE, "frame_index": 0, "strength": 1.0},
                    {"image_path": _REAL_IMAGE, "frame_index": 0, "strength": 1.0},
                ],
                num_frames,
            )
        ),
    )

    def _valid_pair():
        ltx_video_skill._validate_conditions(
            [
                {"image_path": _REAL_IMAGE, "frame_index": 0, "strength": 1.0},
                {"image_path": _REAL_IMAGE, "frame_index": num_frames - 1, "strength": 1.0},
            ],
            num_frames,
        )

    try:
        _valid_pair()
        check("T13 valid two-condition list (indices 0 and num_frames-1) passes", True)
    except ValueError as e:
        check("T13 valid two-condition list (indices 0 and num_frames-1) passes", False, str(e))


# ---------------------------------------------------------------------------
# _check_ceiling (acceptance checks 11/12) -- monkeypatch CEILING_TABLE_PATH
# ---------------------------------------------------------------------------

_FRAME0 = [{"image_path": _REAL_IMAGE, "frame_index": 0, "strength": 1.0}]


def _cond_at(frame_index):
    return [
        {"image_path": _REAL_IMAGE, "frame_index": 0, "strength": 1.0},
        {"image_path": _REAL_IMAGE, "frame_index": frame_index, "strength": 1.0},
    ]


def _with_table(table, fn):
    """Point ltx_video_skill.CEILING_TABLE_PATH at a temp file holding
    `table`, call fn(), then restore the original path."""
    original = ltx_video_skill.CEILING_TABLE_PATH
    fd, path = tempfile.mkstemp(suffix=".json")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(table, f)
        ltx_video_skill.CEILING_TABLE_PATH = path
        fn()
    finally:
        ltx_video_skill.CEILING_TABLE_PATH = original
        os.unlink(path)


def test_check_ceiling():
    table = {
        "meta": {
            "generated_from": "generated/ltx_ceiling/results.jsonl",
            "generated_at": "2026-08-25T00:00:00Z",
            "fraction": 0.82,
            "wide": False,
            "conditioning": "frame0-only",
            "cap_gib": 30.70,
            "safety_margin_frac": 0.95,
            "host_total_gib": 48.0,
            "diffusers_version": "0.40.0",
        },
        "ceiling": {"704x480": 49},
    }

    def _t14():
        try:
            ltx_video_skill._check_ceiling(704, 480, 49, _FRAME0, False)
            check("T14 704x480x49 (== ceiling) passes", True)
        except mps_guard.HostSafetyError as e:
            check("T14 704x480x49 (== ceiling) passes", False, str(e))

    _with_table(table, _t14)

    def _t15():
        check(
            "T15 704x480x57 (> ceiling) raises R2",
            _raises_value_error_like(
                lambda: ltx_video_skill._check_ceiling(704, 480, 57, _FRAME0, False),
                mps_guard.HostSafetyError,
            ),
        )

    _with_table(table, _t15)

    def _t16():
        # num_frames=49 alone would pass, but a non-zero-index condition
        # derates by _CEILING_FRAMES_PER_CONDITION (8): 49 + 8 = 57 > 49.
        check(
            "T16 non-zero-index condition derate pushes 49 over the 49 ceiling",
            _raises_value_error_like(
                lambda: ltx_video_skill._check_ceiling(704, 480, 49, _cond_at(48), False),
                mps_guard.HostSafetyError,
            ),
        )

    _with_table(table, _t16)

    def _t17():
        try:
            ltx_video_skill._check_ceiling(704, 480, 57, _FRAME0, True)
            check("T17 wide=True is a no-op even for an otherwise-over-ceiling request", True)
        except mps_guard.HostSafetyError as e:
            check(
                "T17 wide=True is a no-op even for an otherwise-over-ceiling request",
                False,
                str(e),
            )

    _with_table(table, _t17)

    def _t18():
        # 704x480 does not bound 1024x256 (480 <= 256 is false), so there is
        # no smaller-or-equal measured resolution -> R1 (unmeasured).
        check(
            "T18 unmeasured resolution with no smaller measured bound raises R1",
            _raises_value_error_like(
                lambda: ltx_video_skill._check_ceiling(1024, 256, 49, _FRAME0, False),
                mps_guard.HostSafetyError,
            ),
        )

    _with_table(table, _t18)

    min_rule_table = {"meta": table["meta"], "ceiling": {"384x384": 121, "704x480": 49}}

    def _t19_pass():
        # 800x600 is bounded by both 384x384 and 704x480; the tighter (min)
        # bound, 49, must be used, so 49 frames passes.
        try:
            ltx_video_skill._check_ceiling(800, 600, 49, _FRAME0, False)
            check("T19 min-rule: unmeasured resolution passes at the tighter bound (49)", True)
        except mps_guard.HostSafetyError as e:
            check(
                "T19 min-rule: unmeasured resolution passes at the tighter bound (49)",
                False,
                str(e),
            )

    _with_table(min_rule_table, _t19_pass)

    def _t20_fail():
        # 97 > 49 (the tighter bound) even though 97 <= 121 (the looser one).
        check(
            "T20 min-rule: the tighter bound (49), not the looser one (121), is enforced",
            _raises_value_error_like(
                lambda: ltx_video_skill._check_ceiling(800, 600, 97, _FRAME0, False),
                mps_guard.HostSafetyError,
            ),
        )

    _with_table(min_rule_table, _t20_fail)

    # Table absent: warn and proceed (no raise).
    original = ltx_video_skill.CEILING_TABLE_PATH
    ltx_video_skill.CEILING_TABLE_PATH = "/nonexistent/ltx_ceiling.json"
    try:
        ltx_video_skill._check_ceiling(704, 480, 121, _FRAME0, False)
        check("T21 absent table warns and proceeds (no raise)", True)
    except mps_guard.HostSafetyError as e:
        check("T21 absent table warns and proceeds (no raise)", False, str(e))
    finally:
        ltx_video_skill.CEILING_TABLE_PATH = original


# ---------------------------------------------------------------------------
# _check_ceiling -- measured-but-omitted regression (R3) and related cases
# ---------------------------------------------------------------------------

def test_check_ceiling_measured_omitted():
    # 704x480 WAS measured (rows exist in results.jsonl) but its best run
    # exceeded the safety margin, so the reducer omitted it from `ceiling`.
    # This must be REFUSED (R3), not bounded by 448x448's ceiling.
    regression_table = {
        "meta": {
            "generated_from": "generated/ltx_ceiling/results.jsonl",
            "generated_at": "2026-08-25T00:00:00Z",
            "fraction": 0.82,
            "wide": False,
            "conditioning": "frame0-only",
            "cap_gib": 30.70,
            "safety_margin_frac": 0.98,
            "host_total_gib": 48.0,
            "diffusers_version": "0.40.0",
            "measured_resolutions": ["448x448", "704x480"],
        },
        "ceiling": {"448x448": 73},
    }

    def _t22():
        try:
            ltx_video_skill._check_ceiling(704, 480, 49, _FRAME0, False)
            check("T22 measured-but-omitted 704x480x49 raises R3 (regression)", False, "did not raise")
        except mps_guard.HostSafetyError as e:
            msg = str(e)
            check(
                "T22 measured-but-omitted 704x480x49 raises R3 (regression)",
                "was measured" in msg and "safety margin" in msg,
                "got %r" % msg,
            )

    _with_table(regression_table, _t22)

    # 999x999 is neither in `ceiling` nor in `measured_resolutions`, and no
    # smaller measured resolution dominates it (448<=999 and 448<=999 is
    # true, so it WOULD be dominated by 448x448 -- use a table where the
    # only measured entry does not dominate, so R1 fires).
    r1_table = {
        "meta": regression_table["meta"],
        "ceiling": {},
    }

    def _t23():
        check(
            "T23 999x999 unmeasured, no dominating entry, raises R1",
            _raises_value_error_like(
                lambda: ltx_video_skill._check_ceiling(999, 999, 49, _FRAME0, False),
                mps_guard.HostSafetyError,
            ),
        )
        try:
            ltx_video_skill._check_ceiling(999, 999, 49, _FRAME0, False)
        except mps_guard.HostSafetyError as e:
            check(
                "T23b R1 message names 'no measured ceiling entry'",
                "no measured ceiling entry" in str(e),
                "got %r" % str(e),
            )

    _with_table(r1_table, _t23)

    # A truly-unmeasured resolution (520x520) IS dominated by a smaller
    # measured-in-`ceiling` resolution (512x512): the dominated-min path
    # still works for genuinely-unmeasured resolutions.
    dominated_table = {
        "meta": {
            "generated_from": "generated/ltx_ceiling/results.jsonl",
            "generated_at": "2026-08-25T00:00:00Z",
            "fraction": 0.82,
            "wide": False,
            "conditioning": "frame0-only",
            "cap_gib": 30.70,
            "safety_margin_frac": 0.98,
            "host_total_gib": 48.0,
            "diffusers_version": "0.40.0",
            "measured_resolutions": ["512x512"],
        },
        "ceiling": {"512x512": 73},
    }

    def _t24_pass():
        try:
            ltx_video_skill._check_ceiling(520, 520, 49, _FRAME0, False)
            check("T24 520x520x49 passes, dominated-min bound (73)", True)
        except mps_guard.HostSafetyError as e:
            check("T24 520x520x49 passes, dominated-min bound (73)", False, str(e))

    _with_table(dominated_table, _t24_pass)

    def _t25_fail():
        check(
            "T25 520x520x97 raises R2 (bounded by 73)",
            _raises_value_error_like(
                lambda: ltx_video_skill._check_ceiling(520, 520, 97, _FRAME0, False),
                mps_guard.HostSafetyError,
            ),
        )

    _with_table(dominated_table, _t25_fail)

    # Back-compat: a table with NO measured_resolutions key at all behaves as
    # the old rule (dominated-min fallback), no crash.
    no_measured_table = {
        "meta": {
            "generated_from": "generated/ltx_ceiling/results.jsonl",
            "generated_at": "2026-08-25T00:00:00Z",
            "fraction": 0.82,
            "wide": False,
            "conditioning": "frame0-only",
            "cap_gib": 30.70,
            "safety_margin_frac": 0.95,
            "host_total_gib": 48.0,
            "diffusers_version": "0.40.0",
        },
        "ceiling": {"448x448": 73},
    }

    def _t26():
        try:
            ltx_video_skill._check_ceiling(704, 480, 49, _FRAME0, False)
            check("T26 back-compat: no measured_resolutions key, dominated-min fallback, no crash", True)
        except mps_guard.HostSafetyError as e:
            check(
                "T26 back-compat: no measured_resolutions key, dominated-min fallback, no crash",
                False,
                str(e),
            )

    _with_table(no_measured_table, _t26)


# ---------------------------------------------------------------------------
# --allow-override safety-scoping regression (this task)
#
# generate_video spawns real subprocess stages (stage1/2/3), so it cannot be
# driven end-to-end offline without executing an LTX stage -- forbidden for
# this test file, and not how any other test here exercises generate_video
# (none of the existing tests call it either; they all target the unit-level
# helpers). So, per the task spec's fallback, this is a source-level proof
# that: (a) the pre-check still refuses when it IS consulted
# (allow_override=False, restated here for a self-contained story), and
# (b) allow_override guards ONLY the _check_ceiling call -- never
# mps_guard.preflight.
# ---------------------------------------------------------------------------

def test_allow_override_scoping():
    # (a) The advisory pre-check still refuses a measured-but-omitted
    # resolution when it is consulted (allow_override=False path).
    regression_table = {
        "meta": {
            "generated_from": "generated/ltx_ceiling/results.jsonl",
            "generated_at": "2026-08-25T00:00:00Z",
            "fraction": 0.82,
            "wide": False,
            "conditioning": "frame0-only",
            "cap_gib": 30.70,
            "safety_margin_frac": 0.98,
            "host_total_gib": 48.0,
            "diffusers_version": "0.40.0",
            "measured_resolutions": ["448x448", "704x480"],
        },
        "ceiling": {"448x448": 73},
    }

    def _t27():
        check(
            "T27 _check_ceiling still refuses measured-but-omitted 704x480x49 (R3) when consulted",
            _raises_value_error_like(
                lambda: ltx_video_skill._check_ceiling(704, 480, 49, _FRAME0, False),
                mps_guard.HostSafetyError,
            ),
        )

    _with_table(regression_table, _t27)

    # (b) allow_override guards ONLY the _check_ceiling call. Proven at the
    # source level: an `if allow_override` guard exists in generate_video,
    # and _check_ceiling is called in its `else` branch.
    src = inspect.getsource(ltx_video_skill.generate_video)
    check(
        "T28 generate_video has an `if allow_override` guard",
        "if allow_override" in src,
        "source:\n%s" % src,
    )

    guard_idx = src.find("if allow_override")
    else_idx = src.find("else:", guard_idx) if guard_idx != -1 else -1
    ceiling_call = "_check_ceiling(width, height, num_frames, conditions, wide)"
    check_idx = src.find(ceiling_call, else_idx) if else_idx != -1 else -1
    check(
        "T29 _check_ceiling is called in the `else` branch of the allow_override guard "
        "(override True => not called; override False => called)",
        guard_idx != -1 and else_idx != -1 and check_idx != -1 and guard_idx < else_idx < check_idx,
        "guard_idx=%d else_idx=%d check_idx=%d" % (guard_idx, else_idx, check_idx),
    )

    # Safety-scoping regression: mps_guard.preflight must never appear on a
    # line that also mentions allow_override, anywhere in the module.
    full_src = inspect.getsource(ltx_video_skill)
    offending = [
        line for line in full_src.splitlines()
        if "preflight" in line and "allow_override" in line
    ]
    check(
        "T30 mps_guard.preflight is never gated by allow_override (safety-scoping regression)",
        offending == [],
        "offending lines: %r" % offending,
    )


def _raises_value_error_like(fn, exc_type):
    try:
        fn()
        return False
    except exc_type:
        return True


if __name__ == "__main__":
    test_normalized_conditions()
    test_parse_keyframe_spec()
    test_validate_conditions()
    test_check_ceiling()
    test_check_ceiling_measured_omitted()
    test_allow_override_scoping()

    print("OK %d/%d" % (TOTAL - FAILED, TOTAL))
    sys.exit(0 if FAILED == 0 else 1)
