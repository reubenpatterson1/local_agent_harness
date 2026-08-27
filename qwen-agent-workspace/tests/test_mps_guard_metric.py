"""Plain-python (no pytest) tests for mps_guard's memory-supply metric.

Run: python3 tests/test_mps_guard_metric.py
Prints PASS/FAIL per case, then "OK n/43" and exits 0, or exits 1 on any
failure.
"""

import inspect
import sys

sys.path.insert(0, "/Users/reubenpatterson/qwen-agent-workspace")

import mps_guard  # noqa: E402
from mps_guard import HostSafetyError, mem_supply_gib  # noqa: E402
from mps_guard import _supply_gate_ok, _swap_abort  # noqa: E402

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


def close(a, b):
    return abs(a - b) < 0.005


# ---------------------------------------------------------------------------
# mem_supply_gib cases (synthetic census dicts with only the needed keys)
# ---------------------------------------------------------------------------

def test_mem_supply_cases():
    t1 = mem_supply_gib({"pageable_gib": 38.56, "gpu_other_gib": 31.90})
    check("T1 mem_supply_gib normal", close(t1, 5.66), "got %.4f" % t1)

    t2 = mem_supply_gib({"pageable_gib": 26.39, "gpu_other_gib": 31.96})
    check("T2 mem_supply_gib clamped to 0", close(t2, 0.00), "got %.4f" % t2)

    t3 = mem_supply_gib({"pageable_gib": 36.01, "gpu_other_gib": 5.00})
    check("T3 mem_supply_gib normal", close(t3, 30.01), "got %.4f" % t3)

    t4 = mem_supply_gib({"pageable_gib": 42.60, "gpu_other_gib": 5.00})
    check("T4 mem_supply_gib normal", close(t4, 36.60), "got %.4f" % t4)

    t5 = mem_supply_gib({"pageable_gib": 10.00, "gpu_other_gib": 0.00})
    check("T5 mem_supply_gib normal", close(t5, 9.00), "got %.4f" % t5)

    # T6: gpu_alloc_self > gpu_alloc_system (clock skew) -- gpu_other_gib
    # is computed upstream in _mem_census() via max(0.0, system - self), so
    # here we exercise mem_supply_gib() with that already-clamped value and
    # confirm it does not raise and stays sane.
    gpu_other_clamped = max(0.0, 5.00 - 9.00)
    t6 = mem_supply_gib({"pageable_gib": 20.00, "gpu_other_gib": gpu_other_clamped})
    check(
        "T6 mem_supply_gib clock-skew gpu_other clamps to 0",
        close(gpu_other_clamped, 0.00) and close(t6, 19.00),
        "gpu_other=%.4f t6=%.4f" % (gpu_other_clamped, t6),
    )

    # T7: the live case measured today.
    t7 = mem_supply_gib({"pageable_gib": 40.97, "gpu_other_gib": 2.22})
    required_t7 = 0.82 * 37.44 + 1.5
    check(
        "T7 mem_supply_gib live case",
        close(t7, 37.75) and t7 >= required_t7,
        "got %.4f required=%.4f" % (t7, required_t7),
    )


# ---------------------------------------------------------------------------
# vm_stat parser fixture
# ---------------------------------------------------------------------------

VM_STAT_FIXTURE = """Mach Virtual Memory Statistics: (page size of 16384 bytes)
Pages free:                                  1277828.
Pages active:                                 709816.
Pages inactive:                               544240.
Pages speculative:                            163749.
Pages throttled:                                   0.
Pages wired down:                             221404.
Pages purgeable:                                8451.
"Translation faults":                      219431080.
Pages copy-on-write:                        14338519.
Pages zero filled:                         146080373.
Pages reactivated:                           9366157.
Pages purged:                                7658027.
File-backed pages:                            961774.
Anonymous pages:                              456031.
Pages stored in compressor:                   852686.
Pages occupied by compressor:                 151878.
Decompressions:                             48249336.
Compressions:                               66647980.
Pageins:                                    33580134.
Pageouts:                                      40311.
Swapins:                                     7706171.
Swapouts:                                   10930192.
"""


