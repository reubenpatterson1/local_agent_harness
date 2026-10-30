#!/usr/bin/env python3
"""location_dataset -- the dataset builder and trainer behind bin/location
(docs/superpowers/specs/2026-10-29-location-lora-design.md, Sections 2 and 3).

A location's dataset is 24 people-free 1024x640 stills: 24 Z-Image text2img stills of the
description (text mode), or the user's photos plus Qwen-Image-Edit-2511 edits of them that change
only the time of day, the weather or the season (photo mode). The vision model checks every
still; the kept ones get a trigger-led caption and a 1-frame mp4. Training reuses
character_dataset.train_video_lora and train_stills_lora.

Top-level imports are stdlib, PIL, psutil, character_dataset and location_lib. All
image work runs in character_dataset's own child processes (run_zimage_child, run_edit_child),
so character_dataset.busy_process's markers cover location work. Every gate, VLM call and child
is called through the character_dataset module, so a test fake there applies here too.
"""

import contextlib
import hashlib
import json
import os
import shutil
import sys

import psutil
from PIL import Image, ImageDraw, ImageOps

WS = os.path.dirname(os.path.realpath(__file__))
sys.path.insert(0, WS)

import character_dataset  # noqa: E402
import location_lib  # noqa: E402

DatasetError = character_dataset.DatasetError
STYLE = character_dataset.STYLE        # "photorealistic live-action film still, natural light"
WIDTH, HEIGHT = 1024, 640
SEED_MAX = 2147483647
MIN_CROP_W, MIN_CROP_H = 768, 480
DESCRIBE_PHOTOS = 5

# Spec 2.5: the 24 text-mode stills.
TIMES = ("dawn", "midday", "golden hour", "dusk", "night")
WEATHERS = ("clear", "overcast", "rain", "fog", "snow")        # "snow" only from the check
TIME_PHRASES = {"dawn": "at dawn", "midday": "at midday", "golden hour": "at golden hour",
                "dusk": "at dusk", "night": "at night"}
WEATHER_PHRASES = {"clear": "under a clear sky", "overcast": "under an overcast sky",
                   "rain": "in the rain", "fog": "in fog"}
VARIANTS = [
    # (view, time, weather), still n = position
    ("Extreme wide establishing shot", "dawn", "clear"),
    ("Extreme wide establishing shot", "midday", "overcast"),
    ("Extreme wide establishing shot", "golden hour", "fog"),
    ("Extreme wide establishing shot", "night", "fog"),
    ("Wide shot from a high vantage point", "midday", "clear"),
    ("Wide shot from a high vantage point", "dusk", "overcast"),
    ("Wide shot from a high vantage point", "dawn", "fog"),
    ("Wide shot from a high vantage point", "night", "rain"),
    ("Ground-level view looking along the length", "golden hour", "clear"),
    ("Ground-level view looking along the length", "midday", "rain"),
    ("Ground-level view looking along the length", "dusk", "fog"),
    ("Ground-level view looking along the length", "night", "clear"),
    ("Low-angle upward view", "midday", "overcast"),
    ("Low-angle upward view", "dawn", "overcast"),
    ("Low-angle upward view", "dusk", "rain"),
    ("Low-angle upward view", "golden hour", "fog"),
    ("Medium shot of a single detail", "midday", "overcast"),
    ("Medium shot of a single detail", "golden hour", "rain"),
    ("Medium shot of a single detail", "night", "clear"),
    ("Medium shot of a single detail", "dawn", "rain"),
    ("Close-up of a surface texture or sign", "dawn", "clear"),
    ("Close-up of a surface texture or sign", "dusk", "fog"),
    ("Close-up of a surface texture or sign", "golden hour", "overcast"),
    ("Close-up of a surface texture or sign", "night", "rain"),
]


def gen_prompt(view, time, weather, description):
    return "%s of %s, %s, %s, empty of people. %s." % (
        view, description, TIME_PHRASES[time], WEATHER_PHRASES[weather], STYLE)


# Spec 2.6: the photo-mode top-up edits; edit j (1-based) uses EDIT_CONDITIONS[j - 1].
EDIT_PROMPT = ("Keep this exact place and viewpoint: the same buildings, structures, ground, "
               "signs, materials and colours, seen from the same camera position with the same "
               "framing. Change only the time of day and the conditions: show it %s, %s. No "
               "people anywhere in the image. Photorealistic live-action film still, natural "
               "light.")
EDIT_CONDITIONS = [
    ("at dusk", "under a clear sky"), ("at night", "in light rain"), ("at dawn", "in thick fog"),
    ("at midday", "under an overcast sky"), ("at golden hour", "under a clear sky"),
    ("at night", "under a clear sky"), ("at midday", "in winter with fresh snow on the ground"),
    ("at dusk", "in heavy rain"), ("at dawn", "under an overcast sky"),
    ("at golden hour", "in autumn with fallen leaves on the ground"), ("at midday", "in light fog"),
    ("at night", "in fog"), ("at dawn", "under a clear sky"), ("at dusk", "under an overcast sky"),
    ("at midday", "in the rain"), ("at golden hour", "in light haze"),
    ("at night", "in winter with snow falling"), ("at dawn", "in light rain"),
    ("at midday", "in summer under a clear sky"), ("at dusk", "in fog"),
    ("at golden hour", "under an overcast sky"), ("at night", "in heavy rain"),
    ("at midday", "in spring under a clear sky"),
]                                                    # 23 entries: P = 1 needs 23 edits

