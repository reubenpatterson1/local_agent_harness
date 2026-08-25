"""Sweep tool: measure LTX-Video stage-2 resolution/frame ceilings.

Two modes:
  sweep (default) -- runs a grid of (width, height, num_frames) cells, each
      a REAL stage-2 subprocess reusing one precomputed embeds.pt, and
      appends one JSONL result per cell to generated/ltx_ceiling/results.jsonl.
  --reduce -- reads results.jsonl and writes ltx_ceiling.json (the table
      consulted by ltx_video_skill._check_ceiling).

This is an operator tool, not a pytest suite: it needs a prepped host and
real GPU work, mirroring the manual-verification posture of the existing
mps_guard specs.

Operator flow:
    bin/ltx-host-prep                       # stop servers, stand-down, purge
    python3 tests/measure_ltx_ceiling.py    # runs stage1 once, then sweeps
    python3 tests/measure_ltx_ceiling.py --reduce   # writes ltx_ceiling.json
    bin/ltx-host-restore                    # bring servers back

Freeze-proofness (why this sweep cannot repeat the 2026-08-25 freeze):
  1. Each cell is the REAL stage 2, which calls mps_guard.set_watermark(0.82)
     as its first act, setting torch.mps.set_per_process_memory_fraction(0.82)
     -- a HARD cap. An over-ceiling allocation fails as a caught Metal
     RuntimeError (clean nonzero exit); it cannot grow past the cap into a
     freeze. The 2026-08-25 freeze happened at the 1.7 default, i.e. with NO
     cap in effect at all; here every cell has the cap.
  2. The stage-2 Sentinel runs in every cell, backstopping CPU-side growth
     the watermark does not bound (os._exit(75)).
  3. Each cell is its own subprocess; a cell that os._exit()s or segfaults
     cannot corrupt the sweep loop or the next cell. The parent only reads
     the child's rc + on-disk artifacts.
  4. Cells set LTX_SWEEP_RELAX_SUPPLY=1, which relaxes only the G1b supply
     gate inside preflight (by design -- G1b's fixed requirement refuses
     small cells whose real cost never approaches it, because stage 1's
     mmap of the T5 shards depresses available memory). G0/G0b/G1a/G2 still
     run and still raise unconditionally. Freeze-proofing in this relaxed
     context comes from (1) the watermark cap, (2) the Sentinel, and (3)
     subprocess isolation above -- not from G1b -- and over-ceiling cells
     are recorded as clean oom/sentinel_abort outcomes, which is the data
     this sweep exists to collect.
"""

import argparse
import datetime
import glob
import itertools
import json
import os
import shutil
import socket
import subprocess
import sys
import time
import uuid

import psutil

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import ltx_video_skill  # noqa: E402
import mps_guard  # noqa: E402

DEFAULT_RESOLUTIONS = [(384, 384), (448, 448), (512, 512), (576, 576), (640, 640), (704, 480), (704, 704)]
DEFAULT_FRAMES = [49, 57, 73, 97, 121]  # ascending; (n-1) % 8 == 0 for all
DEFAULT_IMAGE = "/Users/reubenpatterson/qwen-agent-workspace/z_image_test.png"
DEFAULT_PROMPT = "a gentle slow camera push-in, subtle natural motion"
DEFAULT_TABLE_OUT = "/Users/reubenpatterson/qwen-agent-workspace/ltx_ceiling.json"
DEFAULT_MARGIN = 0.95

CEILING_DIR = os.path.join(ltx_video_skill._THIS_DIR, "generated", "ltx_ceiling")
DEFAULT_RESULTS_PATH = os.path.join(CEILING_DIR, "results.jsonl")