def test_vm_stat_parser():
    pages = mps_guard._vm_stat_pages(text=VM_STAT_FIXTURE)
    ok = (
        pages["_page_size"] == 16384
        and pages["Pages free"] == 1277828
        and pages["Pages active"] == 709816
        and pages["Pages inactive"] == 544240
        and pages["Pages speculative"] == 163749
        and pages["Pages wired down"] == 221404
        and pages["Pages purgeable"] == 8451
        and pages["File-backed pages"] == 961774
        and pages["Anonymous pages"] == 456031
        and pages["Pages occupied by compressor"] == 151878
    )
    check("T8 vm_stat parser all nine keys at 16384 B/page", ok, "got %r" % pages)

    fixture_missing_active = "\n".join(
        line for line in VM_STAT_FIXTURE.splitlines() if not line.startswith("Pages active:")
    )
    try:
        mps_guard._vm_stat_pages(text=fixture_missing_active)
        check("T9 vm_stat parser missing key raises", False, "did not raise")
    except HostSafetyError as e:
        check("T9 vm_stat parser missing key raises", "Pages active" in str(e), str(e))

    fixture_missing_header = "\n".join(VM_STAT_FIXTURE.splitlines()[1:])
    try:
        mps_guard._vm_stat_pages(text=fixture_missing_header)
        check("T10 vm_stat parser missing page-size header raises", False, "did not raise")
    except HostSafetyError:
        check("T10 vm_stat parser missing page-size header raises", True)

    check(
        "T11 quoted key not parsed as a key",
        '"Translation faults"' not in pages,
        "got keys %r" % list(pages.keys()),
    )


# ---------------------------------------------------------------------------
# ioreg parser fixture
# ---------------------------------------------------------------------------

IOREG_FIXTURE = '''+-o AppleARMPMURegs  <class IOAccelerator, id 0x100000123>
    {
      "PerformanceStatistics" = {"Alloc system memory"=34308227072,"Device Utilization %"=0}
    }
'''


def test_ioreg_parser():
    val = mps_guard._gpu_alloc_system_gib(text=IOREG_FIXTURE)
    check("T12 ioreg parser sums Alloc system memory", abs(val - 31.95) <= 0.01, "got %.4f" % val)

    try:
        mps_guard._gpu_alloc_system_gib(text="")
        check("T13 ioreg parser empty stdout raises", False, "did not raise")
    except HostSafetyError:
        check("T13 ioreg parser empty stdout raises", True)


# ---------------------------------------------------------------------------
# Threshold arithmetic
# ---------------------------------------------------------------------------

def test_threshold_arithmetic():
    required = 0.82 * 37.44 + mps_guard.PREFLIGHT_OVERHEAD_GIB
    check("T14 required for fraction 0.82 / recommended_max 37.44", close(required, 32.20), "got %.4f" % required)

    census_t1 = {"pageable_gib": 38.56, "gpu_other_gib": 31.90}
    census_t4 = {"pageable_gib": 42.60, "gpu_other_gib": 5.00}
    check(
        "T15 threshold refuses vLLM state and passes good state",
        mem_supply_gib(census_t1) < required and mem_supply_gib(census_t4) > required,
        "supply_t1=%.4f supply_t4=%.4f required=%.4f"
        % (mem_supply_gib(census_t1), mem_supply_gib(census_t4), required),
    )


# ---------------------------------------------------------------------------
# G1b conjunction (_supply_gate_ok) -- regression coverage for the
# 2026-08-25 thrash: mem_supply_gib() alone admitted a run ("jump") that
# then thrashed swap, even though the old psutil-only gate would correctly
# have refused it. The gate must be avail AND supply, never supply alone.
# ---------------------------------------------------------------------------