# Spec 2.7: the vision model drafts a photo location's description.
DESCRIBE_ATTEMPTS = 3
DESCRIBE_PROMPT = (
    'These photos show one place. Describe it for an image generator that must redraw the same '
    'place recognisably from many viewpoints, at any time of day and in any weather. Reply with '
    'only a JSON object with one key. "description": one noun phrase of 15 to 40 words that '
    'starts with "a", "an" or "the" and captures only the place\'s persistent features: its '
    'architecture and structures, materials and surfaces, signage, colour palette, era and the '
    'ground. Leave out people, vehicles, animals, the time of day, the weather, the lighting, the '
    'season, the camera and the image style. Use commas, not full stops.')
DESCRIBE_SHORTEN = (
    'Shorten this place description to one noun phrase of 20 to 35 words that starts with "a", '
    '"an" or "the". Keep the architecture, materials, signage, palette, era and ground; drop '
    'repetition and the least distinctive details; use commas and no full stops. Reply with only '
    'a JSON object with one key, "description": the shortened phrase.\n\nDescription: %s')
DESCRIBE_RETRY = (
    'Your previous reply was rejected: %s. Previous reply: %s\n'
    'Reply again with only the JSON object. Keep "description" one noun phrase of 15 to 40 words '
    'starting with "a", "an" or "the", with commas and no full stops.')

# Spec 2.9: the three check prompts.
_KEYS = ('"people_visible": true when any person or part of a person is visible anywhere in '
         'the image, else false. "shot": exactly one of extreme wide shot, wide shot, medium '
         'shot, medium close-up, close-up, extreme close-up. "time_of_day": exactly one of dawn, '
         'midday, golden hour, dusk, night. "weather": exactly one of clear, overcast, rain, fog, '
         'snow.')
CHECK_TEXT_PROMPT = (
    'The image is a candidate picture of this place: @@DESCRIPTION@@. Reply with only a JSON '
    'object with five keys. "match_score": an integer from 1 to 10 for how clearly the image '
    'shows this place, with its architecture, materials, signage, palette, era and ground, where '
    '10 is unmistakably this place and 1 is a different place. ' + _KEYS)
CHECK_PHOTO_PROMPT = (
    'The first image shows the reference place. The second image is a candidate picture, which '
    'may show the same place from another viewpoint, at another time of day, in other weather or '
    'in another season. Reply with only a JSON object with five keys. "match_score": an integer '
    'from 1 to 10 for how clearly the candidate shows the same place as the reference, comparing '
    'its architecture, materials, signage, palette and ground and ignoring the time of day, '
    'weather and season, where 10 is unmistakably the same place and 1 is a different place. '
    + _KEYS)
TAG_PROMPT = 'Reply with only a JSON object with four keys describing this image. ' + _KEYS
CHECK_RETRY = ('Your previous reply was rejected: %s. Previous reply: %s\n'
               'Reply again with only the JSON object, using exactly the listed values for '
               '"shot", "time_of_day" and "weather" and true or false for "people_visible"%s.')
SCORE_RETRY_EXTRA = ', and an integer from 1 to 10 for "match_score"'
TIME_ALIASES = {"noon": "midday", "day": "midday", "daytime": "midday", "sunrise": "dawn",
                "sunset": "golden hour", "evening": "dusk", "twilight": "dusk"}
WEATHER_ALIASES = {"sunny": "clear", "cloudy": "overcast", "rainy": "rain", "foggy": "fog",
                   "mist": "fog", "misty": "fog", "haze": "fog", "hazy": "fog", "snowy": "snow"}

# Spec 2.12, 6.1: the reason groups of the too-few message, in this order.
REASON_GROUPS = (("people visible", "people visible"), ("score ", "score below 7"),
                 ("blocked by the content screen", "blocked by the content screen"),
                 ("unparseable", "unparseable"))
BLOCKED = "blocked by the content screen"
FORCE_HINT = " (pass --force to keep it)"
# Spec 3.3, 3.4: the trigger-only test prompt of both LoRAs.
TEST_PROMPT = "%s, wide establishing shot at dusk, empty of people."
SKIP_INSTALL_HINT = ("install mflux as described in "
                     "docs/superpowers/specs/2026-10-05-character-library-design.md section 4.10")


def _error(message):
    print("Error: %s" % message, file=sys.stderr)
    return 2


def _sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def still_path(loc_dir, n):
    return os.path.join(loc_dir, "stills", "loc_%02d.png" % n)


def photo_copy_path(loc_dir, k):
    return os.path.join(loc_dir, "photos", "photo_%02d.png" % k)


# ---------------------------------------------------------------------------
# VLM helpers (spec 2.7, 2.9)
# ---------------------------------------------------------------------------

def _image_parts(paths):
    return [{"type": "image_url", "image_url": {"url": character_dataset.image_data_url(p)}}
            for p in paths]


