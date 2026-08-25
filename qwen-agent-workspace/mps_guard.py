"""Host-safety layer for MPS (Apple GPU) memory on this machine.

This module exists because the default MPS high watermark of 1.7 permits
~63.65 GiB of allocation on a 48 GiB host, and because the watermark bounds
Metal buffers only -- CPU tensors escape it entirely -- a system-level
sentinel is required in addition to the watermark. A hard host freeze was
observed on 2026-08-25, with 29.7 GiB of wired, unswappable memory measured
while vLLM was resident at the time.

G1 used to gate on psutil.virtual_memory().available (= free + inactive),
which omits *active* file-backed pages -- reclaimable clean file cache.
Measured: committing MPS memory evicted file cache 1:1 with zero swap
growth. That made the gate produce false refusals: psutil said 31.19 GiB
against a 33.70 GiB requirement (REFUSE) on a run that, measured by the
correct metric, had 37.76 GiB against 32.20 (PASS, +5.55 margin) -- and the
allocation genuinely fit, since the stage-2 cap is 30.70 GiB. G1 is now
`mem_supply_gib()`, built from a `vm_stat` census (see _mem_census()).
"""

import json
import os
import re
import socket
import subprocess
import sys
import threading
import time
import datetime

import psutil

GIB = 1024 ** 3

SENTINEL_INTERVAL_S = 2.0
SENTINEL_ABORT_AVAIL_GIB = 4.0
SENTINEL_ABORT_DISK_GIB  = 5.0   # see PREFLIGHT_MIN_DISK_GIB: disk, not swap slack
# healthy stage-2 run grew swap +0.73 GiB; 2.7x margin
SENTINEL_ABORT_SWAP_GROWTH_GIB = 2.0
# Absolute floor for the swap trigger. Growth alone misfires after `sudo purge`
# shrinks the swapfile: a run aborted at 4.00 GiB absolute swap (growth +2.73 from a
# purged 1.27 baseline) while a run that COMPLETED reached ~5.4 GiB absolute. 6.5 sits
# above that known-good peak with margin, so the trigger now fires only on growth that
# is both large AND has carried absolute usage past anything observed in a healthy run.
SENTINEL_ABORT_SWAP_FLOOR_GIB = 6.5
SENTINEL_EXIT_CODE = 75
# Fail-safe posture: if the sentinel loses its ability to sample memory
# (an ioreg/vm_stat parse failure raises HostSafetyError inside the daemon
# thread), it must not die silently and let the stage run on with no
# memory backstop. Instead it retries a bounded number of times and, if
# sampling still cannot be trusted, aborts the run itself rather than
# continue blind. See Sentinel._loop.
SENTINEL_MAX_SAMPLE_FAILURES = 3

# This process's non-GPU physical residency (CPython heap, torch/diffusers
# module data, CPU staging tensors), NOT headroom above the MPS cap.
# Measured bare-torch non-GPU footprint was 0.20 GiB (phys_footprint 4.20 -
# IOAccelerator 4.00); 1.5 allows ~7x. The old 3.0 assumed the allocation
# could overshoot the cap, which is false -- the cap is hard and binding (a
# real run peaked at 30.09 against a 30.70 cap).
PREFLIGHT_OVERHEAD_GIB = 1.5
# Fixed slack withheld from mem_supply_gib() before it's treated as usable
# supply -- keeps a minimum margin for the OS/kernel independent of the
# per-process MPS cap sizing (which PREFLIGHT_OVERHEAD_GIB covers instead).
MEM_OS_RESERVE_GIB = 1.0
PREFLIGHT_MAX_OTHER_GPU_GIB = 8.0     # idle baseline measured at 2.22 GiB, servers down
# Free disk on the volume backing the swapfile. This replaces a former
# free-swap gate: macOS resizes the swapfile dynamically, so free swap sits in a
# narrow ~1.5 GiB band regardless of real memory pressure (nine samples spanning a
# 28 GB swap-usage change all fell between 1.34 and 1.66 GiB), which made the old
# 2.0 GiB gate unsatisfiable by construction. Disk is what swap can actually grow
# into, so it is what bounds overshoot absorption.
PREFLIGHT_MIN_DISK_GIB = 20.0

FRACTION_STAGE1 = 0.35
# weights 24.29 + 2.32 = 26.61 GiB plus a 4.09 GiB activation budget = 30.70
# GiB; 30.70/37.44 = 0.820.
FRACTION_STAGE2 = 0.82
# widens activations to 6.0 GiB (32.57/37.44 = 0.870); opt-in only.
FRACTION_STAGE2_WIDE = 0.87
FRACTION_STAGE3 = 0.10

VLLM_PORTS = (8177, 8178)

