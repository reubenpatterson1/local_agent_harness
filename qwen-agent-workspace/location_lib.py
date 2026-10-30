"""location_lib -- the location library's schema, validation, triggers, resolution and plan reader.

Stdlib only. This module is the single owner of the location.json schema (schema_version 1), of
the location name, description and trigger rules, of resolving pinned locations (--location NAME)
into LocationPin records, and of reading a story's plan.json for the panels set at a pinned
location. bin/location list/show import it at top level; bin/ltx-movie, bin/ltx-story-manifest
and bin/ltx-story-images load it by path, and only when --location is given. It loads
character_lib.py by path, and only inside the trigger functions that need the character registry.

The library root is $LOCATION_LIBRARY_DIR when set (test infrastructure only), else
<workspace>/generated/locations.

See docs/superpowers/specs/2026-10-29-location-lora-design.md, Sections 1.3, 2.1-2.4, 3.6-3.9,
4.2 and 4.7.
"""

import collections
import datetime
import importlib.machinery
import json
import os
import re
import sys
import uuid

WS = os.path.dirname(os.path.realpath(__file__))
LIBRARY_ENV = "LOCATION_LIBRARY_DIR"
SCHEMA_VERSION = 1
NAME_RE = re.compile(r"[a-z][a-z0-9-]{1,23}")
TRIGGER_RE = re.compile(r"[a-z][a-z0-9]{3,15}")          # character_lib.TRIGGER_RE
SHA256_RE = re.compile(r"[0-9a-f]{64}")
UTC_RE = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z")
TRIGGER_REGISTRY = ".triggers"
STATUSES = ("dataset", "untrained", "trained")
SOURCES = ("text", "photos")
MIN_SCORE = 7
MIN_KEEP = 12
TOTAL_STILLS = 24
MAX_PHOTOS = 24
MAX_LOCATIONS = 3
DESCRIPTION_MIN_WORDS = 15
DESCRIPTION_MAX_WORDS = 40
DEFAULT_LOCATION_STRENGTH = 0.8
TRIGGER_CLASS_NOUN = "place"
VIDEO_BASE_MODEL = "dgrauet/ltx-2.3-mlx-q8"
STILLS_BASE_MODEL = "Tongyi-MAI/Z-Image-Turbo"
PLAN_SCHEMA = "ltx-movie.plan.v1"
LIST_ROW_FORMAT = "%-16s %-16s %-9s %-6s %-5s %-6s %s"
NO_LOCATIONS_AVAILABLE = "available locations: none (create one with bin/location create)"
NO_PLAN_NOTE = ("note: there is no plan.json for this story; no location LoRAs are attached "
                "(location LoRAs attach only to planned beats)")
UNUSABLE_PLAN_NOTE = ("note: plan.json is not usable for locations (%s); no location LoRAs are "
                      "attached")

_TOP_LEVEL_KEYS = frozenset([
    "schema_version", "name", "trigger", "description", "source", "photos", "seed", "status",
    "created_at", "trained_at", "dataset", "loras", "stills_skip_reason", "strength"])
_DATASET_KEYS = frozenset(["kept", "total", "min_score", "contact_sheet"])
_LORA_KEYS = frozenset(["path", "sha256", "base_model", "rank", "alpha", "steps"])
_PHOTO_KEYS = frozenset(["path", "sha256"])
_WORD_RE = re.compile(r"[a-z0-9]+")
_FORBIDDEN_CHARS = (".", "!", "?", '"', "\n", "\r")


class LocationError(Exception):
    """A location library problem: bad input, a missing or invalid record, or a pin that cannot
    be resolved. The message is printed after "Error: "."""


class UnusableLocationError(LocationError):
    """The named location does not exist, cannot be loaded, or cannot render (not trained, or
    its video LoRA is missing or empty). bin/ltx-movie appends
    format_available_line(usable_locations()) (spec 3.9)."""