USAGE = """usage:
  python3 tests/measure_ltx_ceiling.py
      [--resolutions "WxH,WxH,..."]   # default: see module docstring
      [--frames "49,57,73,97,121"]    # default ascending list
      [--image PATH]                  # default: %s
      [--prompt "..."]                # default: %r
      [--out PATH]                    # default: generated/ltx_ceiling/results.jsonl
      [--dry-run]                     # print the filtered grid and exit, run nothing
      [--skip-stage1-if-present]      # reuse an existing base embeds.pt instead of re-encoding

  python3 tests/measure_ltx_ceiling.py --reduce [RESULTS_PATH] [--table-out PATH] [--margin 0.95]
      # RESULTS_PATH default: generated/ltx_ceiling/results.jsonl
      # --table-out default: %s
      # --margin default: 0.95""" % (DEFAULT_IMAGE, DEFAULT_PROMPT, DEFAULT_TABLE_OUT)


def _parse_resolutions(s):
    """Parse 'WxH,WxH,...' -> [(w,h), ...]. Raise ValueError on malformed input."""
    out = []
    for token in s.split(","):
        token = token.strip()
        if "x" not in token:
            raise ValueError("malformed --resolutions token %r: expected WxH" % token)
        w_s, h_s = token.split("x", 1)
        out.append((int(w_s), int(h_s)))
    return out


def _parse_frames(s):
    """Parse '49,57,73' -> [49, 57, 73]. Raise ValueError on malformed input."""
    return [int(tok.strip()) for tok in s.split(",")]


def _filtered_grid(resolutions, frames):
    """Return [(w,h,n), ...] filtered through ltx_video_skill._validate_geometry,
    dropping (and printing a note for) any cell that fails. Frames are
    always ascending per resolution, to enable the sweep's early-exit.
    """
    grid = []
    for (w, h) in resolutions:
        for n in sorted(frames):
            try:
                ltx_video_skill._validate_geometry(w, h, n)
            except ValueError as e:
                print("[measure_ltx_ceiling] dropping %dx%dx%d: %s" % (w, h, n, e))
                continue
            grid.append((w, h, n))
    return grid


def _print_grid(grid):
    print("Filtered grid (%d cells):" % len(grid))
    for (w, h, n) in grid:
        print("  %dx%dx%d" % (w, h, n))


def _open_vllm_ports():
    open_ports = []
    for port in mps_guard.VLLM_PORTS:
        try:
            sock = socket.create_connection(("127.0.0.1", port), timeout=1.0)
            sock.close()
            open_ports.append(port)
        except OSError:
            pass
    return open_ports