def test_supply_gate_conjunction():
    required = 0.82 * 37.44 + mps_guard.PREFLIGHT_OVERHEAD_GIB  # 32.20, per T14

    # T16: the jump regression. mem_supply_gib() alone says PASS here --
    # that is exactly the bug being fixed: the old gate admitted this run
    # and it thrashed (compressor 2.11->21.89 GiB, swap +5.21 GiB, sentinel
    # aborted). The conjunction must refuse on the avail arm.
    census_jump = {
        "free_gib": 13.65,
        "active_gib": 13.89,
        "inactive_gib": 9.37,
        "speculative_gib": 4.50,
        "filebacked_gib": 20.85,
        "anon_gib": 6.91,
        "compressor_gib": 2.11,
        "pageable_gib": 41.41,
        "gpu_other_gib": 2.55,
    }
    avail_jump = 27.52
    supply_jump = mem_supply_gib(census_jump)
    ok_jump, fail_jump = _supply_gate_ok(avail_jump, supply_jump, required)
    check(
        "T16 jump regression: supply arm alone PASSES, conjunction REFUSES on avail",
        abs(supply_jump - 38.05) < 0.5
        and supply_jump >= required
        and not ok_jump
        and any(f.startswith("avail=") for f in fail_jump)
        and not any(f.startswith("supply=") for f in fail_jump),
        "supply=%.4f avail=%.4f required=%.4f ok=%s fail=%r"
        % (supply_jump, avail_jump, required, ok_jump, fail_jump),
    )

    # T17: the dance run, which genuinely succeeded -- the conjunction must
    # still pass it, or the fix would be strictly more restrictive than
    # necessary.
    ok_dance, fail_dance = _supply_gate_ok(36.62, 38.00, required)
    check(
        "T17 dance case still passes",
        ok_dance and fail_dance == [],
        "ok=%s fail=%r" % (ok_dance, fail_dance),
    )

    # T18: supply-fails-only (State V from T1). avail is healthy; supply is
    # not -- the conjunction must refuse, naming the supply arm.
    supply_t18 = mem_supply_gib({"pageable_gib": 38.56, "gpu_other_gib": 31.90})
    ok_t18, fail_t18 = _supply_gate_ok(40.0, supply_t18, required)
    check(
        "T18 supply-fails-only: refuses, names supply arm",
        not ok_t18 and len(fail_t18) == 1 and fail_t18[0].startswith("supply="),
        "supply=%.4f ok=%s fail=%r" % (supply_t18, ok_t18, fail_t18),
    )

    # T19: both arms fail -- the conjunction must refuse and name both.
    ok_t19, fail_t19 = _supply_gate_ok(20.0, 10.0, required)
    check(
        "T19 both arms fail: message names both",
        not ok_t19
        and len(fail_t19) == 2
        and fail_t19[0].startswith("avail=")
        and fail_t19[1].startswith("supply="),
        "ok=%s fail=%r" % (ok_t19, fail_t19),
    )

    # T20: boundary. Comparison is strict "<", so avail == required and
    # supply == required must PASS, not refuse.
    ok_t20, fail_t20 = _supply_gate_ok(required, required, required)
    check(
        "T20 boundary: avail==required and supply==required passes (strict <)",
        ok_t20 and fail_t20 == [],
        "ok=%s fail=%r" % (ok_t20, fail_t20),
    )


# ---------------------------------------------------------------------------
# _swap_abort conjunction -- regression coverage for the 2026-08-25 jump
# misfire: swap-growth-alone aborted a run that never exceeded a healthy
# run's absolute swap peak, because `sudo purge` had shrunk the swapfile to
# a low baseline. The trigger must be growth AND an absolute floor, never
# growth alone.
# ---------------------------------------------------------------------------

