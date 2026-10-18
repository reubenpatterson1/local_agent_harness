"""lora_catalog -- the versioned LoRA catalog (generated/loras/catalog.json).

Stdlib only. This module owns the catalog file: its schema_version 1 shape and validation,
atomic saves under an exclusive lock, the safetensors header reader (rank, alpha, lora_A /
lora_B pairs), the read-only folding of trained library characters, base-model compatibility
and the catalog trigger prefix rule. bin/lora-catalog imports it at top level; bin/ltx-movie,
story_engine.py, bin/ltx-story-manifest and bin/ltx-story-images load it by path, only inside
functions. It loads character_lib.py by path, only inside fold_characters and
character_triggers.

The catalog root is $LORA_CATALOG_DIR when set (test infrastructure only, like
CHARACTER_LIBRARY_DIR), else <workspace>/generated/loras.

See docs/superpowers/specs/2026-10-17-robust-story-lora-catalog-design.md, Section 4.
"""

import datetime
import fcntl
import hashlib
import importlib.machinery
import json
import os
import re
import struct
import uuid

SCHEMA_VERSION = 1
CATALOG_ENV = "LORA_CATALOG_DIR"
STILLS_BASE_MODEL = "Tongyi-MAI/Z-Image-Turbo"
KINDS = ("style", "motion", "physics")
TARGETS = ("video", "stills")
ID_RE = re.compile(r"[a-z][a-z0-9-]{1,31}")
TRIGGER_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9 _'-]{0,39}")
MAX_TRIGGERS = 4
TEXT_MAX = 300
ENTRY_KEYS = ("id", "kind", "path", "sha256", "bytes", "base_models", "target", "triggers",
              "rank", "alpha", "default_strength", "strength_range", "description", "use_when",
              "avoid_when", "added_at")
SHA256_RE = re.compile(r"[0-9a-f]{64}")
UTC_RE = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z")
HEADER_MAX_BYTES = 100 * 1024 * 1024
LORA_A_SUFFIX = ".lora_A.weight"
LORA_B_SUFFIX = ".lora_B.weight"
ALPHA_RANK_MESSAGE = ("alpha must equal rank (%d); ltx-2-mlx fuses B@A*strength with no "
                      "alpha/rank scaling (fuse_loras.py), so this LoRA would render at the "
                      "wrong strength")


class CatalogError(Exception):
    """A catalog problem: an invalid catalog file or entry, or an unreadable LoRA header. The
    message is printed after "Error: "."""


def _is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def _is_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def utc_now():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def catalog_dir(ws):
    return os.environ.get(CATALOG_ENV) or os.path.join(ws, "generated", "loras")


def catalog_path(ws):
    return os.path.join(catalog_dir(ws), "catalog.json")


def empty_catalog():
    return {"schema_version": SCHEMA_VERSION, "entries": []}


