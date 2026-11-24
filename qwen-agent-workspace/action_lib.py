#!/usr/bin/env python3
"""action_lib -- the action LoRA library (generated/actions/), stdlib only.

An action LoRA is an identity-agnostic MOTION LoRA for the LTX-2.3 video DiT: it
captures what a character does over time (a roundhouse kick, a sword draw), as
opposed to a character LoRA which captures who is on screen. This module owns the
on-disk library the way character_lib.py owns generated/characters/: the
schema_version 1 action.json shape, strict validation, atomic writes, and the
read helpers bin/action and ltx-movie use.

Spec: docs/superpowers/specs/2026-10-20-action-lora-motion-library-design.md
(Phase 1: the library + action.json + validation). It parallels character_lib.py;
the trigger here is a Motion: PHRASE (e.g. "performs a roundhouse kick"), matching
lora_catalog's TRIGGER_RE, not character_lib's single-word trigger.

The library root is $ACTION_LIBRARY_DIR when set (test infrastructure only, like
CHARACTER_LIBRARY_DIR), else <workspace>/generated/actions.
"""

import datetime
import json
import os
import re
import uuid

WS = os.path.dirname(os.path.realpath(__file__))
LIBRARY_ENV = "ACTION_LIBRARY_DIR"
SCHEMA_VERSION = 1

NAME_RE = re.compile(r"[a-z][a-z0-9-]{1,31}")
# Trigger is a Motion: phrase, not a single word -- same shape as lora_catalog.TRIGGER_RE.
TRIGGER_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9 _'-]{0,39}")
SHA256_RE = re.compile(r"[0-9a-f]{64}")
UTC_RE = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z")

KIND = "motion"                 # an action LoRA is always a motion LoRA
TARGET = "video"                # ... applied to the video DiT
STATUSES = ("dataset", "untrained", "trained")
SOURCE_TYPES = ("clips",)
MIN_CLIPS = 8                   # fewer than the character MIN_KEEP: clips carry many frames
MIN_PERFORMERS = 3              # identity-agnostic: varied performers (spec 3.2)
DEFAULT_ACTION_STRENGTH = 0.7
# Folder ingestion (docs/superpowers/specs/2026-11-23-bulk-action-clips-design.md, 2.1)
CLIP_EXTS = (".mp4", ".mov", ".m4v", ".webm", ".mkv")     # = movie_ui_server.ACTION_CLIP_EXTS
CLIP_NAME_RE = re.compile(r"([0-9]+)_([0-9]+)_([A-Za-z0-9_-]+)\.([A-Za-z0-9]+)")
MOVE_RE = re.compile(r"[a-z][a-z0-9]*(?: [a-z0-9]+)*")
MAX_MOVES = 8
MAX_MOVE_CHARS = 40
MAX_DIR_CLIPS = 1000            # = ACTION_STEPS at batch size 1: past it some clips are never seen
CLIP_NAME_HINT = "<n>_<n>_<moves>.<ext>"

_TOP_LEVEL_KEYS = {"schema_version", "name", "kind", "trigger", "descriptor",
                   "default_strength", "strength_range", "source", "identity_agnostic",
                   "dataset", "lora", "status", "created_at"}
_LORA_KEYS = {"path", "sha256", "rank", "alpha", "base_model"}


class ActionError(Exception):
    """An action library problem: bad input, or a missing or invalid record. The
    message is printed after "Error: "."""


def _is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def _is_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _is_abs_path(value):
    return isinstance(value, str) and os.path.isabs(value)


def utc_now():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def library_dir():
    return os.environ.get(LIBRARY_ENV) or os.path.join(WS, "generated", "actions")


def action_dir(name):
    return os.path.join(library_dir(), name)


def action_json_path(name):
    return os.path.join(library_dir(), name, "action.json")


def validate_name(name):
    if not isinstance(name, str) or not NAME_RE.fullmatch(name):
        raise ActionError("action name must match [a-z][a-z0-9-]{1,31}, got %r" % (name,))


def validate_trigger(trigger):
    """A Motion: phrase: matches TRIGGER_RE and is whitespace-normalized."""
    if not isinstance(trigger, str) or not TRIGGER_RE.fullmatch(trigger):
        raise ActionError("trigger: must match [A-Za-z0-9][A-Za-z0-9 _'-]{0,39}, got %r" % (trigger,))
    if trigger != " ".join(trigger.split()):
        raise ActionError("trigger: must be whitespace-normalized (single spaces, no edges), got %r"
                          % (trigger,))


def validate_descriptor(text):
    """A noun phrase describing the motion, appearance-free (spec 3.2/3.3)."""
    if not isinstance(text, str):
        raise ActionError("descriptor: must be a string, got %r" % (text,))
    if text != text.strip():
        raise ActionError("descriptor: must not have leading or trailing whitespace")
    words = len(text.split())
    if not 8 <= words <= 60:
        raise ActionError("descriptor: must be 8-60 words, got %d" % words)
    if not (text.startswith("a ") or text.startswith("an ")):
        raise ActionError('descriptor: must start with "a " or "an ", got %r' % (text[:30],))
    if text.endswith("."):
        raise ActionError('descriptor: must not end with "."')