def test_swap_abort_conjunction():
    # T21: the jump misfire must no longer abort. start 1.27, current 4.00
    # (growth 2.73, absolute below floor).
    abort21, reason21 = _swap_abort(4.00, 1.27, ())
    check(
        "T21 jump misfire no longer aborts",
        abort21 is False,
        "abort=%s reason=%r" % (abort21, reason21),
    )

    # T22: the dance healthy run must not abort. start 4.69, current 5.42.
    abort22, reason22 = _swap_abort(5.42, 4.69, ())
    check(
        "T22 dance healthy run does not abort",
        abort22 is False,
        "abort=%s reason=%r" % (abort22, reason22),
    )

    # T23: INVERTED by the 2026-08-27 two-tier redesign. start 4.69, current
    # 12.00 -- growth 7.31 is below the new 8.0 spike threshold, and there is
    # no window (empty tuple), so the sustained tier cannot fire either. This
    # used to abort under the single-sample growth-AND-floor conjunction;
    # see T29 for the sustained-tier case that DOES still catch a genuine
    # runaway once a qualifying window is present.
    abort23, reason23 = _swap_abort(12.00, 4.69, ())
    check(
        "T23 (inverted) growth 7.31 below 8.0 spike tier, no window: no abort",
        abort23 is False,
        "abort=%s reason=%r" % (abort23, reason23),
    )

    # T24: growth large but absolute below floor. start 0.10, current 6.00
    # (growth 5.90, absolute 6.00 < 6.5). The purged-baseline case
    # generalised.
    abort24, reason24 = _swap_abort(6.00, 0.10, ())
    check(
        "T24 growth large but absolute below floor does not abort",
        abort24 is False,
        "abort=%s reason=%r" % (abort24, reason24),
    )

    # T25: absolute above floor but growth small. start 6.40, current 7.00
    # (growth 0.60). A host that merely starts with high swap must not be
    # aborted for drifting slightly.
    abort25, reason25 = _swap_abort(7.00, 6.40, ())
    check(
        "T25 absolute above floor but growth small does not abort",
        abort25 is False,
        "abort=%s reason=%r" % (abort25, reason25),
    )


# ---------------------------------------------------------------------------
# _swap_abort two-tier redesign -- regression coverage for the 2026-08-27
# misfire: EVERY one of 13 real swap aborts across three 10-unit
# ltx-story-video runs fired on the single sample where pipeline.to("mps")
# finished wiring LTX's weights, never during denoising. See
# tests/test_mps_guard_metric.py T28 (the regression), T29-T31 (the
# sustained tier that still catches a genuine runaway), T32 (the spike
# tier), T33 (an AST guard against a future edit neutering the watchdog),
# T34 (replay of two real healthy traces that must never abort), and T35
# (the 2026-08-27 smoke3 panel-2 low-baseline decay-tail misfire that
# motivated widening the window from 5/8s to 7/12s).
# ---------------------------------------------------------------------------

def test_swap_abort_two_tier():
    # T28: replay panel-1's real series -- the load-step misfire itself.
    # swap sits flat at baseline (~10.44) while pipeline.to("mps") wires
    # LTX's weights, then steps once to 14.37 at t=18.1s as that finishes.
    # growth is 3.93, well below the 8.0 spike threshold, and the window's
    # trough (10.43) is still below baseline + 2.0, so the sustained tier
    # cannot fire either. This must NOT abort.
    window28 = [
        (0.0, 10.44),
        (2.0, 10.44),
        (4.1, 10.44),
        (7.2, 10.44),
        (11.6, 10.44),
        (16.0, 10.43),
        (18.1, 14.37),
    ]
    abort28, reason28 = _swap_abort(14.37, 10.44, window28)
    check(
        "T28 2026-08-27 load-step misfire does not abort",
        abort28 is False,
        "abort=%s reason=%r" % (abort28, reason28),
    )

    # T29: sustained runaway -- seven samples spanning 12.0s, every sample
    # (including the trough, the first) above baseline+2.0. Must abort,
    # reason naming the sustained tier. (trough 9.00 > 8.60, 7 samples,
    # span 12.0 >= 12.0.) Baseline 6.60 is ABOVE the 6.5 floor, so the
    # 2026-08-27 effective-baseline change (see mps_guard._swap_abort) is a
    # no-op here -- effective baseline == raw baseline == 6.60 -- and the
    # runaway semantics are unaffected.
    window29 = [
        (0.0, 9.00),
        (2.0, 9.50),
        (4.0, 10.00),
        (6.0, 10.50),
        (8.0, 11.00),
        (10.0, 11.50),
        (12.0, 12.00),
    ]
    abort29, reason29 = _swap_abort(12.00, 6.60, window29)
    check(
        "T29 sustained runaway aborts",
        abort29 is True and "sustained" in reason29,
        "abort=%s reason=%r" % (abort29, reason29),
    )

    # T30: window too short (only 6 of the required 7 samples) -- must not
    # abort even though every sample is above baseline+2.0.
    window30 = window29[-6:]
    abort30, reason30 = _swap_abort(12.00, 6.60, window30)
    check(
        "T30 window too short does not abort",
        abort30 is False,
        "abort=%s reason=%r" % (abort30, reason30),
    )

    # T31: same seven values as T29 but spaced only 1.5s apart (span 9.0s <
    # SENTINEL_SWAP_WINDOW_MIN_S of 12.0s), all above baseline+2.0 -- must
    # not abort.
    window31 = [
        (0.0, 9.00),
        (1.5, 9.50),
        (3.0, 10.00),
        (4.5, 10.50),
        (6.0, 11.00),
        (7.5, 11.50),
        (9.0, 12.00),
    ]
    abort31, reason31 = _swap_abort(12.00, 6.60, window31)
    check(
        "T31 span too short does not abort",
        abort31 is False,
        "abort=%s reason=%r" % (abort31, reason31),
    )

    # T32: spike tier -- single-sample jump of 10.00 GiB, no window needed.
    abort32, reason32 = _swap_abort(20.00, 10.00, ())
    check(
        "T32 spike tier aborts",
        abort32 is True and "spike" in reason32,
        "abort=%s reason=%r" % (abort32, reason32),
    )