LocationPin = collections.namedtuple("LocationPin", [
    "name", "trigger", "description", "video_lora", "stills_lora", "stills_skip_reason",
    "strength", "base_model", "attach_video"])


def library_dir():
    return os.environ.get(LIBRARY_ENV) or os.path.join(WS, "generated", "locations")


def location_dir(name):
    return os.path.join(library_dir(), name)


def location_json_path(name):
    return os.path.join(library_dir(), name, "location.json")


def utc_now():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _character_lib():
    """character_lib.py loaded by path (spec 1.2); the copy already in sys.modules is reused
    when it was loaded from the same file, so a caller's character_lib state is never reset."""
    path = os.path.join(WS, "character_lib.py")
    loaded = sys.modules.get("character_lib")
    if loaded is not None and os.path.realpath(getattr(loaded, "__file__", None) or "") \
            == os.path.realpath(path):
        return loaded
    return importlib.machinery.SourceFileLoader("character_lib", path).load_module()


def _is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def _is_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _is_abs_path(value):
    return isinstance(value, str) and os.path.isabs(value)


def validate_name(name):
    if not isinstance(name, str) or not NAME_RE.fullmatch(name):
        raise LocationError("location name must match [a-z][a-z0-9-]{1,23}, got %r" % (name,))


def normalize_description(text):
    """Whitespace runs collapsed to one space, stripped, one trailing "." dropped and stripped
    again, the first character lower-cased when it is upper-case (spec 2.3). A non-string is
    returned unchanged (validate_description refuses it)."""
    if not isinstance(text, str):
        return text
    text = " ".join(text.split())
    if text.endswith("."):
        text = text[:-1].strip()
    if text[:1].isupper():
        text = text[0].lower() + text[1:]
    return text


def validate_description(text):
    """The description rule of spec 2.3. Raises LocationError("description: <reason>")."""
    if not isinstance(text, str) or text != text.strip():
        raise LocationError("description: must be a string without leading or trailing "
                            "whitespace, got %r" % (text,))
    words = len(text.split())
    if not DESCRIPTION_MIN_WORDS <= words <= DESCRIPTION_MAX_WORDS:
        raise LocationError("description: must be 15-40 words, got %d" % words)
    if not text.startswith(("a ", "an ", "the ")):
        raise LocationError('description: must start with "a ", "an " or "the "')
    if any(c in text for c in _FORBIDDEN_CHARS):
        raise LocationError("description: must be one noun phrase with no . ! ? or double quote")


def description_words(description):
    """The lower-case words of a description, as the trigger rule compares them (spec 2.4)."""
    return _WORD_RE.findall(description.lower())


def validate_trigger(trigger, description=None):
    """The given-trigger rules of spec 2.4 that need no registry: TRIGGER_RE, and (when the
    description is known) not a word of the description."""
    if not isinstance(trigger, str) or not TRIGGER_RE.fullmatch(trigger):
        raise LocationError("trigger must match [a-z][a-z0-9]{3,15}, got %r" % (trigger,))
    if description is not None and trigger in description_words(description):
        raise LocationError("trigger %s must not be a word of the description" % trigger)


def _validate_lora_entry(field, entry):
    if not isinstance(entry, dict) or set(entry) != _LORA_KEYS:
        raise LocationError("%s: must be null or an object with exactly the keys %s, got %r"
                            % (field, ", ".join(sorted(_LORA_KEYS)), entry))
    if not _is_abs_path(entry["path"]):
        raise LocationError("%s: path must be an absolute path, got %r" % (field, entry["path"]))
    if not isinstance(entry["sha256"], str) or not SHA256_RE.fullmatch(entry["sha256"]):
        raise LocationError("%s: sha256 must be 64 lowercase hex characters, got %r"
                            % (field, entry["sha256"]))
    if not isinstance(entry["base_model"], str) or not entry["base_model"]:
        raise LocationError("%s: base_model must be a non-empty string, got %r"
                            % (field, entry["base_model"]))
    if not _is_int(entry["rank"]) or entry["rank"] < 1:
        raise LocationError("%s: rank must be an int >= 1, got %r" % (field, entry["rank"]))
    if not _is_int(entry["alpha"]) or entry["alpha"] != entry["rank"]:
        raise LocationError("%s: alpha must be an int equal to rank (%r), got %r"
                            % (field, entry["rank"], entry["alpha"]))
    if not _is_int(entry["steps"]) or entry["steps"] < 1:
        raise LocationError("%s: steps must be an int >= 1, got %r" % (field, entry["steps"]))