GUARD_STATE_DIR = "/Users/reubenpatterson/.qwen-serve-guard"
GUARD_STANDDOWN = GUARD_STATE_DIR + "/stand-down"

HOST_PREP_SCRIPT = "/Users/reubenpatterson/qwen-agent-workspace/bin/ltx-host-prep"
HOST_RESTORE_SCRIPT = "/Users/reubenpatterson/qwen-agent-workspace/bin/ltx-host-restore"


class HostSafetyError(RuntimeError):
    """Refused because running would risk the host."""


def set_watermark(fraction):
    """Set the MPS high/low watermark ratios and the per-process fraction.

    Must be callable as the first statement of a stage.
    """
    os.environ["PYTORCH_MPS_HIGH_WATERMARK_RATIO"] = "%.4f" % fraction
    # Omitting this raises: RuntimeError: invalid low watermark ratio 1.4
    os.environ["PYTORCH_MPS_LOW_WATERMARK_RATIO"] = "%.4f" % max(fraction - 0.05, 0.01)

    import torch

    if torch.backends.mps.is_available():
        torch.mps.set_per_process_memory_fraction(float(fraction))
        rec = torch.mps.recommended_max_memory() / GIB
    else:
        rec = 0.0

    return {
        "fraction": fraction,
        "cap_gib": round(rec * fraction, 2) if rec else 0.0,
        "recommended_max_gib": round(rec, 2),
    }


# Required vm_stat keys for _mem_census(); exact spelling as printed by
# /usr/bin/vm_stat (before its trailing colon).
_VM_STAT_REQUIRED_KEYS = (
    "Pages free",
    "Pages active",
    "Pages inactive",
    "Pages speculative",
    "Pages wired down",
    "Pages purgeable",
    "File-backed pages",
    "Anonymous pages",
    "Pages occupied by compressor",
)

# Matches "Pages free:                                  1277828." but not
# quoted keys like "Translation faults":  ... (the leading '"' is not in
# [A-Za-z], so those lines never match starting at column 0).
_VM_STAT_LINE_RE = re.compile(r'^([A-Za-z][^:]*):\s+(\d+)\.?\s*$')


def _vm_stat_pages(text=None):
    """Parse `vm_stat` into raw page counts plus "_page_size".

    `text` is test-only: when provided it bypasses the subprocess call so
    tests/test_mps_guard_metric.py can inject a captured fixture. Do not
    pass it in production call sites.
    """
    if text is None:
        result = subprocess.run(["/usr/bin/vm_stat"], capture_output=True, text=True)
        text = result.stdout

    size_match = re.search(r'page size of (\d+) bytes', text)
    if size_match is None:
        raise HostSafetyError(
            "HOST SAFETY REFUSAL: could not read vm_stat page size; "
            "refusing rather than defaulting to an assumed page size."
        )
    page_size = int(size_match.group(1))

    pages = {}
    for line in text.splitlines():
        m = _VM_STAT_LINE_RE.match(line)
        if m:
            pages[m.group(1)] = int(m.group(2))

    missing = [k for k in _VM_STAT_REQUIRED_KEYS if k not in pages]
    if missing:
        raise HostSafetyError(
            "HOST SAFETY REFUSAL: vm_stat output is missing required key(s): %s"
            % ", ".join(missing)
        )

    result_pages = {k: pages[k] for k in _VM_STAT_REQUIRED_KEYS}
    result_pages["_page_size"] = page_size
    return result_pages


def _gpu_alloc_system_gib(text=None):
    """Sum of "Alloc system memory" across all IOAccelerator nodes, in GiB.

    `text` is test-only: when provided it bypasses the subprocess call so
    tests/test_mps_guard_metric.py can inject a captured fixture. Do not
    pass it in production call sites.

    `ioreg -r -c NoSuchClass` exits 0 with empty output, so the exit code
    must NOT be trusted -- detect failure by key absence instead. This
    deliberately departs from the previous wired-memory helper's
    return-0.0-on-error convention, because a silently-zero subtrahend is
    unsafe in exactly the direction that caused the 2026-08-25 freeze.
    """
    if text is None:
        result = subprocess.run(
            ["/usr/sbin/ioreg", "-r", "-c", "IOAccelerator", "-w0", "-k", "PerformanceStatistics"],
            capture_output=True,
            text=True,
        )
        text = result.stdout

    matches = re.findall(r'"Alloc system memory"=(\d+)', text)
    if not matches:
        raise HostSafetyError(
            "HOST SAFETY REFUSAL: could not read system GPU allocation via "
            "ioreg; refusing rather than assuming zero other-process GPU usage."
        )
    # One node on this host; summing is correct for a multi-GPU host too.
    return sum(int(m) for m in matches) / GIB