# ---------------------------------------------------------------------------
# T35: 2026-08-27 smoke3 panel-2 low-baseline decay-tail misfire -- the first
# live run under the 5-sample/8s window killed a unit starting from a LOW
# swap baseline (6.50 GiB) on the load step's natural decay tail: step to
# 11.18, decaying ~0.55 GiB/sample through 10.80/10.17/9.63/9.08, all still
# above baseline+2.0 (8.50) when the old 5-sample window filled. This is the
# real trace (run generated/stories/smoke3, panel-2, both attempts
# identical); the last two samples (22.0, 8.53) and (24.0, 7.98) are
# extrapolated at the measured -0.55 GiB/sample decay rate, since the run
# was killed before they could be observed. Fed sample-by-sample through a
# local deque of maxlen 7 replicating Sentinel._loop, _swap_abort must
# return False on EVERY sample under the new 7-sample/12s window.
# ---------------------------------------------------------------------------

def test_low_baseline_decay_tail():
    import collections

    baseline35 = 6.50
    series35 = [
        (0.0, 6.50),
        (2.0, 6.49),
        (4.0, 6.49),
        (6.0, 6.49),
        (8.0, 6.45),
        (10.0, 6.44),
        (12.0, 11.18),
        (14.0, 10.80),
        (16.0, 10.17),
        (18.0, 9.63),
        (20.0, 9.08),
        (22.0, 8.53),  # extrapolated at -0.55 GiB/sample decay rate
        (24.0, 7.98),  # extrapolated at -0.55 GiB/sample decay rate
    ]

    window = collections.deque(maxlen=7)
    aborted_at = None
    for t, s in series35:
        window.append((t, s))
        should_abort, reason = _swap_abort(s, baseline35, tuple(window))
        if should_abort:
            aborted_at = (t, s, reason)
            break
    check(
        "T35 2026-08-27 smoke3 panel-2 low-baseline decay-tail misfire",
        aborted_at is None,
        "aborted at %r" % (aborted_at,),
    )


# ---------------------------------------------------------------------------
# T36: 2026-08-27 smoke take 2, panel-1 first attempt -- a sub-floor-baseline
# steady-state misfire distinct from T35. Baseline was 4.83 (this unit ran
# first after a fresh `sudo purge`). Loading the model displaces swap to an
# absolute steady state of ~6.9-7.1 GiB regardless of baseline (a sibling
# unit with baseline 8.71 settled at ~7.1, BELOW its own baseline), so from a
# sub-floor baseline the post-load steady state permanently exceeds
# baseline+2.0 and no finite persistence window could have helped -- only
# clamping the baseline up to the floor (SENTINEL_ABORT_SWAP_FLOOR_GIB) before
# adding the growth margin fixes it, since the floor already declares that
# absolute level normal. The pre-step samples below are reconstructed at the
# recorded baseline (4.83, decaying slightly as vm_stat noise); the tail
# values reconstruct the ~6.9-7.1 steady state and match the recorded trough
# (6.86) from the abort record. Fed sample-by-sample through a local deque of
# maxlen 7 replicating Sentinel._loop, _swap_abort must return False on EVERY
# sample.
# ---------------------------------------------------------------------------

