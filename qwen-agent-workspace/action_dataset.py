#!/usr/bin/env python3
"""action_dataset -- build an action LoRA's clip dataset (Phase 2 of
docs/superpowers/specs/2026-10-20-action-lora-motion-library-design.md).

Ingests operator-supplied reference clips of ONE action by varied performers,
normalizes each to the training geometry/fps/frame-lattice with ffmpeg, writes an
appearance-free caption per clip, builds a review contact sheet, enforces the
identity-agnostic performer-count check, and writes action.json (status
"dataset"). Training (ltx-2-mlx) is Phase 3.

Top-level imports are stdlib + PIL; ffmpeg/ffprobe are invoked as subprocesses
(the host already ships them, like judge-clips and wrap_still). Parallels
character_dataset.py but for multi-frame clips instead of stills.
"""

import argparse
import glob
import hashlib
import importlib.machinery
import json
import math
import os
import shlex
import shutil
import subprocess
import sys

from PIL import Image

WS = os.path.dirname(os.path.realpath(__file__))

# Default training geometry (overridable per run). Width/height are multiples of
# 64 and frames sit on the 8k+1 lattice, matching validate_geometry below.
DEFAULT_WIDTH = 768
DEFAULT_HEIGHT = 768
DEFAULT_FRAMES = 97          # 8*12 + 1 = 97; 96/24 = 4.0 s
DEFAULT_FPS = 24
CONTACT_COLS = 4
CREATE_MIN_FREE_GIB = 2.0


def _load_action_lib():
    return importlib.machinery.SourceFileLoader(
        "action_lib", os.path.join(WS, "action_lib.py")).load_module()


class DatasetError(Exception):
    """A dataset-building failure; printed after "Error: "."""


def _resolve(tool, env):
    return (os.environ.get(env) or shutil.which(tool)
            or os.path.join("/opt/homebrew/bin", tool))


FFMPEG = _resolve("ffmpeg", "FFMPEG")
FFPROBE = _resolve("ffprobe", "FFPROBE")


def validate_geometry(width, height, frames):
    """Width/height multiples of 64 (>= 64); frames on the 8k+1 lattice (>= 9).
    Mirrors ltx2_mlx_video_skill.validate_geometry so a dataset matches what the
    DiT trains/renders at."""
    if width % 64 or width < 64:
        raise DatasetError("width must be a multiple of 64 and >= 64, got %d" % width)
    if height % 64 or height < 64:
        raise DatasetError("height must be a multiple of 64 and >= 64, got %d" % height)
    if (frames - 1) % 8 or frames < 9:
        raise DatasetError("frames must satisfy (frames-1) %% 8 == 0 and frames >= 9, got %d" % frames)


