"""Plain-python (no pytest) tests for mps_guard's memory-supply metric.

Run: python3 tests/test_mps_guard_metric.py
Prints PASS/FAIL per case, then "OK n/27" and exits 0, or exits 1 on any
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
    abort21, reason21 = _swap_abort(4.00, 1.27)
    check(
        "T21 jump misfire no longer aborts",
        abort21 is False,
        "abort=%s reason=%r" % (abort21, reason21),
    )

    # T22: the dance healthy run must not abort. start 4.69, current 5.42.
    abort22, reason22 = _swap_abort(5.42, 4.69)
    check(
        "T22 dance healthy run does not abort",
        abort22 is False,
        "abort=%s reason=%r" % (abort22, reason22),
    )

    # T23: genuine runaway aborts. start 4.69, current 12.00 (growth 7.31,
    # absolute 12.00 > 6.5).
    abort23, reason23 = _swap_abort(12.00, 4.69)
    check(
        "T23 genuine runaway aborts, reason mentions growth and floor",
        abort23 is True and "grew" in reason23 and "floor" in reason23,
        "abort=%s reason=%r" % (abort23, reason23),
    )

    # T24: growth large but absolute below floor. start 0.10, current 6.00
    # (growth 5.90, absolute 6.00 < 6.5). The purged-baseline case
    # generalised.
    abort24, reason24 = _swap_abort(6.00, 0.10)
    check(
        "T24 growth large but absolute below floor does not abort",
        abort24 is False,
        "abort=%s reason=%r" % (abort24, reason24),
    )

    # T25: absolute above floor but growth small. start 6.40, current 7.00
    # (growth 0.60). A host that merely starts with high swap must not be
    # aborted for drifting slightly.
    abort25, reason25 = _swap_abort(7.00, 6.40)
    check(
        "T25 absolute above floor but growth small does not abort",
        abort25 is False,
        "abort=%s reason=%r" % (abort25, reason25),
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
    test_skip_supply_gate_scoping()

    print("OK %d/%d" % (TOTAL - FAILED, TOTAL))
    sys.exit(0 if FAILED == 0 else 1)
