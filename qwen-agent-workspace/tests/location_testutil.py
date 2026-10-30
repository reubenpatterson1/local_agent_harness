"""Shared helpers for the location library tests (docs/superpowers/specs/
2026-10-29-location-lora-design.md, Section 6.2).

Not a test module (pytest does not collect it). Every helper writes under a directory the caller
passes in; nothing here reads or writes the real HOME, renders, trains or contacts a server.
"""

import hashlib
import json
import os

VIDEO_BYTES = b"fake-place-lora!"
STILLS_BYTES = b"fake-place-still"
VIDEO_BASE_MODEL = "dgrauet/ltx-2.3-mlx-q8"
STILLS_BASE_MODEL = "Tongyi-MAI/Z-Image-Turbo"
# 24, 30 and 20 words; none contains a period, an exclamation or question mark, or a double quote.
HARBOUR_DESC = ("a narrow cobbled harbour street lined with weathered stone warehouses, green wooden "
                "shutters, rusted mooring rings and faded red fishmonger signs above granite quays")
TEMPLE_DESC = ("an old hillside temple gate of red lacquered timber with a curved tiled roof, stone "
               "lanterns, worn granite steps, paper prayer charms and tall cedar trees behind a "
               "mossy wall")
MILL_DESC = ("an old timber water mill beside a shallow weir with a mossy wheel, a slate roof and a "
             "cobbled yard")


def make_location(lib, name, trigger, description, status="trained", source="text", stills=False,
                  strength=None):
    """Write a valid location.json (location library spec 3.6, 3.7) under lib/name and return
    the dict. untrained and trained records get a 21-of-24 dataset; a trained one also gets a
    16-byte lora/video.safetensors (base dgrauet/ltx-2.3-mlx-q8), plus a 16-byte
    lora/stills.safetensors when stills, each entry with its real sha256. A photos record lists
    one photo."""
    ldir = os.path.join(lib, name)
    os.makedirs(os.path.join(ldir, "lora"), exist_ok=True)
    dataset = None
    if status in ("untrained", "trained"):
        dataset = {"kept": 21, "total": 24, "min_score": 7,
                   "contact_sheet": os.path.join(ldir, "contact_sheet.jpg")}
    video = stills_entry = trained_at = None
    if status == "trained":
        video_path = os.path.join(ldir, "lora", "video.safetensors")
        with open(video_path, "wb") as f:
            f.write(VIDEO_BYTES)
        video = {"path": video_path, "sha256": hashlib.sha256(VIDEO_BYTES).hexdigest(),
                 "base_model": VIDEO_BASE_MODEL, "rank": 32, "alpha": 32, "steps": 1000}
        trained_at = "2026-10-29T12:00:00Z"
        if stills:
            stills_path = os.path.join(ldir, "lora", "stills.safetensors")
            with open(stills_path, "wb") as f:
                f.write(STILLS_BYTES)
            stills_entry = {"path": stills_path,
                            "sha256": hashlib.sha256(STILLS_BYTES).hexdigest(),
                            "base_model": STILLS_BASE_MODEL, "rank": 16, "alpha": 16,
                            "steps": 672}
    photos = []
    if source == "photos":
        photos = [{"path": "/fixtures/photos/%s_01.jpg" % name,
                   "sha256": hashlib.sha256(name.encode("utf-8")).hexdigest()}]
    data = {"schema_version": 1, "name": name, "trigger": trigger, "description": description,
            "source": source, "photos": photos, "seed": 0, "status": status,
            "created_at": "2026-10-29T10:00:00Z", "trained_at": trained_at, "dataset": dataset,
            "loras": {"video": video, "stills": stills_entry}, "stills_skip_reason": None,
            "strength": strength}
    with open(os.path.join(ldir, "location.json"), "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    return data


def harbour(lib, **kw):
    return make_location(lib, "harbour-street", "harboplc", HARBOUR_DESC, **kw)


def temple(lib, **kw):
    return make_location(lib, "temple-gate", "templplc", TEMPLE_DESC, **kw)


def mill(lib, **kw):
    return make_location(lib, "old-mill", "oldmiplc", MILL_DESC, **kw)


def write_plan(story_dir, beat_locations, pinned=(("l1", "harbour-street"),), extra=()):
    """A minimal usable plan.json in story_dir: locations l1.. (location_name from pinned, else
    null; plus extra ids), one beat per entry of beat_locations, each at that location id.
    Returns the plan dict."""
    os.makedirs(story_dir, exist_ok=True)
    names = dict(pinned)
    ids = sorted(set(list(names) + list(extra) + list(beat_locations)))
    plan = {"schema": "ltx-movie.plan.v1", "mode": "chained", "panels": len(beat_locations),
            "cast": [], "props": [],
            "locations": [{"id": i, "setting": "The setting is a place %s." % i,
                           "location_name": names.get(i)} for i in ids],
            "beats": [{"index": k, "location": loc, "cast": []}
                      for k, loc in enumerate(beat_locations, start=1)],
            "loras": {"global": [], "per_beat": {}, "stills": [], "pinned": []}}
    with open(os.path.join(story_dir, "plan.json"), "w", encoding="utf-8") as f:
        json.dump(plan, f, indent=2)
    return plan