def snap_frames(n):
    """The largest 8k+1 frame count <= n (and >= 9)."""
    if n < 9:
        return 9
    return ((n - 1) // 8) * 8 + 1


def _run(cmd, what):
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        tail = (res.stderr or res.stdout).strip().splitlines()[-4:]
        raise DatasetError("%s failed (%s): %s" % (what, os.path.basename(cmd[0]), " | ".join(tail)))
    return res


def probe_clip(path):
    """(width, height, nb_frames, duration_s) for a video file via ffprobe."""
    res = _run([FFPROBE, "-v", "error", "-select_streams", "v:0",
                "-show_entries", "stream=width,height,nb_frames,duration",
                "-of", "json", path], "ffprobe")
    try:
        s = json.loads(res.stdout)["streams"][0]
        dur = float(s.get("duration") or 0.0)
        nb = int(s["nb_frames"]) if str(s.get("nb_frames", "")).isdigit() else int(round(dur * DEFAULT_FPS))
        return int(s["width"]), int(s["height"]), nb, dur
    except (KeyError, IndexError, ValueError) as e:
        raise DatasetError("%s: not a readable video (%s)" % (path, e))


def normalize_clip(src, dst, width, height, frames, fps=DEFAULT_FPS):
    """Re-encode src to exactly width x height, fps, and `frames` frames (scaled to
    fill then center-cropped), writing dst (mp4, yuv420p)."""
    vf = ("fps=%d,scale=%d:%d:force_original_aspect_ratio=increase,crop=%d:%d"
          % (fps, width, height, width, height))
    _run([FFMPEG, "-y", "-i", src, "-vf", vf, "-frames:v", str(frames),
          "-an", "-pix_fmt", "yuv420p", "-c:v", "libx264", "-preset", "veryfast", dst],
         "ffmpeg normalize")
    if not (os.path.isfile(dst) and os.path.getsize(dst) > 0):
        raise DatasetError("%s: ffmpeg produced no output" % dst)


def extract_frame(clip, dst_png, at_frac=0.5):
    """Write one frame (at `at_frac` of the clip) of `clip` to dst_png."""
    w, h, nb, dur = probe_clip(clip)
    ts = max(0.0, (dur or 0.0) * at_frac)
    _run([FFMPEG, "-y", "-ss", "%.3f" % ts, "-i", clip, "-frames:v", "1", dst_png],
         "ffmpeg extract-frame")


def write_contact_sheet(frame_pngs, out_path, cols=CONTACT_COLS):
    """A labeled grid of one frame per clip."""
    imgs = [Image.open(p).convert("RGB") for p in frame_pngs if os.path.isfile(p)]
    if not imgs:
        Image.new("RGB", (320, 120), (20, 20, 20)).save(out_path)
        return
    cw = 320
    def thumb(im): w, h = im.size; return im.resize((cw, max(1, int(h * cw / w))))
    imgs = [thumb(im) for im in imgs]
    rh = max(im.size[1] for im in imgs)
    rows = math.ceil(len(imgs) / cols)
    sheet = Image.new("RGB", (cw * cols, rh * rows), (20, 20, 20))
    for i, im in enumerate(imgs):
        sheet.paste(im, ((i % cols) * cw, (i // cols) * rh))
    sheet.save(out_path, quality=90)


def _sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def _free_gib(path):
    try:
        st = os.statvfs(path)
        return st.f_bavail * st.f_frsize / (1024 ** 3)
    except OSError:
        return 0.0


def build_dataset(name, trigger, descriptor, clip_paths, performers, *,
                  width=DEFAULT_WIDTH, height=DEFAULT_HEIGHT, frames=DEFAULT_FRAMES,
                  fps=DEFAULT_FPS, force=False):
    """Normalize clips, caption, contact-sheet, and write action.json. Returns the
    action.json dict. Raises DatasetError. Does not train."""
    lib = _load_action_lib()
    lib.validate_name(name)
    lib.validate_trigger(trigger)
    lib.validate_descriptor(descriptor)
    validate_geometry(width, height, frames)

    missing = [p for p in clip_paths if not (os.path.isfile(p) and os.access(p, os.R_OK))]
    if missing:
        raise DatasetError("unreadable clip(s): %s" % ", ".join(missing))

    identity_agnostic = performers >= lib.MIN_PERFORMERS
    if not identity_agnostic and not force:
        raise DatasetError("only %d performer(s) asserted; an action LoRA needs >= %d distinct "
                           "performers to stay identity-agnostic (or pass --force to proceed, "
                           "recording identity_agnostic=false)" % (performers, lib.MIN_PERFORMERS))

    adir = lib.action_dir(name)
    dataset_dir = os.path.join(adir, "dataset")
    clips_dir = os.path.join(dataset_dir, "clips")
    captions_dir = os.path.join(dataset_dir, "captions")
    for d in (clips_dir, captions_dir, os.path.join(adir, "loras", "video"), os.path.join(adir, "logs")):
        os.makedirs(d, exist_ok=True)
    if _free_gib(adir) < CREATE_MIN_FREE_GIB:
        raise DatasetError("less than %.0f GiB free at %s" % (CREATE_MIN_FREE_GIB, adir))

    frame_pngs = []
    kept = 0
    for i, src in enumerate(clip_paths):
        w, h, nb, dur = probe_clip(src)
        clip_frames = min(frames, snap_frames(nb)) if nb else frames
        dst = os.path.join(clips_dir, "clip_%02d.mp4" % i)
        normalize_clip(src, dst, width, height, clip_frames, fps)
        with open(os.path.join(captions_dir, "clip_%02d.txt" % i), "w", encoding="utf-8") as f:
            f.write(trigger)                      # appearance-free: the motion phrase only
        png = os.path.join(dataset_dir, "_frame_%02d.png" % i)
        try:
            extract_frame(dst, png)
            frame_pngs.append(png)
        except DatasetError:
            pass
        kept += 1

    sheet = os.path.join(dataset_dir, "contact_sheet.jpg")
    write_contact_sheet(frame_pngs, sheet)
    for p in frame_pngs:                          # the per-clip frames were only for the sheet
        try:
            os.unlink(p)
        except OSError:
            pass

    data = lib.new_action(name, trigger, descriptor, clip_paths,
                          identity_agnostic=identity_agnostic)
    data["dataset"] = {"clips": kept, "performers": performers, "width": width,
                       "height": height, "frames": frames, "fps": fps,
                       "contact_sheet": sheet}
    lib.write_action(data)

    manifest = {"name": name, "trigger": trigger, "descriptor": descriptor,
                "clips": kept, "performers": performers, "identity_agnostic": identity_agnostic,
                "width": width, "height": height, "frames": frames, "fps": fps,
                "sources": [os.path.abspath(p) for p in clip_paths]}
    with open(os.path.join(dataset_dir, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)
    return data


def create(args):
    """bin/action create. Returns 0, 2 (bad input) or 3 (fewer than MIN_CLIPS)."""
    lib = _load_action_lib()
    try:
        lib.validate_name(args.name)
    except lib.ActionError as e:
        return _error(str(e))
    if not args.regenerate and os.path.exists(lib.action_json_path(args.name)):
        return _error("action %s already exists; use --regenerate to rebuild" % args.name)
    if not args.clips or not args.trigger or not args.descriptor:
        return _error("create needs --trigger, --descriptor and at least one --clip")
    try:
        data = build_dataset(args.name, args.trigger, args.descriptor, args.clips,
                             args.performers, width=args.width, height=args.height,
                             frames=args.frames, force=args.force)
    except (DatasetError, lib.ActionError) as e:
        return _error(str(e))
    kept = data["dataset"]["clips"]
    print("dataset: %d clips normalized to %dx%d x %d @ %dfps in %s"
          % (kept, args.width, args.height, args.frames, args.fps,
             os.path.join(lib.action_dir(args.name), "dataset")))
    print("identity_agnostic: %s (%d performers asserted)" % (data["identity_agnostic"], args.performers))
    print("contact sheet: %s" % data["dataset"]["contact_sheet"])
    if kept < lib.MIN_CLIPS:
        print("Error: only %d clip(s); training needs >= %d. The dataset is kept; add more --clip "
              "and run bin/action create %s --regenerate." % (kept, lib.MIN_CLIPS, args.name),
              file=sys.stderr)
        return 3
    print("next: review the contact sheet, then run bin/action train %s" % args.name)
    return 0


def _error(message):
    print("Error: %s" % message, file=sys.stderr)
    return 2


def build_parser():
    p = argparse.ArgumentParser(prog="action-dataset", description="Build an action LoRA clip dataset.")
    sub = p.add_subparsers(dest="command", required=True)
    c = sub.add_parser("create", help="normalize reference clips into a training dataset")
    c.add_argument("name")
    c.add_argument("--trigger", required=True, help='Motion: phrase, e.g. "performs a roundhouse kick"')
    c.add_argument("--descriptor", required=True)
    c.add_argument("--clip", dest="clips", action="append", default=[], metavar="PATH")
    c.add_argument("--performers", type=int, default=0, help="distinct performers across the clips")
    c.add_argument("--width", type=int, default=DEFAULT_WIDTH)
    c.add_argument("--height", type=int, default=DEFAULT_HEIGHT)
    c.add_argument("--frames", type=int, default=DEFAULT_FRAMES)
    c.add_argument("--fps", type=int, default=DEFAULT_FPS)
    c.add_argument("--force", action="store_true", help="proceed with < 3 performers (not identity-agnostic)")
    c.add_argument("--regenerate", action="store_true", help="rebuild an existing action's dataset")
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    args.fps = getattr(args, "fps", DEFAULT_FPS)
    if args.command == "create":
        return create(args)
    return 2


if __name__ == "__main__":
    sys.exit(main())