def _validate_lora(lora):
    if not isinstance(lora, dict):
        raise ActionError("lora: must be an object or null, got %s" % type(lora).__name__)
    missing = sorted(_LORA_KEYS - set(lora))
    if missing:
        raise ActionError("lora: missing keys %s" % ", ".join(missing))
    extra = sorted(set(lora) - _LORA_KEYS)
    if extra:
        raise ActionError("lora: unexpected keys %s" % ", ".join(extra))
    if not _is_abs_path(lora["path"]):
        raise ActionError("lora.path: must be an absolute path, got %r" % (lora["path"],))
    if not isinstance(lora["sha256"], str) or not SHA256_RE.fullmatch(lora["sha256"]):
        raise ActionError("lora.sha256: must be 64 lowercase hex characters, got %r" % (lora["sha256"],))
    if not _is_int(lora["rank"]) or lora["rank"] < 1:
        raise ActionError("lora.rank: must be an int >= 1, got %r" % (lora["rank"],))
    if not _is_int(lora["alpha"]) or lora["alpha"] != lora["rank"]:
        raise ActionError("lora.alpha: must equal rank (%r); ltx-2-mlx fuses B@A*strength with no "
                          "alpha/rank scaling, so a mismatch renders at the wrong strength"
                          % (lora["rank"],))
    if not isinstance(lora["base_model"], str) or not lora["base_model"]:
        raise ActionError("lora.base_model: must be a non-empty string, got %r" % (lora["base_model"],))


def validate_action(data, name=None):
    """Strict schema_version 1 validation (spec 2.2). Raises ActionError("<field>:
    <reason>"). File existence is not checked here."""
    if not isinstance(data, dict):
        raise ActionError("top level: must be a JSON object, got %s" % type(data).__name__)
    missing = sorted(_TOP_LEVEL_KEYS - set(data))
    if missing:
        raise ActionError("top level: missing keys %s" % ", ".join(missing))
    extra = sorted(set(data) - _TOP_LEVEL_KEYS)
    if extra:
        raise ActionError("top level: unexpected keys %s" % ", ".join(extra))
    if not _is_int(data["schema_version"]) or data["schema_version"] != SCHEMA_VERSION:
        raise ActionError("schema_version: must be %d, got %r" % (SCHEMA_VERSION, data["schema_version"]))
    if not isinstance(data["name"], str) or not NAME_RE.fullmatch(data["name"]):
        raise ActionError("name: must match [a-z][a-z0-9-]{1,31}, got %r" % (data["name"],))
    if name is not None and data["name"] != name:
        raise ActionError("name: %r does not match its directory name %r" % (data["name"], name))
    if data["kind"] != KIND:
        raise ActionError('kind: must be %r (an action is a motion LoRA), got %r' % (KIND, data["kind"]))
    validate_trigger(data["trigger"])
    validate_descriptor(data["descriptor"])
    default = data["default_strength"]
    span = data["strength_range"]
    if not _is_number(default):
        raise ActionError("default_strength: must be a number, got %r" % (default,))
    if (not isinstance(span, list) or len(span) != 2 or not all(_is_number(v) for v in span)):
        raise ActionError("strength_range: must be a list of two numbers, got %r" % (span,))
    if not 0 < span[0] <= default <= span[1] <= 2:
        raise ActionError("strength_range and default_strength must satisfy 0 < lo <= default <= "
                          "hi <= 2, got range %r and default %r" % (span, default))
    source = data["source"]
    if not (isinstance(source, dict) and set(source) == {"type", "paths"}
            and source["type"] in SOURCE_TYPES
            and isinstance(source["paths"], list) and source["paths"]
            and all(_is_abs_path(p) for p in source["paths"])):
        raise ActionError('source: must be {"type": "clips", "paths": [<absolute path>, ...]} with a '
                          "non-empty list of absolute paths, got %r" % (source,))
    if not isinstance(data["identity_agnostic"], bool):
        raise ActionError("identity_agnostic: must be a boolean, got %r" % (data["identity_agnostic"],))
    if not (data["dataset"] is None or isinstance(data["dataset"], dict)):
        raise ActionError("dataset: must be an object or null, got %s" % type(data["dataset"]).__name__)
    if data["lora"] is not None:
        _validate_lora(data["lora"])
    if data["status"] not in STATUSES:
        raise ActionError("status: must be one of %s, got %r" % (", ".join(STATUSES), data["status"]))
    if not isinstance(data["created_at"], str) or not UTC_RE.fullmatch(data["created_at"]):
        raise ActionError("created_at: must be a UTC timestamp YYYY-MM-DDTHH:MM:SSZ, got %r"
                          % (data["created_at"],))