def validate_entry(entry):
    """LC3 entry rules. Raises CatalogError("entry <id>: <field> <reason>"). File existence is
    not checked here (verify_entry does that)."""
    if not isinstance(entry, dict):
        raise CatalogError("entry: must be an object, got %s" % type(entry).__name__)
    label = entry.get("id") if isinstance(entry.get("id"), str) else "?"

    def fail(field, reason):
        raise CatalogError("entry %s: %s %s" % (label, field, reason))

    missing = [key for key in ENTRY_KEYS if key not in entry]
    if missing:
        raise CatalogError("entry %s: missing keys %s" % (label, ", ".join(missing)))
    extra = sorted(set(entry) - set(ENTRY_KEYS))
    if extra:
        raise CatalogError("entry %s: unexpected keys %s" % (label, ", ".join(extra)))
    if not isinstance(entry["id"], str) or not ID_RE.fullmatch(entry["id"]):
        fail("id", "must match [a-z][a-z0-9-]{1,31}, got %r" % (entry["id"],))
    if entry["kind"] not in KINDS:
        fail("kind", "must be one of %s, got %r" % (", ".join(KINDS), entry["kind"]))
    if not isinstance(entry["path"], str) or not os.path.isabs(entry["path"]):
        fail("path", "must be an absolute path, got %r" % (entry["path"],))
    if not isinstance(entry["sha256"], str) or not SHA256_RE.fullmatch(entry["sha256"]):
        fail("sha256", "must be 64 lowercase hex characters, got %r" % (entry["sha256"],))
    if not _is_int(entry["bytes"]) or entry["bytes"] < 1:
        fail("bytes", "must be an int >= 1, got %r" % (entry["bytes"],))
    models = entry["base_models"]
    if (not isinstance(models, list) or not models
            or not all(isinstance(m, str) and m for m in models)):
        fail("base_models", "must be a non-empty list of non-empty strings, got %r" % (models,))
    if entry["target"] not in TARGETS:
        fail("target", "must be one of %s, got %r" % (", ".join(TARGETS), entry["target"]))
    triggers = entry["triggers"]
    if not isinstance(triggers, list) or len(triggers) > MAX_TRIGGERS:
        fail("triggers", "must be a list of at most %d strings, got %r" % (MAX_TRIGGERS, triggers))
    for trigger in triggers:
        if not isinstance(trigger, str) or not TRIGGER_RE.fullmatch(trigger):
            fail("triggers", "item must match [A-Za-z0-9][A-Za-z0-9 _'-]{0,39}, got %r"
                 % (trigger,))
    if len({t.lower() for t in triggers}) != len(triggers):
        fail("triggers", "must not repeat a trigger, got %r" % (triggers,))
    if not _is_int(entry["rank"]) or entry["rank"] < 1:
        fail("rank", "must be an int >= 1, got %r" % (entry["rank"],))
    if not _is_int(entry["alpha"]) or entry["alpha"] != entry["rank"]:
        raise CatalogError("entry %s: %s" % (label, ALPHA_RANK_MESSAGE % entry["rank"]))
    default = entry["default_strength"]
    span = entry["strength_range"]
    if not _is_number(default):
        fail("default_strength", "must be a number, got %r" % (default,))
    if (not isinstance(span, list) or len(span) != 2
            or not all(_is_number(v) for v in span)):
        fail("strength_range", "must be a list of two numbers, got %r" % (span,))
    if not 0 < span[0] <= default <= span[1] <= 2:
        fail("strength_range", "and default_strength must satisfy 0 < lo <= default <= hi <= 2, "
             "got range %r and default %r" % (span, default))
    for key, low in (("description", 1), ("use_when", 1), ("avoid_when", 0)):
        text = entry[key]
        if not isinstance(text, str) or not low <= len(text) <= TEXT_MAX:
            fail(key, "must be a string of %d to %d characters, got %r" % (low, TEXT_MAX, text))
    if not isinstance(entry["added_at"], str) or not UTC_RE.fullmatch(entry["added_at"]):
        fail("added_at", "must be a UTC timestamp YYYY-MM-DDTHH:MM:SSZ, got %r"
             % (entry["added_at"],))


def validate_catalog(data):
    """LC3 top-level rules plus every entry. Raises CatalogError."""
    if not isinstance(data, dict) or set(data) != {"schema_version", "entries"}:
        raise CatalogError("top level: must be an object with exactly the keys entries, "
                           "schema_version")
    if not _is_int(data["schema_version"]) or data["schema_version"] != SCHEMA_VERSION:
        raise CatalogError("schema_version: must be %d, got %r"
                           % (SCHEMA_VERSION, data["schema_version"]))
    if not isinstance(data["entries"], list):
        raise CatalogError("entries: must be a list")
    ids, triggers = set(), {}
    for entry in data["entries"]:
        validate_entry(entry)
        if entry["id"] in ids:
            raise CatalogError("entries: id %s is listed more than once" % entry["id"])
        ids.add(entry["id"])
        for trigger in entry["triggers"]:
            owner = triggers.get(trigger.lower())
            if owner is not None:
                raise CatalogError("entries: trigger %s is used by both %s and %s"
                                   % (trigger, owner, entry["id"]))
            triggers[trigger.lower()] = entry["id"]


def load_catalog(path):
    """The catalog at path, validated; the empty catalog when the file does not exist. Raises
    CatalogError("<path>: <reason>")."""
    if not os.path.exists(path):
        return empty_catalog()
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except OSError as e:
        raise CatalogError("%s: cannot read: %s" % (path, e))
    except (ValueError, RecursionError) as e:
        raise CatalogError("%s: not valid JSON: %s" % (path, e))
    try:
        validate_catalog(data)
    except CatalogError as e:
        raise CatalogError("%s: %s" % (path, e))
    return data