def _mem_census():
    """Sample the full memory picture that G1a/G1b gate on.

    Kept separate from snapshot() so preflight() can take this sample once
    and gate on it before paying for a full snapshot() (see the G1a comment
    in preflight() about keeping the refusal path cheap).
    """
    pages = _vm_stat_pages()
    page_size = pages["_page_size"]

    def gib(key):
        return pages[key] * page_size / GIB

    free_gib = gib("Pages free")
    active_gib = gib("Pages active")
    inactive_gib = gib("Pages inactive")
    speculative_gib = gib("Pages speculative")
    wired_gib = gib("Pages wired down")
    purgeable_gib = gib("Pages purgeable")
    filebacked_gib = gib("File-backed pages")
    anon_gib = gib("Anonymous pages")
    compressor_gib = gib("Pages occupied by compressor")

    gpu_alloc_system_gib = _gpu_alloc_system_gib()

    import torch

    if torch.backends.mps.is_available():
        gpu_alloc_self_gib = torch.mps.driver_allocated_memory() / GIB
    else:
        gpu_alloc_self_gib = 0.0

    # Physical pages the kernel can hand to a new allocation without
    # touching the compressor or swap. Deliberately EXCLUDES `wired`
    # (cannot be yielded, and it is where our own future GPU pages land)
    # and `compressor` (pinned, and crediting it re-introduces
    # non-monotonicity). Deliberately does NOT use the anon/file split,
    # because macOS exposes no per-queue file/anon breakdown -- the four
    # queue counters span the same pages (verified: anon + filebacked =
    # 38.52 vs active + inactive + speculative = 38.47).
    pageable_gib = free_gib + active_gib + inactive_gib + speculative_gib

    # Subtracted because pageable_gib includes *idle* Metal buffers (an
    # idle vLLM's 26 GiB sits in anon, hence in active/inactive). Using
    # reservations rather than residency over-subtracts slightly -- the
    # safe direction, and it closes the reserved-but-untouched hole.
    gpu_other_gib = max(0.0, gpu_alloc_system_gib - gpu_alloc_self_gib)

    return {
        "free_gib": free_gib,
        "active_gib": active_gib,
        "inactive_gib": inactive_gib,
        "speculative_gib": speculative_gib,
        "wired_gib": wired_gib,
        "purgeable_gib": purgeable_gib,
        "filebacked_gib": filebacked_gib,
        "anon_gib": anon_gib,
        "compressor_gib": compressor_gib,
        "pageable_gib": pageable_gib,
        "gpu_alloc_system_gib": gpu_alloc_system_gib,
        "gpu_alloc_self_gib": gpu_alloc_self_gib,
        "gpu_other_gib": gpu_other_gib,
    }


def mem_supply_gib(census):
    """Usable host memory supply, in GiB. Pure function of a census dict
    (single argument, no I/O) so it is unit-testable offline.
    """
    return max(0.0, census["pageable_gib"] - census["gpu_other_gib"] - MEM_OS_RESERVE_GIB)


def _supply_gate_ok(avail_gib, supply_gib, required_gib):
    """G1b decision, factored out as a pure function (no I/O, no host
    access) purely so it is unit-testable without a live host -- see
    tests/test_mps_guard_metric.py T16-T20. Both preflight() and the
    `readiness` CLI subcommand call this so they can never disagree.

    Refuses (returns ok=False) if EITHER arm falls short of required_gib --
    this is a conjunction of both metrics, not either alone. Returns
    (ok, failures), where failures holds one human-readable string per
    failing arm (empty when ok).
    """
    # The single most important line in this function: refuse if EITHER
    # metric falls short (`or`), never only if BOTH do (`and`). An `and`
    # here would make the gate strictly more permissive than either metric
    # alone, which is precisely the 2026-08-25 regression being fixed.
    if avail_gib < required_gib or supply_gib < required_gib:
        failures = []
        if avail_gib < required_gib:
            failures.append("avail=%.2f GiB < required=%.2f GiB" % (avail_gib, required_gib))
        if supply_gib < required_gib:
            failures.append("supply=%.2f GiB < required=%.2f GiB" % (supply_gib, required_gib))
        return (False, failures)
    return (True, [])


def _swap_abort(swap_used_gib, swap_start_gib):
    """Sentinel's third abort decision, factored out as a pure function (no
    I/O, no host access) purely so it is unit-testable without a live host --
    see tests/test_mps_guard_metric.py T21-T25. Sentinel._loop calls this so
    the abort logic can never drift from what is tested here.

    Returns (should_abort, reason).
    """
    swap_growth = swap_used_gib - swap_start_gib
    if swap_growth > SENTINEL_ABORT_SWAP_GROWTH_GIB and swap_used_gib > SENTINEL_ABORT_SWAP_FLOOR_GIB:
        reason = (
            "swap grew %.2f GiB (from %.2f to %.2f), above %.1f, and absolute usage "
            "%.2f exceeds floor %.1f"
            % (
                swap_growth,
                swap_start_gib,
                swap_used_gib,
                SENTINEL_ABORT_SWAP_GROWTH_GIB,
                swap_used_gib,
                SENTINEL_ABORT_SWAP_FLOOR_GIB,
            )
        )
        return (True, reason)
    return (False, "")