def describe(paths):
    """The vision model's description of the place in the photos at paths (spec 2.7): a
    normalised, valid description. Raises DatasetError after DESCRIBE_ATTEMPTS failures."""
    content = [{"type": "text", "text": DESCRIBE_PROMPT}] + _image_parts(paths)
    reply, error, too_long = None, None, None
    for _attempt in range(DESCRIBE_ATTEMPTS):
        # The call is at temperature 0, so a bare retry repeats the same reply: a too-long
        # description is sent back alone to be shortened, any other rejection is quoted.
        if too_long is not None:
            parts = [{"type": "text", "text": DESCRIBE_SHORTEN % too_long}]
        elif error is not None:
            parts = content + [{"type": "text", "text": DESCRIBE_RETRY % (error, reply)}]
        else:
            parts = content
        reply = character_dataset.vlm_call(parts)
        too_long = None
        try:
            d = character_dataset.extract_json(reply)
            text = d.get("description")
            if not isinstance(text, str):
                raise ValueError('"description" must be a string')
            text = location_lib.normalize_description(text)
            if len(text.split()) > location_lib.DESCRIPTION_MAX_WORDS:
                too_long = text
            location_lib.validate_description(text)
            return text
        except (ValueError, location_lib.LocationError) as e:
            error = e
    raise DatasetError("describe failed: %s; last reply: %r" % (error, reply))


def validate_location_check(d, scored):
    """The normalised check of spec 2.9: {"match_score": int or None, "people_visible": bool,
    "shot", "time_of_day", "weather"}. Raises ValueError on any malformed reply."""
    score = None
    if scored:
        if "match_score" not in d:
            raise ValueError("missing key: match_score")
        score = d["match_score"]
        if isinstance(score, bool) or not isinstance(score, int):
            raise ValueError("match_score must be an integer, got %r" % (score,))
        if not 1 <= score <= 10:
            raise ValueError("match_score must be 1-10, got %d" % score)
    if not isinstance(d.get("people_visible"), bool):
        raise ValueError("people_visible must be true or false, got %r" % (d.get("people_visible"),))
    out = {"match_score": score, "people_visible": d["people_visible"]}
    for key, aliases, allowed in (("shot", character_dataset.SHOT_ALIASES, character_dataset.SHOTS),
                                  ("time_of_day", TIME_ALIASES, TIMES),
                                  ("weather", WEATHER_ALIASES, WEATHERS)):
        value = d.get(key)
        if not isinstance(value, str):
            raise ValueError("%s must be a string, got %r" % (key, value))
        value = value.lower().strip()
        value = aliases.get(value, value)
        if value not in allowed:
            raise ValueError("%s %r is not one of %s" % (key, value, ", ".join(allowed)))
        out[key] = value
    return out


def check_still(prompt, paths, scored):
    """(check, None), or (None, "unparseable: <error>") after CHECK_ATTEMPTS unparseable replies
    (spec 2.9). A RuntimeError from the VLM call propagates."""
    content = [{"type": "text", "text": prompt}] + _image_parts(paths)
    extra = SCORE_RETRY_EXTRA if scored else ""
    reply, error = None, None
    for _attempt in range(character_dataset.CHECK_ATTEMPTS):
        parts = content if error is None else content + [
            {"type": "text", "text": CHECK_RETRY % (error, reply, extra)}]
        reply = character_dataset.vlm_call(parts)
        try:
            return validate_location_check(character_dataset.extract_json(reply), scored), None
        except ValueError as e:
            error = e
    return None, "unparseable: %s" % error


def caption(trigger, check):
    """The training caption of a kept still (spec 2.9); check None is a forced unparseable
    photo."""
    if check is None:
        return "%s, %s." % (trigger, STYLE)
    parts = [trigger] + [v for v in (check["shot"], check["time_of_day"], check["weather"]) if v]
    if check["people_visible"] is False:
        parts.append("empty of people")
    return ", ".join(parts) + ", " + STYLE + "."


# ---------------------------------------------------------------------------
# The contact sheet (spec 2.11)
# ---------------------------------------------------------------------------