def test_sub_floor_baseline_steady_state():
    import collections

    baseline36 = 4.83
    series36 = [
        (0.0, 4.83),
        (2.0, 4.83),
        (4.1, 4.82),
        (6.1, 4.80),
        (8.2, 4.79),
        (10.2, 4.78),
        (12.3, 6.90),
        (14.3, 7.05),
        (16.4, 6.98),
        (18.4, 6.92),
        (20.5, 6.88),
        (22.5, 6.86),
        (24.6, 6.86),
    ]

    window = collections.deque(maxlen=7)
    aborted_at = None
    for t, s in series36:
        window.append((t, s))
        should_abort, reason = _swap_abort(s, baseline36, tuple(window))
        if should_abort:
            aborted_at = (t, s, reason)
            break
    check(
        "T36 2026-08-27 smoke take 2 panel-1 sub-floor-baseline steady-state misfire",
        aborted_at is None,
        "aborted at %r" % (aborted_at,),
    )


# ---------------------------------------------------------------------------
# T33: AST guard on Sentinel._loop -- guards against a future edit silently
# neutering the watchdog (this is exactly the class of mistake this
# redesign is meant not to introduce).
# ---------------------------------------------------------------------------

def test_sentinel_loop_ast_guard():
    import ast

    with open(mps_guard.__file__) as f:
        src = f.read()
    tree = ast.parse(src, filename=mps_guard.__file__)

    sentinel_cls = None
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == "Sentinel":
            sentinel_cls = node
            break
    check("T33a Sentinel class found", sentinel_cls is not None)

    loop_fn = None
    for node in ast.walk(sentinel_cls):
        if isinstance(node, ast.FunctionDef) and node.name == "_loop":
            loop_fn = node
            break
    check("T33b Sentinel._loop found", loop_fn is not None)

    loop_src = ast.get_source_segment(src, loop_fn) or ""

    has_swap_abort_call = any(
        isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "_swap_abort"
        for n in ast.walk(loop_fn)
    )
    check("T33c _loop calls _swap_abort", has_swap_abort_call)

    def _is_os_exit_with_sentinel_code(n):
        if not (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "_exit"):
            return False
        if not (isinstance(n.func.value, ast.Name) and n.func.value.id == "os"):
            return False
        return any(
            isinstance(a, ast.Name) and a.id == "SENTINEL_EXIT_CODE" for a in n.args
        )

    has_os_exit = any(_is_os_exit_with_sentinel_code(n) for n in ast.walk(loop_fn))
    check("T33d _loop calls os._exit(SENTINEL_EXIT_CODE)", has_os_exit)

    check("T33e _loop references SENTINEL_ABORT_AVAIL_GIB", "SENTINEL_ABORT_AVAIL_GIB" in loop_src)
    check("T33f _loop references SENTINEL_ABORT_DISK_GIB", "SENTINEL_ABORT_DISK_GIB" in loop_src)


# ---------------------------------------------------------------------------
# T34: replay of two real healthy traces (panel-5, panel-9) through a local
# 5-sample deque replicating Sentinel._loop's call pattern -- must never
# abort. Then a synthetic monotonic climb must abort within 18.0s.
# ---------------------------------------------------------------------------