def snapshot():
    """Sample host and MPS memory state."""
    import torch

    vm = psutil.virtual_memory()
    swap = psutil.swap_memory()
    census = _mem_census()

    if torch.backends.mps.is_available():
        mps_driver_gib = torch.mps.driver_allocated_memory() / GIB
        mps_current_gib = torch.mps.current_allocated_memory() / GIB
    else:
        mps_driver_gib = 0.0
        mps_current_gib = 0.0

    return {
        "avail_gib": round(vm.available / GIB, 2),
        "used_gib": round(vm.used / GIB, 2),
        "total_gib": round(vm.total / GIB, 2),
        # swap_free_gib and swap_used_pct no longer gate anything (see
        # PREFLIGHT_MIN_DISK_GIB) but stay in the snapshot as forensic signal
        # in the jsonl -- they are not dead fields.
        "swap_free_gib": round(swap.free / GIB, 2),
        "swap_used_pct": round(swap.percent, 2),
        "disk_free_gib": round(_disk_free_gib(), 2),
        "mps_driver_gib": round(mps_driver_gib, 2),
        "mps_current_gib": round(mps_current_gib, 2),
        "wired_gib": round(census["wired_gib"], 2),
        "ts": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        # Everything below is new. anon_gib/filebacked_gib in particular
        # gate nothing -- they are kept purely as forensic signal, since
        # their absence made the false-refusal investigation much harder.
        "free_gib": round(census["free_gib"], 2),
        "active_gib": round(census["active_gib"], 2),
        "inactive_gib": round(census["inactive_gib"], 2),
        "speculative_gib": round(census["speculative_gib"], 2),
        "purgeable_gib": round(census["purgeable_gib"], 2),
        "filebacked_gib": round(census["filebacked_gib"], 2),
        "anon_gib": round(census["anon_gib"], 2),
        "compressor_gib": round(census["compressor_gib"], 2),
        "pageable_gib": round(census["pageable_gib"], 2),
        "gpu_alloc_system_gib": round(census["gpu_alloc_system_gib"], 2),
        "gpu_alloc_self_gib": round(census["gpu_alloc_self_gib"], 2),
        "gpu_other_gib": round(census["gpu_other_gib"], 2),
        "mem_supply_gib": round(mem_supply_gib(census), 2),
        "swap_used_gib": round(swap.used / GIB, 2),
    }


def _disk_free_gib():
    # Free disk on the volume backing the swapfile; never raise -- return
    # 0.0 on any failure, matching the previous wired-memory helper's
    # convention (this one is fine to keep permissive: unlike gpu_other_gib,
    # understating disk_free_gib as 0.0 only makes G2/the sentinel MORE
    # conservative).
    try:
        return psutil.disk_usage("/").free / GIB
    except Exception:
        return 0.0