def validate_location(data, name=None):
    """Strict schema_version 1 validation (spec 3.7). Raises LocationError("<field>: <reason>").
    File existence is not checked here."""
    if not isinstance(data, dict):
        raise LocationError("top level: must be a JSON object, got %s" % type(data).__name__)
    missing = sorted(_TOP_LEVEL_KEYS - set(data))
    if missing:
        raise LocationError("top level: missing keys %s" % ", ".join(missing))
    extra = sorted(set(data) - _TOP_LEVEL_KEYS)
    if extra:
        raise LocationError("top level: unexpected keys %s" % ", ".join(extra))
    if not _is_int(data["schema_version"]) or data["schema_version"] != SCHEMA_VERSION:
        raise LocationError("schema_version: must be %d, got %r"
                            % (SCHEMA_VERSION, data["schema_version"]))
    if not isinstance(data["name"], str) or not NAME_RE.fullmatch(data["name"]):
        raise LocationError("name: must match [a-z][a-z0-9-]{1,23}, got %r" % (data["name"],))
    if name is not None and data["name"] != name:
        raise LocationError("name: %r does not match its directory name %r" % (data["name"], name))
    trigger = data["trigger"]
    if not isinstance(trigger, str) or not TRIGGER_RE.fullmatch(trigger):
        raise LocationError("trigger: must match [a-z][a-z0-9]{3,15}, got %r" % (trigger,))
    validate_description(data["description"])
    if trigger in description_words(data["description"]):
        raise LocationError("trigger: %r must not be a word of the description" % (trigger,))
    if data["source"] not in SOURCES:
        raise LocationError('source: must be "text" or "photos", got %r' % (data["source"],))
    photos = data["photos"]
    if data["source"] == "text":
        if photos != []:
            raise LocationError("photos: must be [] for a text location, got %r" % (photos,))
    else:
        if not isinstance(photos, list) or not 1 <= len(photos) <= MAX_PHOTOS:
            raise LocationError("photos: must be a list of 1 to 24 objects for a photo location, "
                                "got %r" % (photos,))
        for k, photo in enumerate(photos, start=1):
            if (not isinstance(photo, dict) or set(photo) != _PHOTO_KEYS
                    or not (photo["path"] is None or _is_abs_path(photo["path"]))
                    or not isinstance(photo["sha256"], str)
                    or not SHA256_RE.fullmatch(photo["sha256"])):
                raise LocationError("photos: item %d must be an object with exactly the keys path "
                                    "(absolute or null) and sha256 (64 lowercase hex), got %r"
                                    % (k, photo))
    if not _is_int(data["seed"]) or data["seed"] < 0:
        raise LocationError("seed: must be an int >= 0, got %r" % (data["seed"],))
    if data["status"] not in STATUSES:
        raise LocationError("status: must be one of %s, got %r"
                            % (", ".join(STATUSES), data["status"]))
    if not isinstance(data["created_at"], str) or not UTC_RE.fullmatch(data["created_at"]):
        raise LocationError("created_at: must be a UTC timestamp YYYY-MM-DDTHH:MM:SSZ, got %r"
                            % (data["created_at"],))
    trained_at = data["trained_at"]
    if trained_at is not None and (not isinstance(trained_at, str)
                                   or not UTC_RE.fullmatch(trained_at)):
        raise LocationError("trained_at: must be null or a UTC timestamp YYYY-MM-DDTHH:MM:SSZ, "
                            "got %r" % (trained_at,))
    dataset = data["dataset"]
    if dataset is not None:
        if not isinstance(dataset, dict) or set(dataset) != _DATASET_KEYS:
            raise LocationError("dataset: must be null or an object with exactly the keys %s, "
                                "got %r" % (", ".join(sorted(_DATASET_KEYS)), dataset))
        if (not _is_int(dataset["kept"]) or not _is_int(dataset["total"])
                or not 0 <= dataset["kept"] <= dataset["total"]):
            raise LocationError("dataset: kept and total must be ints with 0 <= kept <= total, "
                                "got kept=%r total=%r" % (dataset["kept"], dataset["total"]))
        if not _is_int(dataset["min_score"]) or not 1 <= dataset["min_score"] <= 10:
            raise LocationError("dataset: min_score must be an int from 1 to 10, got %r"
                                % (dataset["min_score"],))
        if not _is_abs_path(dataset["contact_sheet"]):
            raise LocationError("dataset: contact_sheet must be an absolute path, got %r"
                                % (dataset["contact_sheet"],))
    loras = data["loras"]
    if not isinstance(loras, dict) or set(loras) != {"video", "stills"}:
        raise LocationError("loras: must be an object with exactly the keys stills, video, got %r"
                            % (loras,))
    for kind in ("video", "stills"):
        if loras[kind] is not None:
            _validate_lora_entry("loras.%s" % kind, loras[kind])
    reason = data["stills_skip_reason"]
    if reason is not None and (not isinstance(reason, str) or not reason):
        raise LocationError("stills_skip_reason: must be null or a non-empty string, got %r"
                            % (reason,))
    strength = data["strength"]
    if strength is not None and (not _is_number(strength) or not 0 < strength <= 1.0):
        raise LocationError("strength: must be null or a number in (0, 1], got %r" % (strength,))
    trained = data["status"] == "trained"
    if trained != (loras["video"] is not None):
        raise LocationError('status: %r is inconsistent with loras.video (%s); status is '
                            '"trained" exactly when a video LoRA is recorded'
                            % (data["status"], "null" if loras["video"] is None else "set"))
    if trained != (trained_at is not None):
        raise LocationError('trained_at: %r is inconsistent with status %r; trained_at is set '
                            'exactly when status is "trained"' % (trained_at, data["status"]))
    if data["status"] in ("untrained", "trained") and (dataset is None
                                                        or dataset["kept"] < MIN_KEEP):
        raise LocationError("status: %r requires a dataset with at least %d kept stills"
                            % (data["status"], MIN_KEEP))