def _sentinel_reason(run_dir, stage_name):
    path = os.path.join(run_dir, "mem_%s.jsonl" % stage_name)
    try:
        with open(path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                rec = json.loads(line)
                if rec.get("event") == "sentinel_abort":
                    return rec.get("reason")
    except OSError:
        pass
    return None


def _swap_growth(run_dir, stage_name):
    path = os.path.join(run_dir, "mem_%s.jsonl" % stage_name)
    first = None
    last = None
    try:
        with open(path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                rec = json.loads(line)
                if "swap_used_gib" in rec:
                    if first is None:
                        first = rec["swap_used_gib"]
                    last = rec["swap_used_gib"]
    except OSError:
        pass
    if first is None or last is None:
        return 0.0
    return round(last - first, 2)


def _await_gpu_reclaim(timeout_s=30.0, poll_s=1.5, cell_label=None):
    """Wait until foreign GPU allocation falls below the G1a threshold, so a
    just-killed cell's still-reclaiming Metal buffers don't trip the NEXT
    cell's preflight G1a. Returns the final gpu_other_gib. Best-effort: on
    timeout it returns the last reading and lets the cell's own preflight
    decide (a genuinely stuck >8 GiB will then still refuse)."""
    t_start = time.monotonic()
    deadline = t_start + timeout_s
    first = None
    last = None
    while True:
        c = mps_guard._mem_census()
        last = c["gpu_other_gib"]
        if first is None:
            first = last
        if last <= mps_guard.PREFLIGHT_MAX_OTHER_GPU_GIB:
            if first > mps_guard.PREFLIGHT_MAX_OTHER_GPU_GIB:
                print(
                    "[measure_ltx_ceiling] waiting for GPU reclaim before %s: "
                    "gpu_other=%.2f -> %.2f (%.1fs)"
                    % (cell_label, first, last, time.monotonic() - t_start)
                )
            return last
        if time.monotonic() >= deadline:
            return last
        time.sleep(poll_s)


def _base_request(image_path, prompt, width, height, num_frames):
    abs_image_path = os.path.abspath(image_path)
    return {
        "image_path": abs_image_path,
        "prompt": prompt,
        "negative_prompt": ltx_video_skill.DEFAULT_NEGATIVE_PROMPT,
        "output_path": None,
        "width": width,
        "height": height,
        "num_frames": num_frames,
        "num_inference_steps": ltx_video_skill.DEFAULT_STEPS,
        "guidance_scale": ltx_video_skill.DEFAULT_GUIDANCE,
        "fps": ltx_video_skill.DEFAULT_FPS,
        "frame_rate": ltx_video_skill.DEFAULT_FRAME_RATE,
        "seed": 0,
        "wide": False,
        "conditions": [{"image_path": abs_image_path, "frame_index": 0, "strength": 1.0}],
    }


def _find_or_create_base_dir(image_path, prompt, grid, skip_stage1_if_present):
    """Encode stage 1 once (Section 9.4 step 1) and return the base run dir.

    Geometry is irrelevant to embeds (I2), but a valid request.json is
    required, so the first geometry in the (already-filtered) grid is used.
    """
    if skip_stage1_if_present:
        existing = sorted(glob.glob(os.path.join(CEILING_DIR, "_base-*")))
        for candidate in reversed(existing):
            if os.path.isfile(os.path.join(candidate, "embeds.pt")):
                print("[measure_ltx_ceiling] reusing existing base dir: %s" % candidate)
                return candidate

    first_w, first_h, first_n = grid[0]
    run_id = "_base-%s-%s" % (
        datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ"),
        uuid.uuid4().hex[:8],
    )
    base_dir = os.path.join(CEILING_DIR, run_id)
    os.makedirs(base_dir)

    request = _base_request(image_path, prompt, first_w, first_h, first_n)
    with open(os.path.join(base_dir, "request.json"), "w") as f:
        json.dump(request, f, indent=2)

    proc = subprocess.run(
        [sys.executable, ltx_video_skill.__file__, "--stage", "1", "--run-dir", base_dir],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    if proc.returncode != 0:
        sys.stderr.write(proc.stdout or "")
        print(
            "[measure_ltx_ceiling] ABORTING: stage 1 encode failed (rc=%d)" % proc.returncode,
            file=sys.stderr,
        )
        sys.exit(1)

    print("[measure_ltx_ceiling] base dir encoded: %s" % base_dir)
    return base_dir


def _run_cell(w, h, n, base_embeds, image_path, prompt, cap_gib, out_path):
    """Run one real stage-2 cell in its own subprocess (Section 9.4 step 2)."""
    cell_id = "%dx%dx%d-%s" % (w, h, n, uuid.uuid4().hex[:8])
    cell_dir = os.path.join(CEILING_DIR, cell_id)
    os.makedirs(cell_dir)
    shutil.copyfile(base_embeds, os.path.join(cell_dir, "embeds.pt"))

    request = _base_request(image_path, prompt, w, h, n)
    with open(os.path.join(cell_dir, "request.json"), "w") as f:
        json.dump(request, f, indent=2)

    t0 = time.monotonic()
    # Relax G1b for this cell only: stage 1's mmap of the T5 shards leaves
    # reclaimable file cache that depresses avail below the fixed G1b
    # requirement even for small cells. The watermark cap + Sentinel remain
    # in force and are what actually prevent a freeze; see module docstring.
    cell_env = os.environ.copy()
    cell_env["LTX_SWEEP_RELAX_SUPPLY"] = "1"
    reclaim_gib = _await_gpu_reclaim(cell_label="%dx%dx%d" % (w, h, n))
    proc = subprocess.run(
        [sys.executable, ltx_video_skill.__file__, "--stage", "2", "--run-dir", cell_dir],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        env=cell_env,
    )
    wall_s = time.monotonic() - t0
    log = proc.stdout or ""

    peaks_path = os.path.join(cell_dir, "peaks_stage2.json")
    peaks = None
    if os.path.isfile(peaks_path):
        with open(peaks_path) as f:
            peaks = json.load(f)

    if proc.returncode == 0:
        outcome = "completed"
        sentinel_reason = None
    elif proc.returncode == mps_guard.SENTINEL_EXIT_CODE:
        outcome = "sentinel_abort"
        sentinel_reason = _sentinel_reason(cell_dir, "stage2")
    elif (
        "HOST SAFETY REFUSAL:" in log
        and "another process holds too much GPU memory" in log
        and reclaim_gib > mps_guard.PREFLIGHT_MAX_OTHER_GPU_GIB
    ):
        # G1a refused because foreign GPU memory was still above threshold
        # even after _await_gpu_reclaim's poll window. This is a slow-reclaim
        # condition, not a mis-prepped host: record it and let the sweep
        # continue to the next resolution rather than aborting entirely.
        print(log)
        print(
            "[measure_ltx_ceiling] cell %dx%dx%d: host GPU busy after reclaim "
            "wait (gpu_other=%.2f GiB); continuing sweep"
            % (w, h, n, reclaim_gib)
        )
        outcome = "host_gpu_busy"
        sentinel_reason = None
    elif "HOST SAFETY REFUSAL:" in log:
        print(log)
        print(
            "[measure_ltx_ceiling] ABORTING sweep: host not ready "
            "(HOST SAFETY REFUSAL in cell %s)" % cell_dir,
            file=sys.stderr,
        )
        sys.exit(3)
    else:
        outcome = "oom_or_error"
        sentinel_reason = None

    swap_growth_gib = _swap_growth(cell_dir, "stage2")
    latent_frames = (n - 1) // 8 + 1
    tokens = latent_frames * (w // 32) * (h // 32)

    # results.jsonl "outcome" field: one of
    #   "completed"      -- rc == 0, real measurement
    #   "sentinel_abort"  -- Sentinel os._exit(75)'d the child
    #   "oom_or_error"    -- nonzero rc, no sentinel, no HOST SAFETY REFUSAL
    #   "host_gpu_busy"   -- G1a refused on foreign GPU memory that was still
    #                        above threshold after _await_gpu_reclaim's poll
    #                        window; the sweep continues to the next
    #                        resolution rather than aborting (see module
    #                        docstring / _run_cell above)
    record = {
        "width": w,
        "height": h,
        "num_frames": n,
        "latent_frames": latent_frames,
        "tokens": tokens,
        "outcome": outcome,
        "peak_mps_driver_gib": peaks.get("mps_driver_gib") if peaks else None,
        "min_supply_gib": peaks.get("min_supply_gib") if peaks else None,
        "max_compressor_gib": peaks.get("max_compressor_gib") if peaks else None,
        "swap_growth_gib": swap_growth_gib,
        "cap_gib": round(cap_gib, 2),
        "wall_s": round(wall_s, 1),
        "rc": proc.returncode,
        "sentinel_reason": sentinel_reason,
        "ts": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }

    with open(out_path, "a") as f:
        f.write(json.dumps(record) + "\n")
        f.flush()

    # Frames are large; delete them, but keep request.json/mem_stage2.jsonl/
    # peaks_stage2.json/stage2.log for forensics.
    frames_dir = os.path.join(cell_dir, "frames")
    if os.path.isdir(frames_dir):
        shutil.rmtree(frames_dir, ignore_errors=True)

    print(
        "[measure_ltx_ceiling] %dx%dx%d -> %s (rc=%d, wall=%.1fs)"
        % (w, h, n, outcome, proc.returncode, wall_s)
    )
    return record


def _print_summary(results, cap_gib):
    print()
    print(
        "%-12s | %-6s | %-14s | %-8s | %-8s | %-8s | %-9s | %-8s"
        % ("WxH", "frames", "outcome", "peak_drv", "comp", "supply", "swap_grow", "wall_s")
    )
    for r in sorted(results, key=lambda r: (r["width"], r["height"], r["num_frames"])):
        print(
            "%-12s | %-6d | %-14s | %-8s | %-8s | %-8s | %-9s | %-8s"
            % (
                "%dx%d" % (r["width"], r["height"]),
                r["num_frames"],
                r["outcome"],
                "%.2f" % r["peak_mps_driver_gib"] if r["peak_mps_driver_gib"] is not None else "-",
                "%.2f" % r["max_compressor_gib"] if r["max_compressor_gib"] is not None else "-",
                "%.2f" % r["min_supply_gib"] if r["min_supply_gib"] is not None else "-",
                "%.2f" % r["swap_growth_gib"],
                "%.1f" % r["wall_s"],
            )
        )

    print()
    by_res = {}
    for r in results:
        by_res.setdefault((r["width"], r["height"]), []).append(r)
    for (w, h) in sorted(by_res.keys()):
        rows = by_res[(w, h)]
        qualifying = [
            r["num_frames"]
            for r in rows
            if r["outcome"] == "completed"
            and r["peak_mps_driver_gib"] is not None
            and r["peak_mps_driver_gib"] <= 0.95 * cap_gib
        ]
        if qualifying:
            print("MAX COMPLETING <= 0.95*cap: %dx%d -> %d frames" % (w, h, max(qualifying)))
        else:
            print("MAX COMPLETING <= 0.95*cap: %dx%d -> none" % (w, h))


def _run_sweep(grid, base_dir, out_path, cap_gib, image_path, prompt):
    base_embeds = os.path.join(base_dir, "embeds.pt")
    results = []

    for (w, h), cells in itertools.groupby(grid, key=lambda c: (c[0], c[1])):
        stop_escalating = False
        for (cw, ch, n) in cells:
            if stop_escalating:
                print(
                    "[measure_ltx_ceiling] skipping %dx%dx%d: earlier n at this "
                    "resolution did not complete cleanly under cap" % (cw, ch, n)
                )
                continue
            record = _run_cell(cw, ch, n, base_embeds, image_path, prompt, cap_gib, out_path)
            results.append(record)
            peak = record["peak_mps_driver_gib"]
            if record["outcome"] != "completed" or (peak is not None and peak > cap_gib):
                stop_escalating = True

    _print_summary(results, cap_gib)


def _sweep_main(args):
    try:
        resolutions = _parse_resolutions(args.resolutions) if args.resolutions else DEFAULT_RESOLUTIONS
        frames = _parse_frames(args.frames) if args.frames else DEFAULT_FRAMES
    except ValueError as e:
        print("error: %s" % e, file=sys.stderr)
        print(USAGE, file=sys.stderr)
        sys.exit(2)

    grid = _filtered_grid(resolutions, frames)

    if args.dry_run:
        _print_grid(grid)
        return 0

    if not grid:
        print("[measure_ltx_ceiling] filtered grid is empty; nothing to sweep")
        return 0

    open_ports = _open_vllm_ports()
    if open_ports:
        print(
            "REFUSING: vLLM server(s) up on %s. Run bin/ltx-host-prep first."
            % ", ".join(str(p) for p in open_ports),
            file=sys.stderr,
        )
        sys.exit(2)

    os.makedirs(CEILING_DIR, exist_ok=True)

    import torch

    if not torch.backends.mps.is_available():
        print("REFUSING: MPS not available; the sweep measures MPS behavior.", file=sys.stderr)
        sys.exit(2)

    cap_gib = mps_guard.FRACTION_STAGE2 * mps_guard._recommended_max_gib()

    out_path = args.out or DEFAULT_RESULTS_PATH
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)

    base_dir = _find_or_create_base_dir(args.image, args.prompt, grid, args.skip_stage1_if_present)

    _run_sweep(grid, base_dir, out_path, cap_gib, args.image, args.prompt)
    return 0


def _modal(values):
    from collections import Counter

    return Counter(values).most_common(1)[0][0]


def _diffusers_version():
    import diffusers

    return diffusers.__version__


def _reduce_main(args):
    results_path = args.results_path or DEFAULT_RESULTS_PATH

    rows = []
    with open(results_path) as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))

    margin = args.margin

    by_res = {}
    for r in rows:
        by_res.setdefault((r["width"], r["height"]), []).append(r)

    cap_values = [r["cap_gib"] for r in rows if r.get("cap_gib") is not None]

    ceiling = {}
    omitted = []
    for (w, h) in sorted(by_res.keys()):
        group = by_res[(w, h)]
        qualifying = [
            r
            for r in group
            if r["outcome"] == "completed"
            and r.get("peak_mps_driver_gib") is not None
            and r["peak_mps_driver_gib"] <= margin * r["cap_gib"]
        ]
        if qualifying:
            best = max(qualifying, key=lambda r: r["num_frames"])
            ceiling["%dx%d" % (w, h)] = best["num_frames"]
            print(
                "%dx%d -> %d frames (peak %.2f GiB)"
                % (w, h, best["num_frames"], best["peak_mps_driver_gib"])
            )
        else:
            omitted.append("%dx%d" % (w, h))

    if omitted:
        print("Omitted (no qualifying row): %s" % ", ".join(omitted))

    # measured_resolutions: every WxH with >=1 row in results.jsonl,
    # regardless of outcome. This is distinct from `ceiling`'s keys: a
    # resolution can appear here but be absent from `ceiling` because it WAS
    # measured but its best run missed the safety margin. Consulted by
    # ltx_video_skill._check_ceiling to distinguish "measured but omitted"
    # (refuse) from "truly unmeasured" (bound by a smaller measured
    # resolution).
    measured_resolutions = sorted("%dx%d" % (w, h) for (w, h) in by_res.keys())

    table = {
        "meta": {
            "generated_from": os.path.relpath(
                os.path.abspath(results_path), ltx_video_skill._THIS_DIR
            ),
            "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "fraction": mps_guard.FRACTION_STAGE2,
            "wide": False,
            "conditioning": "frame0-only",
            "cap_gib": _modal(cap_values) if cap_values else None,
            "safety_margin_frac": margin,
            "host_total_gib": round(psutil.virtual_memory().total / mps_guard.GIB, 2),
            "diffusers_version": _diffusers_version(),
            "measured_resolutions": measured_resolutions,
        },
        "ceiling": ceiling,
    }

    table_out = args.table_out
    with open(table_out, "w") as f:
        json.dump(table, f, indent=2)

    print("Wrote %s" % table_out)
    return 0


def _build_arg_parser():
    p = argparse.ArgumentParser(add_help=True)
    p.add_argument("results_path", nargs="?", default=None)
    p.add_argument("--resolutions", default=None)
    p.add_argument("--frames", default=None)
    p.add_argument("--image", default=DEFAULT_IMAGE)
    p.add_argument("--prompt", default=DEFAULT_PROMPT)
    p.add_argument("--out", default=None)
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--skip-stage1-if-present", action="store_true")
    p.add_argument("--reduce", action="store_true")
    p.add_argument("--table-out", default=DEFAULT_TABLE_OUT)
    p.add_argument("--margin", type=float, default=DEFAULT_MARGIN)
    return p


def main():
    args = _build_arg_parser().parse_args()
    if args.reduce:
        return _reduce_main(args)
    return _sweep_main(args)


if __name__ == "__main__":
    sys.exit(main())