def preflight(stage_name, fraction, require_servers_down=True, *, skip_supply_gate=False):
    """Refuse to proceed if running this stage would risk the host.

    skip_supply_gate: measurement-sweep-only escape hatch for the G1b
    supply gate (see tests/measure_ltx_ceiling.py). Freeze-proofing in that
    context comes from the watermark cap + Sentinel, not G1b. Does not
    affect G0/G0b/G1a/G2, which always run and always raise.
    """
    if require_servers_down:
        # G0 -- vLLM residency.
        open_ports = []
        for port in VLLM_PORTS:
            try:
                sock = socket.create_connection(("127.0.0.1", port), timeout=1.0)
                sock.close()
                open_ports.append(port)
            except OSError:
                pass

        if open_ports:
            cap_gib = round(fraction * _recommended_max_gib(), 2)
            raise HostSafetyError(
                "HOST SAFETY REFUSAL: a vLLM server is listening on 127.0.0.1:%s.\n"
                "Stage %s needs %.2f GiB of MPS memory; the 27B server alone holds ~27 GiB.\n"
                "Run:  %s\n"
                "Then re-run. Afterwards restore with %s."
                % (
                    ",".join(str(p) for p in open_ports),
                    stage_name,
                    cap_gib,
                    HOST_PREP_SCRIPT,
                    HOST_RESTORE_SCRIPT,
                )
            )

        # G0b -- guard stand-down.
        if not os.path.exists(GUARD_STANDDOWN):
            raise HostSafetyError(
                "HOST SAFETY REFUSAL: the qwen-serve-guard launchd agent will restart the 27B\n"
                "server within 300 s (StartInterval=300), which would evict this run mid-flight.\n"
                "Create the stand-down file by running:  %s" % HOST_PREP_SCRIPT
            )

    # G1a -- other-process GPU memory (hard, no retry). Evaluated FIRST,
    # before snapshot(), so the refusal path stays cheap.
    census = _mem_census()
    if census["gpu_other_gib"] > PREFLIGHT_MAX_OTHER_GPU_GIB:
        lines = [
            "HOST SAFETY REFUSAL: another process holds too much GPU memory for stage %s." % stage_name,
            "Measured gpu_other_gib=%.2f GiB, threshold=%.2f GiB."
            % (census["gpu_other_gib"], PREFLIGHT_MAX_OTHER_GPU_GIB),
            "Another process holds GPU memory that this stage would have to share. "
            "Metal buffers are not visible in RSS, so `ps` will understate it.",
            "Run:  %s" % HOST_PREP_SCRIPT,
            "Then re-run. Afterwards restore with %s." % HOST_RESTORE_SCRIPT,
        ]
        # Best-effort per-process attribution via `footprint`. Wrapped so a
        # parsing surprise can never turn a clear refusal into a traceback.
        try:
            candidates = []
            for p in psutil.process_iter(["pid", "name", "memory_info"]):
                info = p.info
                mem = info.get("memory_info")
                if mem is not None and mem.rss >= 1 * GIB:
                    candidates.append((mem.rss, info.get("pid"), info.get("name")))
            candidates.sort(key=lambda t: t[0], reverse=True)
            for rss, pid, name in candidates[:8]:
                fp = subprocess.run(["footprint", "-p", str(pid)], capture_output=True, text=True)
                for fline in fp.stdout.splitlines():
                    if "IOAccelerator (graphics)" in fline:
                        lines.append("  pid=%s  %s  %s" % (pid, name, fline.strip()))
        except Exception:
            pass
        raise HostSafetyError("\n".join(lines))
    # No retry: another process's GPU reservations do not decay on a 60 s
    # timescale, unlike transient CPU-side pressure.

    # G1b -- host memory supply (hard). Reuses the census already sampled
    # for G1a above -- do NOT re-sample.
    #
    # Evidence measured 2026-08-25 (avail/supply at the gate):
    #   dance (succeeded):     avail=36.62  supply=~38     -> both PASS
    #   jump  (THRASHED):      avail=27.52  supply=38.05   -> supply ALONE
    #     passes; compressor grew 2.11->21.89 GiB, swap +5.21 GiB, sentinel
    #     aborted. mem_supply_gib() was thus measured to admit a thrashing
    #     run and must never again be used as the sole condition -- nor
    #     does excluding anon pages fix it (free+speculative+filebacked-
    #     gpu_other-reserve = 35.45 at the jump gate, still a false PASS).
    # A false refusal costs one retry; a false pass risks a host freeze
    # requiring a forced reboot (as happened on 2026-08-25). So the gate is
    # the CONJUNCTION of both metrics: it can never admit anything the
    # original psutil-only gate would have refused.
    cap_gib = fraction * _recommended_max_gib()
    required_gib = cap_gib + PREFLIGHT_OVERHEAD_GIB
    supply_gib = mem_supply_gib(census)
    avail_gib = psutil.virtual_memory().available / GIB
    gate_ok, arm_failures = _supply_gate_ok(avail_gib, supply_gib, required_gib)
    if not gate_ok and skip_supply_gate:
        # Sweep mode only (tests/measure_ltx_ceiling.py): G1b is redundant
        # belt-and-suspenders here -- the watermark cap + Sentinel are what
        # actually prevent a freeze, and over-ceiling cells are meant to be
        # recorded as clean OOM/sentinel_abort outcomes, not refused.
        print(
            "[mps_guard] G1b supply gate SKIPPED (sweep mode): avail=%.2f supply=%.2f "
            "required=%.2f -- relying on the watermark cap + sentinel"
            % (avail_gib, supply_gib, required_gib),
            file=sys.stderr,
        )
    elif not gate_ok:
        lines = [
            "HOST SAFETY REFUSAL: insufficient memory supply for stage %s." % stage_name,
        ]
        lines.extend(arm_failures)
        lines.append(
            "Measured avail=%.2f GiB, supply=%.2f GiB, required=%.2f GiB (cap=%.2f + overhead=%.2f)."
            % (avail_gib, supply_gib, required_gib, cap_gib, PREFLIGHT_OVERHEAD_GIB)
        )
        lines.append(
            "Both metrics must pass: psutil available is empirically the better predictor of "
            "thrashing, while mem_supply credits reclaimable file cache. Passing only one is not "
            "sufficient."
        )
        lines.append(
            "Census: pageable=%.2f gpu_other=%.2f os_reserve=%.2f free=%.2f active=%.2f "
            "inactive=%.2f speculative=%.2f wired=%.2f compressor=%.2f filebacked=%.2f"
            % (
                census["pageable_gib"],
                census["gpu_other_gib"],
                MEM_OS_RESERVE_GIB,
                census["free_gib"],
                census["active_gib"],
                census["inactive_gib"],
                census["speculative_gib"],
                census["wired_gib"],
                census["compressor_gib"],
                census["filebacked_gib"],
            )
        )
        try:
            procs = []
            for p in psutil.process_iter(["pid", "name", "memory_info"]):
                info = p.info
                mem = info.get("memory_info")
                if mem is not None:
                    procs.append((mem.rss, info.get("pid"), info.get("name")))
            procs.sort(key=lambda t: t[0], reverse=True)
            lines.append("Top processes by RSS:")
            for rss, pid, name in procs[:5]:
                lines.append("  %.2f GiB  pid=%s  %s" % (rss / GIB, pid, name))
        except Exception:
            pass
        raise HostSafetyError("\n".join(lines))

    # IMPORTANT: do NOT add a settle/retry loop here. An earlier design
    # called for one; it was measured and refuted -- availability did NOT
    # recover, staying pinned at ~31.2 GiB for 140 s of polling. A retry
    # loop would only add up to a minute of latency to every genuine
    # refusal.

    snap = snapshot()

    # G2 -- free disk (hard). Free swap itself is not gated on: macOS resizes
    # the swapfile dynamically, so free swap sits in a narrow ~1.5 GiB band
    # regardless of real memory pressure. Free disk is what swap can actually
    # grow into to absorb an allocation overshoot between two 2 s sentinel
    # samples, so disk is what is checked instead.
    if snap["disk_free_gib"] < PREFLIGHT_MIN_DISK_GIB:
        raise HostSafetyError(
            "HOST SAFETY REFUSAL: insufficient free disk for stage %s.\n"
            "Measured disk_free=%.2f GiB, required=%.2f GiB.\n"
            "Free disk bounds how far swap can grow to absorb an allocation overshoot\n"
            "between two 2 s sentinel samples."
            % (stage_name, snap["disk_free_gib"], PREFLIGHT_MIN_DISK_GIB)
        )

    print(
        "[mps_guard] preflight OK stage=%s cap=%sGiB required=%sGiB avail=%sGiB supply=%sGiB "
        "gpu_other=%sGiB wired=%sGiB comp=%sGiB disk_free=%sGiB"
        % (
            stage_name,
            round(cap_gib, 2),
            round(required_gib, 2),
            round(avail_gib, 2),
            round(supply_gib, 2),
            round(census["gpu_other_gib"], 2),
            snap["wired_gib"],
            snap["compressor_gib"],
            snap["disk_free_gib"],
        ),
        file=sys.stderr,
    )
    return snap