def new_action(name, trigger, descriptor, source_paths, *, default_strength=DEFAULT_ACTION_STRENGTH,
               strength_range=None, identity_agnostic=True):
    """A fresh, valid action.json dict (status "dataset", no dataset/lora yet). Raises
    ActionError on invalid input."""
    validate_name(name)
    data = {
        "schema_version": SCHEMA_VERSION,
        "name": name,
        "kind": KIND,
        "trigger": trigger,
        "descriptor": descriptor,
        "default_strength": default_strength,
        "strength_range": list(strength_range) if strength_range is not None else [0.4, 1.0],
        "source": {"type": "clips", "paths": [os.path.abspath(p) for p in source_paths]},
        "identity_agnostic": bool(identity_agnostic),
        "dataset": None,
        "lora": None,
        "status": "dataset",
        "created_at": utc_now(),
    }
    validate_action(data)
    return data


def write_action(data):
    """Validate, then atomically replace <lib>/<name>/action.json. The directory must
    already exist."""
    validate_action(data)
    path = action_json_path(data["name"])
    temporary = "%s.%s.tmp" % (path, uuid.uuid4().hex)
    try:
        with open(temporary, "x", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            f.write("\n")
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def load_action(name):
    validate_name(name)
    path = action_json_path(name)
    if not os.path.isfile(path):
        raise ActionError("unknown action: %s (no %s)" % (name, path))
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        validate_action(data, name=name)
    except (ValueError, ActionError) as e:
        raise ActionError("invalid action.json for %s: %s" % (name, e))
    return data


def list_names():
    lib = library_dir()
    if not os.path.isdir(lib):
        return []
    return sorted(n for n in os.listdir(lib)
                  if NAME_RE.fullmatch(n) and os.path.isfile(action_json_path(n)))


def registered_triggers():
    """{trigger: name} for every trained action in the library (status 'trained').
    Untrained actions are not offered to the planner."""
    triggers = {}
    for name in list_names():
        try:
            data = load_action(name)
        except ActionError:
            continue
        if data["status"] == "trained":
            triggers[data["trigger"]] = name
    return triggers


# ---------------------------------------------------------------------------
# Folder ingestion: one action from a folder of clips named <n>_<n>_<moves>.<ext>
# (docs/superpowers/specs/2026-11-23-bulk-action-clips-design.md, 2.1)
# ---------------------------------------------------------------------------

def parse_clip_name(name):
    """(moves, None) for a clip file name <n>_<n>_<moves>.<ext>, else (None, reason). Moves are
    split on "-"; "_" inside a move is a space; moves are lowercased and duplicates are kept. The
    first failing check gives the reason (spec 2.1)."""
    if name.startswith("."):
        return None, "hidden file"
    if os.path.splitext(name)[1].lower() not in CLIP_EXTS:
        return None, "not a video (%s)" % ", ".join(CLIP_EXTS)
    m = CLIP_NAME_RE.fullmatch(name)
    if m is None:
        return None, "name does not match %s" % CLIP_NAME_HINT
    moves = []
    for raw in m.group(3).lower().split("-"):
        move = " ".join(raw.replace("_", " ").split())
        if move == "":
            return None, "empty move"
        if len(move) > MAX_MOVE_CHARS:
            return None, "move longer than %d characters" % MAX_MOVE_CHARS
        if not MOVE_RE.fullmatch(move):
            return None, "move '%s' must start with a letter" % move
        moves.append(move)
    if len(moves) > MAX_MOVES:
        return None, "more than %d moves" % MAX_MOVES
    return moves, None


def scan_clip_dir(path):
    """One folder's clips, not recursive: {"dir": <abs>, "clips": [{"name", "path", "moves"}],
    "skipped": [{"name", "reason"}]}. clips sort by the two numbers, then the name; skipped stay
    in name order. It lists the folder and stats its entries; it opens no file. Raises
    ActionError when the folder cannot be listed (spec 2.1.1)."""
    d = os.path.abspath(path)
    unreadable = "folder %s is not a readable directory" % d
    if not (os.path.isdir(d) and os.access(d, os.R_OK | os.X_OK)):
        raise ActionError(unreadable)
    try:
        names = os.listdir(d)
    except OSError:
        raise ActionError(unreadable)
    found, skipped = [], []
    for name in sorted(names):
        full = os.path.join(d, name)
        moves = None
        if name.startswith("."):
            reason = "hidden file"
        elif os.path.isdir(full):
            reason = "folder (not scanned)"
        elif not os.path.isfile(full):
            reason = "not a regular file"
        else:
            moves, reason = parse_clip_name(name)
            if reason is None and not os.access(full, os.R_OK):
                reason = "not readable"
        if reason is not None:
            text = name.encode("utf-8", "surrogateescape").decode("utf-8", "replace")
            skipped.append({"name": text, "reason": reason})
            continue
        m = CLIP_NAME_RE.fullmatch(name)
        found.append(((int(m.group(1)), int(m.group(2)), name), {"name": name, "path": full, "moves": moves}))
    found.sort(key=lambda item: item[0])
    return {"dir": d, "clips": [clip for _key, clip in found], "skipped": skipped}


def clip_caption(trigger, moves):
    """A folder clip's caption, "<trigger>: <m1>, then <m2>, ..." (spec 2.1.2). The caller has
    validated the trigger; TRIGGER_RE has no ":", so the separator is unambiguous."""
    return trigger + ": " + ", then ".join(moves)