def save_catalog(path, data):
    """Validate, sort the entries by id, and atomically replace path (written to
    <path>.<uuid4 hex>.tmp, then os.replace)."""
    validate_catalog(data)
    data = {"schema_version": SCHEMA_VERSION,
            "entries": sorted(data["entries"], key=lambda e: e["id"])}
    temporary = "%s.%s.tmp" % (path, uuid.uuid4().hex)
    try:
        with open(temporary, "x", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            f.write("\n")
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


class _CatalogLock(object):
    """fcntl.flock(LOCK_EX) on <catalog dir>/.lock (created mode 0600) for a with block."""

    def __init__(self, path):
        self.lock_path = os.path.join(os.path.dirname(path), ".lock")
        self.fd = None

    def __enter__(self):
        self.fd = os.open(self.lock_path, os.O_RDWR | os.O_CREAT, 0o600)
        fcntl.flock(self.fd, fcntl.LOCK_EX)
        return self

    def __exit__(self, *exc):
        try:
            fcntl.flock(self.fd, fcntl.LOCK_UN)
        finally:
            os.close(self.fd)
        return False


def catalog_lock(path):
    return _CatalogLock(path)


def file_sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_safetensors_header(path):
    """The parsed JSON header of a safetensors file (LC4). Raises CatalogError("<path>: not a
    safetensors file") on a short read, a length of 0 or above 100 MiB, or invalid JSON."""
    bad = CatalogError("%s: not a safetensors file" % path)
    try:
        with open(path, "rb") as f:
            head = f.read(8)
            if len(head) != 8:
                raise bad
            (length,) = struct.unpack("<Q", head)
            if length == 0 or length > HEADER_MAX_BYTES:
                raise bad
            raw = f.read(length)
        if len(raw) != length:
            raise bad
        header = json.loads(raw.decode("utf-8"))
    except (OSError, ValueError, RecursionError, struct.error):
        raise bad
    if not isinstance(header, dict):
        raise bad
    return header


def _whole_number(value):
    try:
        number = float(value)
        whole = int(number)
    except (TypeError, ValueError, OverflowError):
        return None
    return whole if number == whole else None


def rank_alpha(header):
    """(rank or None, alpha or None) from a safetensors header (LC4)."""
    meta = header.get("__metadata__")
    meta = meta if isinstance(meta, dict) else {}
    rank = None
    keys = sorted(k for k in header if k.endswith(LORA_A_SUFFIX))
    if keys:
        tensor = header[keys[0]]
        shape = tensor.get("shape") if isinstance(tensor, dict) else None
        if isinstance(shape, list) and shape and _is_int(shape[0]) and shape[0] >= 1:
            rank = shape[0]
    if rank is None and "ss_network_dim" in meta:
        rank = _whole_number(meta["ss_network_dim"])
    alpha = None
    for key in ("lora_alpha", "alpha", "ss_network_alpha"):
        if key in meta:
            alpha = _whole_number(meta[key])
            if alpha is not None:
                break
    return rank, alpha


def has_lora_pairs(header):
    """True when some key X.lora_A.weight has a matching X.lora_B.weight (LC4)."""
    return any(k.endswith(LORA_A_SUFFIX)
               and k[:-len(LORA_A_SUFFIX)] + LORA_B_SUFFIX in header for k in header)


def _character_lib(ws):
    return importlib.machinery.SourceFileLoader(
        "character_lib", os.path.join(ws, "character_lib.py")).load_module()


def fold_characters(ws):
    """Read-only pseudo-entries for every library character with a video LoRA (LC5), sorted by
    id. Never written to catalog.json and never offered to the story planner."""
    lib = _character_lib(ws)
    folded = []
    for name in lib.list_names():
        try:
            data = lib.load_character(name)
        except (lib.CharacterError, OSError):
            continue
        video = data["loras"]["video"]
        if not video:
            continue
        folded.append({
            "id": "char:%s" % name, "kind": "character", "path": video["path"],
            "sha256": video["sha256"], "bytes": None, "base_models": [video["base_model"]],
            "target": "video", "triggers": [data["trigger"]], "rank": video["rank"],
            "alpha": video["alpha"],
            "default_strength": data["strength"] if data["strength"] is not None else 0.8,
            "strength_range": None, "description": data["descriptor"],
            "use_when": "cast with bin/ltx-movie --character %s" % name, "avoid_when": ""})
    return sorted(folded, key=lambda e: e["id"])


def character_paths(ws):
    """{realpath: (name, "video" | "stills")} for every library character LoRA file."""
    lib = _character_lib(ws)
    paths = {}
    for name in lib.list_names():
        try:
            data = lib.load_character(name)
        except (lib.CharacterError, OSError):
            continue
        for kind in ("video", "stills"):
            if data["loras"][kind]:
                paths[os.path.realpath(data["loras"][kind]["path"])] = (name, kind)
    return paths


def character_triggers(ws):
    """{trigger.lower(): name} from character_lib.registered_triggers()."""
    return {t.lower(): name for t, name in _character_lib(ws).registered_triggers().items()}


def compatible(entry, model):
    """True when model equals a base_models item exactly, or both are absolute paths with the
    same os.path.realpath (LC6)."""
    for base in entry["base_models"]:
        if base == model:
            return True
        if (os.path.isabs(base) and os.path.isabs(model)
                and os.path.realpath(base) == os.path.realpath(model)):
            return True
    return False


def prefix_triggers(prompt, triggers):
    """prompt with the missing triggers in front as "t1, t2. " (LC18): the triggers, in order,
    de-duplicated case-insensitively, that do not already occur as whole words."""
    missing, seen = [], set()
    for trigger in triggers:
        if trigger.lower() in seen:
            continue
        seen.add(trigger.lower())
        pattern = r"(?<![\w-])" + re.escape(trigger) + r"(?![\w-])"
        if not re.search(pattern, prompt, re.IGNORECASE):
            missing.append(trigger)
    if not missing:
        return prompt
    return ", ".join(missing) + ". " + prompt


def verify_entry(entry, all_entries, char_triggers):
    """Problem strings for one catalog entry (LC10), in order: the file, its size, its sha256
    (only when the size matched), its header, rank/alpha, lora pairs, shared triggers."""
    problems = []
    path = entry["path"]
    readable = os.path.isfile(path) and os.access(path, os.R_OK)
    header = None
    if readable:
        try:
            size = os.path.getsize(path)
            if size != entry["bytes"]:
                problems.append("size is %d bytes; the catalog records %d" % (size, entry["bytes"]))
            elif file_sha256(path) != entry["sha256"]:
                problems.append("sha256 differs from the catalog; the file changed since it was "
                                "added")
        except OSError:
            readable = False
    if not readable:
        problems.append("%s is missing or unreadable" % path)
    else:
        try:
            header = read_safetensors_header(path)
        except CatalogError:
            problems.append("not a safetensors file")
    if entry["alpha"] != entry["rank"]:
        problems.append("alpha %r does not equal rank %r" % (entry["alpha"], entry["rank"]))
    if header is not None:
        rank, alpha = rank_alpha(header)
        if rank is not None and rank != entry["rank"]:
            problems.append("the header's rank %d differs from the recorded rank %d"
                            % (rank, entry["rank"]))
        if alpha is not None and alpha != entry["alpha"]:
            problems.append("the header's alpha %d differs from the recorded alpha %d"
                            % (alpha, entry["alpha"]))
        if entry["target"] == "video" and not has_lora_pairs(header):
            problems.append("has no lora_A/lora_B weight pairs; the ltx-2-mlx fuser would "
                            "ignore it")
    for trigger in entry["triggers"]:
        for other in all_entries:
            if other["id"] != entry["id"] and trigger.lower() in [t.lower() for t in other["triggers"]]:
                problems.append("trigger %s is also catalog entry %s's trigger"
                                % (trigger, other["id"]))
        if trigger.lower() in char_triggers:
            problems.append("trigger %s is also character %s's trigger"
                            % (trigger, char_triggers[trigger.lower()]))
    return problems