def test_healthy_trace_replay():
    import collections

    # panel-5: start 9.20, single-sample max 11.20 (step of exactly +2.00,
    # per the evidence: "panel-5 stepped exactly +2.00 and survived only
    # because the comparison is a strict `>`"), then receding to 9.48. No
    # more than one consecutive sample sits above start+2.0 (11.20).
    panel5_start = 9.20
    panel5_series = [9.20, 9.20, 11.20, 10.10, 9.48]
    panel5_elapsed = [0.0, 2.0, 4.0, 6.0, 8.0]

    # panel-9: start 13.31, series 13.15 -> 11.16 -> 9.27 receding (per the
    # evidence). No sample exceeds start+2.0 (15.31).
    panel9_start = 13.31
    panel9_series = [13.31, 13.15, 11.16, 9.27, 9.10]
    panel9_elapsed = [0.0, 2.0, 4.0, 6.0, 8.0]

    for name, start, series, elapsed in (
        ("panel-5", panel5_start, panel5_series, panel5_elapsed),
        ("panel-9", panel9_start, panel9_series, panel9_elapsed),
    ):
        window = collections.deque(maxlen=5)
        aborted_at = None
        for t, s in zip(elapsed, series):
            window.append((t, s))
            should_abort, reason = _swap_abort(s, start, tuple(window))
            if should_abort:
                aborted_at = (t, s, reason)
                break
        check(
            "T34 %s healthy trace never aborts" % name,
            aborted_at is None,
            "aborted at %r" % (aborted_at,),
        )

    # Synthetic monotonic climb: start 9.0, +1.0 GiB every 2s (+0.5 GiB/s).
    # First True must occur at elapsed <= 18.0s. Boundary math: at +0.5
    # GiB/s sampled every 2s, the 7-sample window's oldest (trough) sample
    # is always 12s behind the current one, i.e. its growth over baseline is
    # 0.5 * (elapsed - 12). That growth STRICTLY exceeds
    # SENTINEL_ABORT_SWAP_GROWTH_GIB (2.0) only once elapsed > 16.0 -- at
    # elapsed=16.0 the trough's growth is exactly 2.0, and the strict `>`
    # correctly does not fire there (the same strictness that lets
    # panel-5's real +2.00 load step above survive without aborting). The
    # next sample, at elapsed=18.0, is the first to strictly exceed it. The
    # ~4s of residual runaway latency this leaves (up from ~2s under the
    # 5-sample/8s window) is bounded by the 8.0 GiB spike tier, the
    # avail_gib < 4.0 trigger, and the MPS watermark cap.
    climb_start = 9.0
    window = collections.deque(maxlen=7)
    first_abort_elapsed = None
    for i in range(10):
        t = i * 2.0
        s = climb_start + i * 1.0
        window.append((t, s))
        should_abort, reason = _swap_abort(s, climb_start, tuple(window))
        if should_abort:
            first_abort_elapsed = t
            break
    check(
        "T34 synthetic monotonic climb aborts at elapsed <= 18.0s",
        first_abort_elapsed is not None and first_abort_elapsed <= 18.0,
        "first_abort_elapsed=%r" % (first_abort_elapsed,),
    )


# ---------------------------------------------------------------------------
# skip_supply_gate scoping -- the sweep-only G1b relaxation added for
# tests/measure_ltx_ceiling.py. T26 proves the underlying gate logic is
# untouched; T27 proves preflight() exposes the escape hatch, defaulted off.
# ---------------------------------------------------------------------------

def test_skip_supply_gate_scoping():
    # T26: the avail arm alone still fails the gate -- skip_supply_gate has
    # no effect on _supply_gate_ok itself, only on what preflight() does
    # with its result.
    ok26, fail26 = _supply_gate_ok(27.0, 38.0, 32.2)
    check(
        "T26 supply gate logic unchanged: avail arm alone still refuses",
        not ok26 and len(fail26) == 1 and fail26[0].startswith("avail="),
        "ok=%s fail=%r" % (ok26, fail26),
    )

    # T27: preflight() accepts skip_supply_gate, defaulted to False, so a
    # caller that never passes it keeps today's behavior unchanged.
    params = inspect.signature(mps_guard.preflight).parameters
    check(
        "T27 preflight() exposes skip_supply_gate, default False",
        "skip_supply_gate" in params and params["skip_supply_gate"].default is False,
        "params=%r" % (list(params),),
    )


if __name__ == "__main__":
    test_mem_supply_cases()
    test_vm_stat_parser()
    test_ioreg_parser()
    test_threshold_arithmetic()
    test_supply_gate_conjunction()
    test_swap_abort_conjunction()
    test_swap_abort_two_tier()
    test_low_baseline_decay_tail()
    test_sub_floor_baseline_steady_state()
    test_sentinel_loop_ast_guard()
    test_healthy_trace_replay()
    test_skip_supply_gate_scoping()

    print("OK %d/%d" % (TOTAL - FAILED, TOTAL))
    sys.exit(0 if FAILED == 0 else 1)