def _readiness(stage_name, fraction):
    """Evaluate G1a, G1b and G2 once, without raising.

    Backs the `readiness` CLI subcommand. Each entry in the returned
    "failures" list uses the same phrasing as the first line of the
    corresponding HostSafetyError raised by preflight(), so a later
    prep-script change can consume this without drifting from preflight().
    """
    census = _mem_census()
    cap_gib = fraction * _recommended_max_gib()
    required_gib = cap_gib + PREFLIGHT_OVERHEAD_GIB
    supply_gib = mem_supply_gib(census)
    avail_gib = psutil.virtual_memory().available / GIB
    disk_free_gib = _disk_free_gib()

    failures = []
    if census["gpu_other_gib"] > PREFLIGHT_MAX_OTHER_GPU_GIB:
        failures.append(
            "HOST SAFETY REFUSAL: another process holds too much GPU memory for stage %s." % stage_name
        )
    # G1b -- same conjunction as preflight(), via the shared helper, so this
    # can never drift from the HostSafetyError preflight() would raise.
    gate_ok, arm_failures = _supply_gate_ok(avail_gib, supply_gib, required_gib)
    if not gate_ok:
        failures.extend(arm_failures)
    if disk_free_gib < PREFLIGHT_MIN_DISK_GIB:
        failures.append(
            "HOST SAFETY REFUSAL: insufficient free disk for stage %s." % stage_name
        )

    return {
        "ready": len(failures) == 0,
        "stage": stage_name,
        "fraction": fraction,
        "cap_gib": round(cap_gib, 2),
        "required_gib": round(required_gib, 2),
        "avail_gib": round(avail_gib, 2),
        "supply_gib": round(supply_gib, 2),
        "gpu_other_gib": round(census["gpu_other_gib"], 2),
        "gpu_other_limit_gib": PREFLIGHT_MAX_OTHER_GPU_GIB,
        "disk_free_gib": round(disk_free_gib, 2),
        "disk_required_gib": PREFLIGHT_MIN_DISK_GIB,
        "failures": failures,
        "census": {k: round(v, 2) for k, v in census.items()},
    }