def write_contact_sheet(items, stills_dir, out_path):
    """5 columns of 256x160 thumbnails, each with a 20-px label row, under a 24-px banner; a
    dropped cell is outlined in red, a missing still is a black cell."""
    cols, tw, th, lh, banner = 5, 256, 160, 20, 24
    rows = (len(items) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * tw, banner + rows * (th + lh)), (0, 0, 0))
    draw = ImageDraw.Draw(sheet)
    kept = sum(1 for item in items if item["kept"])
    draw.text((4, 6), "kept %d of %d (need %d)" % (kept, len(items), location_lib.MIN_KEEP),
              fill=(255, 255, 255))
    for k, item in enumerate(items):
        x, y = (k % cols) * tw, banner + (k // cols) * (th + lh)
        path = os.path.join(stills_dir, "loc_%02d.png" % item["n"])
        if os.path.isfile(path):
            with Image.open(path) as img:
                sheet.paste(img.convert("RGB").resize((tw, th), Image.LANCZOS), (x, y))
        if not item["kept"]:
            draw.rectangle([x, y, x + tw - 1, y + th - 1], outline=(255, 0, 0), width=4)
        draw.text((x + 4, y + th + 3), cell_label(item), fill=(255, 255, 255))
    sheet.save(out_path, format="JPEG", quality=90)


def cell_label(item):
    score = "s%d" % item["match_score"] if item["match_score"] is not None else "s-"
    verdict = "kept" if item["kept"] else (item["reason"] or "")[:28]
    return "%02d %s %s %s" % (item["n"], item["source"][0].upper(), score, verdict)


# ---------------------------------------------------------------------------
# Building the dataset (spec 2.5, 2.6, 2.8-2.12)
# ---------------------------------------------------------------------------

def _with_story_server_stopped(min_gib, work):
    """Stop the story server, wait for min_gib available, run work(), and restore the server in
    a finally: detached after an interrupt, else with --wait and a wait for the VLM (spec 2.6
    step 6; character_dataset.py:980-1008)."""
    interrupted = False
    rc = character_dataset.story_server("stop")
    if rc != 0:
        print("warning: story-server stop returned %d" % rc, file=sys.stderr)
    try:
        if not character_dataset.wait_for_avail(min_gib, character_dataset.AVAIL_WAIT_S):
            raise DatasetError("timed out waiting for %d GiB available memory after stopping the "
                               "story server" % min_gib)
        work()
    except (KeyboardInterrupt, EOFError):
        interrupted = True
        raise
    finally:
        if interrupted:
            character_dataset.restore_story_server()
        else:
            rc = character_dataset.restore_story_server(wait=True)
            if rc != 0:
                print("warning: story-server-restore %s --wait returned %d"
                      % (character_dataset.VLM_SERVE_MODE, rc), file=sys.stderr)
            if not character_dataset.wait_for_vlm(character_dataset.VLM_WAIT_S):
                raise DatasetError("timed out waiting for the vision server to come back")


def _plan(data, loc_dir):
    """[{"n", "source", "photo", "prompt"}] for the 24 stills, and the image child to run:
    ("generate", spec), ("edit", spec) or (None, None)."""
    if data["source"] == "text":
        plan = [{"n": n, "source": "generated", "photo": None,
                 "prompt": gen_prompt(view, time, weather, data["description"])}
                for n, (view, time, weather) in enumerate(VARIANTS, start=1)]
        jobs = [{"prompt": e["prompt"], "output_path": still_path(loc_dir, e["n"]),
                 "seed": data["seed"], "width": WIDTH, "height": HEIGHT} for e in plan]
        return plan, ("generate", {"jobs": jobs, "loras": None})
    p = len(data["photos"])
    plan = [{"n": k, "source": "photo", "photo": k, "prompt": None} for k in range(1, p + 1)]
    for j in range(1, location_lib.TOTAL_STILLS - p + 1):
        plan.append({"n": p + j, "source": "edit", "photo": ((j - 1) % p) + 1,
                     "prompt": EDIT_PROMPT % EDIT_CONDITIONS[j - 1]})
    edits = [e for e in plan if e["source"] == "edit"]
    if not edits:
        return plan, (None, None)
    jobs = [{"image": still_path(loc_dir, e["photo"]), "prompt": e["prompt"],
             "output_path": still_path(loc_dir, e["n"]), "seed": data["seed"], "width": WIDTH,
             "height": HEIGHT} for e in edits]
    spec = {"image": jobs[0]["image"], "skill": "location_edit",
            "model": character_dataset.EDIT_MODEL, "lora_repo": character_dataset.EDIT_LORA_REPO,
            "lora_file": character_dataset.EDIT_LORA_FILE, "steps": character_dataset.EDIT_STEPS,
            "true_cfg": character_dataset.EDIT_TRUE_CFG, "jobs": jobs}
    return plan, ("edit", spec)


def _check_entry(data, loc_dir, entry, force):
    """The manifest item of one still (spec 2.9, 2.10)."""
    item = {"n": entry["n"], "source": entry["source"], "photo": entry["photo"],
            "prompt": entry["prompt"], "match_score": None, "people_visible": None, "shot": "",
            "time_of_day": "", "weather": "", "kept": False, "reason": None, "caption": None}
    png = still_path(loc_dir, entry["n"])
    if not os.path.isfile(png):
        item["reason"] = BLOCKED
        return item
    if entry["source"] == "generated":
        check, unparseable = check_still(
            CHECK_TEXT_PROMPT.replace("@@DESCRIPTION@@", data["description"]), [png], True)
    elif entry["source"] == "edit":
        check, unparseable = check_still(CHECK_PHOTO_PROMPT, [still_path(loc_dir, 1), png], True)
    else:
        check, unparseable = check_still(TAG_PROMPT, [png], False)
    if check is not None:
        for key in ("match_score", "people_visible", "shot", "time_of_day", "weather"):
            item[key] = check[key]
    if entry["source"] == "photo":
        problem = unparseable if check is None else (
            "people visible" if check["people_visible"] else None)
        if problem is None:
            item["kept"] = True
        elif force:
            item["kept"], item["reason"] = True, "kept by --force: " + problem
        else:
            item["reason"] = problem + FORCE_HINT
    elif check is None:
        item["reason"] = unparseable
    elif check["match_score"] < location_lib.MIN_SCORE:
        item["reason"] = "score %d" % check["match_score"]
    elif check["people_visible"]:
        item["reason"] = "people visible"
    else:
        item["kept"] = True
    if item["kept"]:
        item["caption"] = caption(data["trigger"], check)
        with open(os.path.join(loc_dir, "captions", "loc_%02d.txt" % entry["n"]), "w",
                  encoding="utf-8") as f:
            f.write(item["caption"])
        mp4 = os.path.join(loc_dir, "videos", "loc_%02d.mp4" % entry["n"])
        character_dataset.wrap_still(png, mp4)
        character_dataset.verify_ffprobe(mp4)
    return item


def reason_counts(items):
    """The too-few message's counts by reason, e.g. "5 people visible, 4 score below 7"."""
    counts = []
    for prefix, label in REASON_GROUPS:
        n = sum(1 for item in items if not item["kept"] and (item["reason"] or "").startswith(prefix))
        if n:
            counts.append("%d %s" % (n, label))
    return ", ".join(counts)


def build_dataset(data, force=False):
    """Make, check, caption and wrap the 24 stills of location.json data; write manifest.json,
    contact_sheet.jpg and the updated location.json. Returns 0, 1 (a DatasetError or
    RuntimeError, printed, or an abort; status stays "dataset") or 3 (fewer than MIN_KEEP kept)."""
    try:
        return _build_dataset(data, force)
    except (DatasetError, RuntimeError) as e:
        print("Error: %s" % e, file=sys.stderr)
        return 1
    except (KeyboardInterrupt, EOFError):
        print("\nError: aborted; the stills made so far are kept in %s; run bin/location create "
              "%s --regenerate to start again"
              % (location_lib.location_dir(data["name"]), data["name"]), file=sys.stderr)
        return 1


def _build_dataset(data, force):
    name = data["name"]
    loc_dir = location_lib.location_dir(name)
    plan, (child, spec) = _plan(data, loc_dir)
    for k in range(1, len(data["photos"]) + 1):
        with Image.open(photo_copy_path(loc_dir, k)) as img:
            ImageOps.fit(img.convert("RGB"), (WIDTH, HEIGHT), Image.LANCZOS,
                         centering=(0.5, 0.5)).save(still_path(loc_dir, k))
    if child == "generate":
        print("=== generate: %d stills ===" % len(spec["jobs"]), flush=True)
        _with_story_server_stopped(character_dataset.GENERATE_MIN_AVAIL_GIB, lambda: (
            character_dataset.run_zimage_child(spec, loc_dir, "generate")))
    elif child == "edit":
        print("=== edit: %d stills ===" % len(spec["jobs"]), flush=True)
        _with_story_server_stopped(character_dataset.EDIT_MIN_AVAIL_GIB, lambda: (
            character_dataset.run_edit_child(spec, loc_dir, "edit")))

    print("=== check ===", flush=True)
    items = [_check_entry(data, loc_dir, entry, force) for entry in plan]
    photo_mode = data["source"] == "photos"
    manifest = {"source": data["source"], "trigger": data["trigger"],
                "description": data["description"], "seed": data["seed"],
                "min_score": location_lib.MIN_SCORE, "reference": "loc_01" if photo_mode else None,
                "generator": ("Z-Image" if not photo_mode
                              else "%s + %s, %d steps" % (character_dataset.EDIT_MODEL,
                                                          character_dataset.EDIT_LORA_FILE,
                                                          character_dataset.EDIT_STEPS)
                              if child == "edit" else "photos only"),
                "items": items}
    with open(os.path.join(loc_dir, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)
    sheet = os.path.join(loc_dir, "contact_sheet.jpg")
    write_contact_sheet(items, os.path.join(loc_dir, "stills"), sheet)

    kept = sum(1 for item in items if item["kept"])
    data["dataset"] = {"kept": kept, "total": location_lib.TOTAL_STILLS,
                       "min_score": location_lib.MIN_SCORE, "contact_sheet": sheet}
    data["status"] = "untrained" if kept >= location_lib.MIN_KEEP else "dataset"
    location_lib.write_location(data)

    print("%-4s %-6s %-5s %s" % ("n", "score", "kept", "caption"))
    for item in items:
        print("%-4d %-6s %-5s %s" % (item["n"], "-" if item["match_score"] is None
                                     else item["match_score"], str(item["kept"]),
                                     item["caption"] or "(dropped: %s)" % item["reason"]))
    print("dataset: %d/%d stills kept (minimum %d) in %s"
          % (kept, location_lib.TOTAL_STILLS, location_lib.MIN_KEEP, loc_dir))
    print("contact sheet: %s" % sheet)
    if kept < location_lib.MIN_KEEP:
        if photo_mode:
            fix = ("create a new location with more photos that show no people, or run "
                   "bin/location create %s --regenerate --new-seed (--force keeps photos that "
                   "show people)" % name)
        else:
            fix = ("run bin/location create %s --regenerate --new-seed, or --regenerate "
                   "--description TEXT with a clearer description" % name)
        print("Error: only %d/%d stills kept (need %d): %s; the dataset is kept in %s; %s"
              % (kept, location_lib.TOTAL_STILLS, location_lib.MIN_KEEP, reason_counts(items),
                 loc_dir, fix), file=sys.stderr)
        return 3
    print("next: review the contact sheet, then run bin/location train %s" % name)
    return 0


# ---------------------------------------------------------------------------
# create, regenerate, edit (spec 2.12)
# ---------------------------------------------------------------------------

def _load_photos(paths):
    """([(absolute path, oriented RGB image, sha256)], None) or (None, error message) for the
    --photo paths (spec 2.6 step 1)."""
    import ltx_image_fit
    if len(paths) > location_lib.MAX_PHOTOS:
        return None, "at most 24 --photo, got %d" % len(paths)
    loaded, seen = [], {}
    for k, given in enumerate(paths, start=1):
        path = os.path.abspath(given)
        if not os.path.isfile(path):
            return None, "--photo not found: %s" % path
        try:
            img = ltx_image_fit.load_oriented_rgb(path)
        except Exception as e:
            return None, "--photo is not a readable image: %s: %s" % (path, e)
        w, h = img.size
        crop_w, crop_h = min(w, h * 16 // 10), min(h, w * 10 // 16)
        if crop_w < MIN_CROP_W or crop_h < MIN_CROP_H:
            return None, ("--photo %s is %dx%d; its centred 16:10 crop is %dx%d, smaller than the "
                          "768x480 minimum" % (path, w, h, crop_w, crop_h))
        sha = _sha256(path)
        if sha in seen:
            return None, "--photo %s is the same file as photo %d" % (path, seen[sha])
        seen[sha] = k
        loaded.append((path, img, sha))
    return loaded, None


def _edit_models_problem():
    missing = character_dataset.edit_models_missing()
    if not missing:
        return None
    return ("the photo editor is not downloaded: %s; download it with: %s"
            % (", ".join(missing), "; ".join("hf download %s" % m for m in missing)))


def _gates(stack):
    """The lock, busy, disk and VLM preflights of spec 2.12 create step 5, holding the lock on
    stack; the error message, or None when every one passes."""
    try:
        stack.enter_context(character_dataset.library_lock())
    except DatasetError as e:
        return str(e)
    busy = character_dataset.busy_process()
    if busy is not None:
        return ("a render or training process is running (pid %d: %s); bin/location never trains "
                "or generates concurrently with a render" % busy)
    lib = location_lib.library_dir()
    free = character_dataset.free_gib(lib)
    if free < character_dataset.CREATE_MIN_FREE_GIB:
        return "only %.1f GiB free at %s; create needs 2 GiB" % (free, lib)
    if not character_dataset.vlm_ready():
        return ("the vision model %s is not being served at %s; start it with: bin/story-server %s"
                % (character_dataset.VLM_MODEL, character_dataset.MODELS_URL,
                   character_dataset.VLM_SERVE_MODE))
    return None


def _description_arg(text, trigger=None):
    """(normalised description, None) or (None, error message) for --description TEXT."""
    description = location_lib.normalize_description(text)
    try:
        location_lib.validate_description(description)
        if trigger is not None:
            location_lib.validate_trigger(trigger, description)
    except location_lib.LocationError as e:
        return None, "--description: %s" % e
    return description, None


def create(args):
    """bin/location create NAME (spec 2.12). Returns 0, 1, 2 or 3."""
    name = args.name
    try:
        location_lib.validate_name(name)
    except location_lib.LocationError as e:
        return _error(e)
    if args.regenerate:
        return _regenerate(args)
    if args.new_seed:
        return _error("--new-seed needs --regenerate")
    loc_dir = location_lib.location_dir(name)
    if os.path.exists(loc_dir):
        return _error("location %s already exists (%s); use --regenerate to rebuild its dataset"
                      % (name, loc_dir))
    photos, problem = _load_photos(args.photos or [])
    if problem:
        return _error(problem)
    description = None
    if args.description is not None:
        description, problem = _description_arg(args.description)
        if problem:
            return _error(problem)
    if not photos and description is None:
        return _error("create needs --description or at least one --photo")
    seed = args.seed if args.seed is not None else 0
    if not 0 <= seed <= SEED_MAX:
        return _error("--seed must be between 0 and 2147483647")
    if args.trigger is not None:
        try:
            location_lib.validate_trigger(args.trigger, description)
        except location_lib.LocationError as e:
            return _error(e)
        owner = location_lib.all_triggers().get(args.trigger)
        if owner is not None:
            return _error("trigger %s is already used by %s; triggers are never reused"
                          % (args.trigger, owner))
    if photos and len(photos) < location_lib.TOTAL_STILLS:
        problem = _edit_models_problem()
        if problem:
            return _error(problem)

    with contextlib.ExitStack() as stack:
        problem = _gates(stack)
        if problem:
            return _error(problem)
        if description is None:
            try:
                description = describe([p for p, _img, _sha in photos[:DESCRIBE_PHOTOS]])
            except (DatasetError, RuntimeError) as e:
                print("Error: %s" % e, file=sys.stderr)
                return 1
            print("description (drafted by the vision model; change it with bin/location edit %s "
                  "--description TEXT): %s" % (name, description))
        if args.trigger is not None:
            try:
                location_lib.validate_trigger(args.trigger, description)
            except location_lib.LocationError as e:
                return _error(e)
            trigger = args.trigger
        else:
            trigger = location_lib.auto_trigger(name, description,
                                                set(location_lib.all_triggers()))
        subs = ["stills", "captions", "videos", "logs"] + (["photos"] if photos else [])
        for sub in subs:
            os.makedirs(os.path.join(loc_dir, sub), exist_ok=True)
        for k, (_path, img, _sha) in enumerate(photos, start=1):
            img.save(photo_copy_path(loc_dir, k), format="PNG")
        location_lib.register_trigger(trigger, name)
        data = {"schema_version": location_lib.SCHEMA_VERSION, "name": name, "trigger": trigger,
                "description": description, "source": "photos" if photos else "text",
                "photos": [{"path": path, "sha256": sha} for path, _img, sha in photos],
                "seed": seed, "status": "dataset", "created_at": location_lib.utc_now(),
                "trained_at": None, "dataset": None, "loras": {"video": None, "stills": None},
                "stills_skip_reason": None, "strength": None}
        location_lib.write_location(data)
        return build_dataset(data, args.force)


def _regenerate(args):
    """create NAME --regenerate (spec 2.12): every refusal before the lock leaves location.json
    untouched; the new seed and description are persisted only under the lock."""
    name = args.name
    try:
        data = location_lib.load_location(name)
    except location_lib.LocationError as e:
        return _error(e)
    if args.photos or args.trigger is not None:
        return _error("--regenerate takes no --photo or --trigger: a location keeps the photos and "
                      "the trigger it was created with")
    if args.seed is not None and args.new_seed:
        return _error("give --seed or --new-seed, not both")
    if args.seed is not None and not 0 <= args.seed <= SEED_MAX:
        return _error("--seed must be between 0 and 2147483647")
    description = data["description"]
    if args.description is not None:
        if data["source"] == "photos":
            return _error("a photo location's stills come from its photos; change its description "
                          "with bin/location edit %s --description TEXT" % name)
        description, problem = _description_arg(args.description, data["trigger"])
        if problem:
            return _error(problem)
    if data["status"] == "trained" and not args.force:
        return _error("location %s is trained; regenerating its dataset deletes its LoRAs. Pass "
                      "--force to regenerate it anyway" % name)
    if data["source"] == "photos" and len(data["photos"]) < location_lib.TOTAL_STILLS:
        problem = _edit_models_problem()
        if problem:
            return _error(problem)
    old_seed = data["seed"]
    if args.new_seed:
        new_seed = 0 if old_seed >= SEED_MAX else old_seed + 1
    elif args.seed is not None:
        new_seed = args.seed
    else:
        new_seed = old_seed
    loc_dir = location_lib.location_dir(name)

    with contextlib.ExitStack() as stack:
        problem = _gates(stack)
        if problem:
            return _error(problem)
        if data["status"] == "trained":
            for sub in ("lora", "tests", "train"):
                shutil.rmtree(os.path.join(loc_dir, sub), ignore_errors=True)
            data["loras"] = {"video": None, "stills": None}
            data["trained_at"] = None
            data["stills_skip_reason"] = None
        data["seed"], data["description"] = new_seed, description
        data["status"], data["dataset"] = "dataset", None
        location_lib.write_location(data)
        print("seed: %d -> %d" % (old_seed, new_seed) if new_seed != old_seed
              else "seed: %d (unchanged)" % old_seed)
        for sub in ("stills", "captions", "videos"):
            shutil.rmtree(os.path.join(loc_dir, sub), ignore_errors=True)
            os.makedirs(os.path.join(loc_dir, sub))
        for rel in ("manifest.json", "contact_sheet.jpg"):
            with contextlib.suppress(FileNotFoundError):
                os.remove(os.path.join(loc_dir, rel))
        os.makedirs(os.path.join(loc_dir, "logs"), exist_ok=True)
        return build_dataset(data, args.force)


def edit(args):
    """bin/location edit NAME --description TEXT (spec 2.12): a photo location's new
    description, saved under the library lock. Returns 0 or 2."""
    name = args.name
    try:
        data = location_lib.load_location(name)
    except location_lib.LocationError as e:
        return _error(e)
    if data["source"] == "text":
        return _error("location %s is a text location: its stills are drawn from its description; "
                      "run bin/location create %s --regenerate --description TEXT (add --force "
                      "when it is trained)" % (name, name))
    description, problem = _description_arg(args.description, data["trigger"])
    if problem:
        return _error(problem)
    with contextlib.ExitStack() as stack:
        try:
            stack.enter_context(character_dataset.library_lock())
        except DatasetError as e:
            return _error(e)
        data = location_lib.load_location(name)
        data["description"] = description
        location_lib.write_location(data)
    print("description: %s" % description)
    return 0


# ---------------------------------------------------------------------------
# train (spec 3.1-3.4)
# ---------------------------------------------------------------------------

def _train_video(data):
    """The video LoRA through character_dataset.train_video_lora (spec 3.3). Returns its
    outcome."""
    name = data["name"]
    loc_dir = location_lib.location_dir(name)
    clips = {}

    def recorded(entry):
        data["loras"]["video"] = {"path": entry["path"], "sha256": entry["sha256"],
                                  "base_model": location_lib.VIDEO_BASE_MODEL,
                                  "rank": entry["rank"], "alpha": entry["alpha"],
                                  "steps": entry["steps"]}
        data["trained_at"] = location_lib.utc_now()
        data["status"] = "trained"
        location_lib.write_location(data)

    def tested(key, path):
        clips[key] = path

    outcome = character_dataset.train_video_lora(
        loc_dir, os.path.join(loc_dir, "videos"), os.path.join(loc_dir, "captions"),
        TEST_PROMPT % data["trigger"], "location %s stays %s" % (name, data["status"]),
        recorded, tested)
    if outcome == "failed":
        return outcome
    entry = data["loras"]["video"]
    print("video LoRA: %s (sha256 %s)" % (entry["path"], entry["sha256"]))
    print("trigger-only A/B (compare by eye; the LoRA clip should show the place, the control a "
          "different place):")
    print("  with LoRA: %s" % clips.get("sample_path"))
    print("  control:   %s" % clips.get("control_path"))
    return outcome


def _train_stills(data):
    """The stills LoRA through character_dataset.train_stills_lora (spec 3.4). Returns its
    outcome."""
    loc_dir = location_lib.location_dir(data["name"])
    with open(os.path.join(loc_dir, "manifest.json"), encoding="utf-8") as f:
        kept_ns = [item["n"] for item in json.load(f)["items"] if item["kept"]]
    pairs = [(still_path(loc_dir, n), os.path.join(loc_dir, "captions", "loc_%02d.txt" % n))
             for n in kept_ns]

    def kept_ok(entry, sample_path, control_path):
        data["loras"]["stills"] = {"path": entry["path"], "sha256": entry["sha256"],
                                   "base_model": location_lib.STILLS_BASE_MODEL,
                                   "rank": entry["rank"], "alpha": entry["alpha"],
                                   "steps": entry["steps"]}
        data["stills_skip_reason"] = None
        location_lib.write_location(data)

    def skipped(reason):
        data["stills_skip_reason"] = reason
        location_lib.write_location(data)

    return character_dataset.train_stills_lora(loc_dir, pairs, TEST_PROMPT % data["trigger"],
                                               data["seed"], kept_ok, skipped)


def train(args):
    """bin/location train NAME (spec 3.2). Returns 0, 1 or 2."""
    name = args.name
    try:
        data = location_lib.load_location(name)
    except location_lib.LocationError as e:
        return _error(e)
    if data["status"] == "dataset":
        kept = data["dataset"]["kept"] if data["dataset"] else 0
        return _error("location %s has no accepted dataset (status dataset, %d of 24 stills kept, "
                      "need 12); fix it with bin/location create %s --regenerate"
                      % (name, kept, name))
    requested = [k for k in ("video", "stills") if getattr(args, k)] or ["video", "stills"]
    explicit_stills = args.stills
    for kind in requested:
        if data["loras"][kind] is not None and not args.force:
            return _error("location %s already has a %s LoRA (%s); pass --force to retrain it"
                          % (name, kind, data["loras"][kind]["path"]))
    loc_dir = location_lib.location_dir(name)

    with contextlib.ExitStack() as stack:
        try:
            stack.enter_context(character_dataset.library_lock())
        except DatasetError as e:
            return _error(e)
        busy = character_dataset.busy_process()
        if busy is not None:
            return _error("a render or training process is running (pid %d: %s); bin/location "
                          "never trains or generates concurrently with a render" % busy)
        state = character_dataset.story_server_state()
        if state != "STOPPED":
            return _error("the story server is %s; stop it first with bin/story-server stop "
                          "(training needs its memory)" % state)
        avail = psutil.virtual_memory().available / 2 ** 30
        if avail < character_dataset.TRAIN_MIN_AVAIL_GIB:
            return _error("only %.1f GiB of memory is available; training needs 30 GiB (quit "
                          "memory-heavy apps and retry)" % avail)
        need = character_dataset.TRAIN_MIN_FREE_GIB_PER_KIND * len(requested)
        free = character_dataset.free_gib(loc_dir)
        if free < need:
            return _error("only %.1f GiB free at %s; training %s needs %d GiB"
                          % (free, loc_dir, " and ".join(requested), need))
        if "video" in requested:
            model_dir = character_dataset.TRAIN_MODEL_DIR
            if (not os.path.isfile(os.path.join(model_dir, "transformer-dev.safetensors"))
                    or os.path.exists(os.path.join(model_dir, "transformer.safetensors"))
                    or os.path.exists(os.path.join(model_dir,
                                                   "transformer-distilled.safetensors"))):
                return _error("%s must contain transformer-dev.safetensors and neither "
                              "transformer.safetensors nor transformer-distilled.safetensors "
                              "(the trainer would pick those first)" % model_dir)
            if not os.path.isdir(character_dataset.TEST_MODEL_DIR):
                return _error("test-render model not found: %s" % character_dataset.TEST_MODEL_DIR)
            binary = character_dataset.SKILL.LTX2_MLX_BIN
            if not (os.path.isfile(binary) and os.access(binary, os.X_OK)):
                return _error("ltx-2-mlx binary not found or not executable: %s" % binary)

        stills_outcome = "ok"
        mflux = character_dataset.MFLUX_TRAIN
        if "stills" in requested and not (os.path.isfile(mflux) and os.access(mflux, os.X_OK)):
            data["stills_skip_reason"] = "mflux-train not found at %s" % mflux
            location_lib.write_location(data)
            print("stills LoRA skipped: %s; %s" % (data["stills_skip_reason"], SKIP_INSTALL_HINT))
            requested.remove("stills")
            stills_outcome = "skipped"

        video_outcome = "ok"
        if "video" in requested:
            video_outcome = _train_video(data)
            if video_outcome == "failed":
                return 1
        if "stills" in requested:
            stills_outcome = _train_stills(data)
        if (video_outcome == "test_failed" or stills_outcome == "failed"
                or (stills_outcome == "skipped" and explicit_stills)):
            return 1
        return 0