def load_location(name):
    validate_name(name)
    path = location_json_path(name)
    if not os.path.isfile(path):
        raise LocationError("unknown location: %s (no %s)" % (name, path))
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        validate_location(data, name=name)
    except (ValueError, LocationError) as e:
        raise LocationError("invalid location.json for %s: %s" % (name, e))
    return data


def write_location(data):
    """Validate, then atomically replace <lib>/<name>/location.json. The directory must already
    exist."""
    validate_location(data)
    path = location_json_path(data["name"])
    temporary = "%s.%s.tmp" % (path, uuid.uuid4().hex)
    try:
        with open(temporary, "x", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            f.write("\n")
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def list_names():
    lib = library_dir()
    if not os.path.isdir(lib):
        return []
    return sorted(n for n in os.listdir(lib)
                  if NAME_RE.fullmatch(n) and os.path.isfile(location_json_path(n)))


def registered_triggers():
    """{trigger: location name}: the .triggers registry, then every readable location.json
    trigger. Registry entries win on conflict; triggers are never reused (spec 2.4)."""
    triggers = {}
    registry = os.path.join(library_dir(), TRIGGER_REGISTRY)
    if os.path.isfile(registry):
        with open(registry, encoding="utf-8") as f:
            for line in f:
                fields = line.split()
                if len(fields) == 2:
                    triggers.setdefault(fields[0], fields[1])
    for name in list_names():
        try:
            with open(location_json_path(name), encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            continue
        trigger = data.get("trigger") if isinstance(data, dict) else None
        if isinstance(trigger, str):
            triggers.setdefault(trigger, name)
    return triggers


def register_trigger(trigger, name):
    lib = library_dir()
    os.makedirs(lib, exist_ok=True)
    with open(os.path.join(lib, TRIGGER_REGISTRY), "a", encoding="utf-8") as f:
        f.write("%s %s\n" % (trigger, name))


def all_triggers():
    """{trigger: owner}: every location trigger (owner "location NAME"), then every character
    trigger (owner "character NAME", character_lib.registered_triggers()). A location trigger
    wins on conflict (spec 2.4)."""
    owners = dict((t, "location %s" % n) for t, n in registered_triggers().items())
    for trigger, name in _character_lib().registered_triggers().items():
        owners.setdefault(trigger, "character %s" % name)
    return owners


def auto_trigger(name, description, taken):
    """The rare-token trigger of spec 2.4: character_lib.auto_trigger with the class noun
    "place", avoiding the description's words."""
    return _character_lib().auto_trigger(name, TRIGGER_CLASS_NOUN, taken,
                                         avoid=description_words(description))


def model_compatible(base_model, model):
    """True when a video LoRA trained for base_model may attach to bin/ltx-movie --model model
    (spec 3.8): the same id, or the recorded HF base and its local ltx-2-mlx copy."""
    if model == base_model:
        return True
    if base_model != VIDEO_BASE_MODEL:
        return False
    local = os.path.join(os.path.expanduser(os.environ.get("LTX2_MLX_DIR", "~/ltx-2-mlx")),
                         "models", "ltx-2.3-mlx-q8")
    return os.path.realpath(os.path.expanduser(model)) == os.path.realpath(local)


def _readable_nonempty(path):
    return os.path.isfile(path) and os.access(path, os.R_OK) and os.path.getsize(path) > 0


def _pin(name):
    try:
        data = load_location(name)
    except LocationError as e:
        raise UnusableLocationError(str(e))
    if data["status"] != "trained":
        raise UnusableLocationError("location %s is not trained (status %s); run bin/location "
                                    "train %s" % (name, data["status"], name))
    video = data["loras"]["video"]
    if not _readable_nonempty(video["path"]):
        raise UnusableLocationError("location %s's video LoRA is missing or empty: %s"
                                    % (name, video["path"]))
    stills = data["loras"]["stills"]["path"] if data["loras"]["stills"] else None
    if stills is not None and not _readable_nonempty(stills):
        raise LocationError("location %s's stills LoRA is missing or empty: %s" % (name, stills))
    return LocationPin(name, data["trigger"], data["description"], video["path"], stills,
                       data["stills_skip_reason"], data["strength"], video["base_model"], True)


def resolve_locations(names):
    """[LocationPin] for --location NAME ... in order, every one with attach_video=True (spec
    3.9). Raises LocationError (UnusableLocationError for a location that cannot render)."""
    names = list(names)
    if len(names) > MAX_LOCATIONS:
        raise LocationError("at most 3 locations, got %d" % len(names))
    for name in names:
        if names.count(name) > 1:
            raise LocationError("location %s is pinned more than once" % name)
    pins = [_pin(name) for name in names]
    by_trigger = {}
    for pin in pins:
        if pin.trigger in by_trigger:
            raise LocationError("locations %s and %s share the trigger %s"
                                % (by_trigger[pin.trigger], pin.name, pin.trigger))
        by_trigger[pin.trigger] = pin.name
    return pins


def usable_locations():
    """Sorted names of the library locations that resolve_locations accepts on their own."""
    usable = []
    for name in list_names():
        try:
            resolve_locations([name])
        except LocationError:
            continue
        usable.append(name)
    return usable


def format_available_line(names):
    """One line naming the usable locations; names is usable_locations()'s list."""
    if not names:
        return NO_LOCATIONS_AVAILABLE
    return "available locations: " + ", ".join(names)


def location_table_lines():
    """The library table printed by bin/location list (spec 2.2)."""
    names = list_names()
    if not names:
        return ["no locations in %s" % library_dir()]
    lines = [LIST_ROW_FORMAT % ("NAME", "TRIGGER", "STATUS", "SOURCE", "VIDEO", "STILLS",
                                "DESCRIPTION")]
    for name in names:
        try:
            data = load_location(name)
        except LocationError as e:
            lines.append("%-16s (invalid: %s)" % (name, e))
            continue
        lines.append(LIST_ROW_FORMAT % (
            name, data["trigger"], data["status"], data["source"],
            "yes" if data["loras"]["video"] else "no",
            "yes" if data["loras"]["stills"] else "no", data["description"]))
    return lines


def _read_plan(story_dir):
    """(plan, None) for a usable plan.json of story_dir, (None, reason) for an unusable one, or
    (None, None) when there is no plan.json. Usable: a JSON object of PLAN_SCHEMA whose
    locations are a list of objects."""
    path = os.path.join(story_dir, "plan.json")
    if not os.path.exists(path):
        return None, None
    try:
        with open(path, encoding="utf-8") as f:
            plan = json.load(f)
    except (OSError, ValueError):
        plan = None
    if not isinstance(plan, dict):
        return None, "it is unreadable or not a JSON object"
    if plan.get("schema") != PLAN_SCHEMA:
        return None, "its schema is not ltx-movie.plan.v1"
    if (not isinstance(plan.get("locations"), list)
            or not all(isinstance(e, dict) for e in plan["locations"])):
        return None, "its locations are not a list of objects"
    return plan, None


def plan_location_names(story_dir):
    """The set of library location names story_dir's plan.json pins (its location entries'
    non-empty "location_name" strings), or None when there is no usable plan.json (spec 4.2)."""
    plan, _reason = _read_plan(story_dir)
    if plan is None:
        return None
    return set(e["location_name"] for e in plan["locations"]
               if isinstance(e.get("location_name"), str) and e["location_name"])


def plan_panel_locations(story_dir, n_panels, names):
    """([library location name or None for each of n_panels panels], note or None) from
    story_dir's plan.json (spec 4.7): panel k carries the name of beat k's location when that
    location entry's location_name is in names. Without a usable plan every panel is None and
    the note says why."""
    empty = [None] * n_panels
    plan, reason = _read_plan(story_dir)
    if plan is None and reason is None:
        return empty, NO_PLAN_NOTE
    if plan is not None:
        beats = plan.get("beats") if isinstance(plan.get("beats"), list) else []
        if len(beats) != n_panels:
            reason = "it has %d beats for %d panels" % (len(beats), n_panels)
        else:
            for k, beat in enumerate(beats, start=1):
                if (not isinstance(beat, dict) or not isinstance(beat.get("location"), str)
                        or not beat["location"]):
                    reason = "beat %d has no location id" % k
                    break
    if reason is not None:
        return empty, UNUSABLE_PLAN_NOTE % reason
    by_id = {}
    for entry in plan["locations"]:
        if isinstance(entry.get("id"), str):
            by_id.setdefault(entry["id"], entry.get("location_name"))
    out = []
    for beat in plan["beats"]:
        name = by_id.get(beat["location"])
        out.append(name if name in names else None)
    return out, None


def prefix_location_trigger(prompt, trigger):
    """prompt with "<trigger>. " in front unless the trigger already occurs in it as a whole
    word, in any case (spec 4.7; the rule of character_lib.prefix_character_triggers)."""
    if re.search(r"(?<![\w-])" + re.escape(trigger) + r"(?![\w-])", prompt, re.IGNORECASE):
        return prompt
    return trigger + ". " + prompt