def _recommended_max_gib():
    import torch

    if torch.backends.mps.is_available():
        return torch.mps.recommended_max_memory() / GIB
    return 0.0


class Sentinel:
    """Background watchdog that samples memory and force-exits on danger.

    Uses os._exit() rather than raising because a daemon thread cannot
    interrupt an in-flight Metal kernel or a .to("mps") copy, graceful
    unwinding itself requires memory, and the driver reclaims all Metal
    buffers on process exit. Losing the partial run is the intended price.

    The MPS watermark cap is the PRIMARY backstop: a bounded fill stopped
    at the cap (a real run peaked at 30.09/30.70 GiB), and the 2026-08-25
    freeze happened at the 1.7 default, i.e. with no cap in effect at all.
    This sentinel is SECONDARY -- it exists for CPU-side allocation, which
    the watermark does not bound, and for another process arriving
    mid-run. A mem_supply_gib() abort trigger was considered here and
    deliberately NOT added, for lack of a calibrating healthy-run trace.
    max_compressor_gib is recorded without a trigger of its own because
    the compressor grew 8.27 GiB during a bounded, survivable allocation.

    The third trigger (swap) is a CONJUNCTION, not growth alone: growth-only
    misfired on a run aborted at 4.00 GiB absolute swap (growth +2.73 from a
    `sudo purge`-shrunk 1.27 GiB baseline) while a run that COMPLETED reached
    ~5.4 GiB absolute -- i.e. the aborted run never exceeded a known-good
    peak. It now fires only when growth is large AND absolute swap usage has
    passed SENTINEL_ABORT_SWAP_FLOOR_GIB. This deliberately makes the trigger
    LESS likely to fire, which is safe because: the MPS watermark cap (30.70
    GiB for stage 2) bounds GPU allocation regardless; the avail_gib < 4.0
    trigger is unchanged and was far from firing when this misfire occurred
    (avail was 16.32 at abort); and the disk trigger is unchanged. Residual
    uncertainty, noted honestly: the misfiring run showed compressor_gib at
    19.82, which may indicate genuine compression pressure, but this could
    not be compared against the successful run because that run's samples
    predate the compressor_gib field. max_compressor_gib is already recorded
    in peaks so a future comparison becomes possible.
    """

    def __init__(self, stage_name, run_dir):
        self.stage_name = stage_name
        self.run_dir = run_dir
        self.peak = {
            "mps_driver_gib": 0.0,
            "mps_current_gib": 0.0,
            "min_avail_gib": float("inf"),
            "min_swap_free_gib": float("inf"),
            "max_compressor_gib": 0.0,
            "min_supply_gib": float("inf"),
        }
        self._swap_used_start_gib = None
        self._stop_event = threading.Event()
        self._thread = None

    def start(self):
        os.makedirs(self.run_dir, exist_ok=True)
        self._swap_used_start_gib = psutil.swap_memory().used / GIB
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def _update_peak(self, s):
        self.peak["mps_driver_gib"] = max(self.peak["mps_driver_gib"], s["mps_driver_gib"])
        self.peak["mps_current_gib"] = max(self.peak["mps_current_gib"], s["mps_current_gib"])
        self.peak["min_avail_gib"] = min(self.peak["min_avail_gib"], s["avail_gib"])
        self.peak["min_swap_free_gib"] = min(self.peak["min_swap_free_gib"], s["swap_free_gib"])
        self.peak["max_compressor_gib"] = max(self.peak["max_compressor_gib"], s["compressor_gib"])
        self.peak["min_supply_gib"] = min(self.peak["min_supply_gib"], s["mem_supply_gib"])

    def _append_record(self, record):
        try:
            path = os.path.join(self.run_dir, "mem_%s.jsonl" % self.stage_name)
            data = (json.dumps(record) + "\n").encode("utf-8")
            fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
            try:
                os.write(fd, data)
            finally:
                os.close(fd)
        except Exception:
            pass

    def _loop(self):
        # Fail-safe posture (see SENTINEL_MAX_SAMPLE_FAILURES): snapshot()
        # can raise HostSafetyError on unexpected ioreg/vm_stat output. If
        # that exception escaped this daemon thread uncaught, the thread
        # would die silently and the stage would run on with no memory
        # backstop. So every tick's body is guarded: a failure is logged
        # and retried, and if sampling fails too many times in a row to be
        # trusted, the watchdog aborts the run itself -- it would rather
        # abort than run blind.
        consecutive_failures = 0
        while not self._stop_event.is_set():
            try:
                s = snapshot()
                self._update_peak(s)
                self._append_record(s)

                # avail_gib is lagging and non-monotonic in GPU residency -- in
                # run 20260825T145741Z-dance01 it read 8.45 at 23.17 GiB driver
                # then RECOVERED to 21.30 at 30.09 GiB driver -- so it is
                # retained here as a secondary CPU-side signal only; the MPS
                # watermark cap (see class docstring) is the primary backstop.
                # The disk trigger guards the case where swap cannot grow to
                # absorb an overshoot because the volume backing it is nearly
                # full. The swap-growth trigger below catches CPU-side
                # allocation growth that neither of the other two sees.
                # Swap decision is factored into _swap_abort() so it is
                # unit-testable offline (see tests/test_mps_guard_metric.py).
                swap_should_abort, swap_reason = _swap_abort(s["swap_used_gib"], self._swap_used_start_gib)
                if (
                    s["avail_gib"] < SENTINEL_ABORT_AVAIL_GIB
                    or s["disk_free_gib"] < SENTINEL_ABORT_DISK_GIB
                    or swap_should_abort
                ):
                    if s["avail_gib"] < SENTINEL_ABORT_AVAIL_GIB:
                        reason = "avail_gib=%.2f below %.1f" % (s["avail_gib"], SENTINEL_ABORT_AVAIL_GIB)
                    elif s["disk_free_gib"] < SENTINEL_ABORT_DISK_GIB:
                        reason = "disk_free_gib=%.2f below %.1f" % (s["disk_free_gib"], SENTINEL_ABORT_DISK_GIB)
                    else:
                        reason = swap_reason
                    self._append_record({"event": "sentinel_abort", "reason": reason, "snapshot": s})
                    sys.stderr.write(reason + "\n")
                    sys.stderr.flush()
                    os._exit(SENTINEL_EXIT_CODE)

                consecutive_failures = 0
            except Exception as e:
                consecutive_failures += 1
                sys.stderr.write(
                    "[mps_guard] Sentinel sample failed (%s: %s); retry %d/%d\n"
                    % (type(e).__name__, e, consecutive_failures, SENTINEL_MAX_SAMPLE_FAILURES)
                )
                sys.stderr.flush()
                if consecutive_failures >= SENTINEL_MAX_SAMPLE_FAILURES:
                    last_error = "%s: %s" % (type(e).__name__, e)
                    reason = (
                        "%d consecutive sample failures; cannot guarantee memory safety"
                        % consecutive_failures
                    )
                    self._append_record({
                        "event": "sentinel_abort",
                        "reason": reason,
                        "last_error": last_error,
                    })
                    sys.stderr.write(reason + "\n")
                    sys.stderr.flush()
                    os._exit(SENTINEL_EXIT_CODE)

            self._stop_event.wait(SENTINEL_INTERVAL_S)

    def stop(self):
        import torch

        # In-flight command buffers hold buffer references, so the final
        # sample would otherwise understate the peak.
        if torch.backends.mps.is_available():
            torch.mps.synchronize()

        s = snapshot()
        self._update_peak(s)

        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=5.0)

        return {k: round(v if v != float("inf") else 0.0, 2) for k, v in self.peak.items()}

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.stop()
        return False


def write_peaks(run_dir, stage_name, peaks):
    os.makedirs(run_dir, exist_ok=True)
    path = os.path.join(run_dir, "peaks_%s.json" % stage_name)
    with open(path, "w") as f:
        f.write(json.dumps(peaks, indent=2))


if __name__ == "__main__":
    args = sys.argv[1:]

    if len(args) == 2 and args[0] == "watermark":
        print(json.dumps(set_watermark(float(args[1]))))
    elif len(args) == 1 and args[0] == "snapshot":
        print(json.dumps(snapshot()))
    elif len(args) == 1 and args[0] == "census":
        print(json.dumps({k: round(v, 2) for k, v in _mem_census().items()}))
    elif len(args) == 3 and args[0] == "preflight":
        try:
            preflight(args[1], float(args[2]))
            print("OK")
        except HostSafetyError as e:
            print(str(e), file=sys.stderr)
            sys.exit(2)
    elif len(args) == 3 and args[0] == "readiness":
        result = _readiness(args[1], float(args[2]))
        print(json.dumps(result))
        sys.exit(0 if result["ready"] else 1)
    else:
        print(
            "usage: mps_guard.py {watermark <fraction>|snapshot|census|"
            "preflight <stage> <fraction>|readiness <stage> <fraction>}",
            file=sys.stderr,
        )
        sys.exit(1)
