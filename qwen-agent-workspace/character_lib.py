"""character_lib -- the character library's schema, validation and casting rules.

Stdlib only. This module is the single owner of the character.json schema
(schema_version 1), of name/trigger/phrase validation, and of the casting rules:
phrase matching, trigger insertion, per-panel LoRA strengths and the Phase 1 Cast
block. bin/character imports it at top level; bin/ltx-movie, bin/ltx-story-manifest
and bin/ltx-story-images load it by path, and only inside their casting branch, so
an uncast run never reads this file.

The library root is $CHARACTER_LIBRARY_DIR when set (test infrastructure only, like
LTX2_MLX_BIN), else <workspace>/generated/characters.

See docs/superpowers/specs/2026-10-05-character-library-design.md, Sections 2-3.
"""

import collections
import datetime
import json
import os
import re
import uuid

WS = os.path.dirname(os.path.realpath(__file__))
LIBRARY_ENV = "CHARACTER_LIBRARY_DIR"
SCHEMA_VERSION = 1
NAME_RE = re.compile(r"[a-z][a-z0-9-]{1,23}")
TRIGGER_RE = re.compile(r"[a-z][a-z0-9]{3,15}")
CLASS_RE = re.compile(r"[a-z]{3,12}")
PHRASE_WORD_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9''-]*")
MAX_PHRASE_WORDS = 6
ARTICLES = ("the", "a", "an")
STATUSES = ("dataset", "untrained", "trained")
SOURCE_TYPES = ("seed_image", "descriptor")
MIN_SCORE = 7
MIN_KEEP = 12
DEFAULT_CHARACTER_STRENGTH = 0.8
SINGLE_CHARACTER_STRENGTH = 1.0
TRIGGER_REGISTRY = ".triggers"
LOCK_NAME = ".lock"
SHA256_RE = re.compile(r"[0-9a-f]{64}")
UTC_RE = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z")
CAST_BLOCK_HEADER = ("Cast: these characters have fixed identities that the pipeline already "
                     "knows how to draw.")
CAST_BLOCK_RULES = (
    "Use each quoted phrase above, word for word, as that character's referring phrase "
    "everywhere in the file: it replaces the phrase you would otherwise invent for them, even "
    "when it is longer than four words. In Panel 1's Image: field, describe each of these "
    "characters who is on screen in the opening frame with exactly the description given above, "
    "word for word. Bring a cast member on screen only where the narrative calls for them. "
    "Every other character still gets a referring phrase of your own, under the rules below.")

_TOP_LEVEL_KEYS = frozenset([
    "schema_version", "name", "trigger", "class_noun", "referring_phrase", "descriptor",
    "seed", "source", "strength", "status", "created_at", "dataset", "loras",
    "stills_skip_reason"])
_DATASET_KEYS = frozenset(["reference", "kept", "total", "min_score", "face_height",
                           "contact_sheet"])
_LORA_KEYS = frozenset(["path", "sha256", "base_model", "rank", "alpha", "steps",
                        "trained_at", "sample_path", "control_path"])


class CharacterError(Exception):
    """A character library problem: bad input, a missing or invalid record, or a cast
    that cannot be resolved. The message is printed after "Error: "."""


class UnusableCharacterError(CharacterError):
    """The named character does not exist, cannot be loaded, or cannot render (not trained, or
    its video LoRA is missing or empty). Callers that can offer alternatives append
    format_available_line(usable_characters()) (spec 3.9)."""


NO_CHARACTERS_AVAILABLE = "available characters: none (create one with bin/character create)"
LIST_ROW_FORMAT = "%-16s %-16s %-9s %-5s %-6s %s"


CastMember = collections.namedtuple("CastMember", [
    "name", "phrase", "trigger", "class_noun", "descriptor",
    "video_lora", "stills_lora", "stills_skip_reason", "strength"])


def library_dir():
    return os.environ.get(LIBRARY_ENV) or os.path.join(WS, "generated", "characters")


def character_dir(name):
    return os.path.join(library_dir(), name)


def character_json_path(name):
    return os.path.join(library_dir(), name, "character.json")


def utc_now():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def _is_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _is_abs_path(value):
    return isinstance(value, str) and os.path.isabs(value)


def validate_name(name):
    if not isinstance(name, str) or not NAME_RE.fullmatch(name):
        raise CharacterError("character name must match [a-z][a-z0-9-]{1,23}, got %r" % (name,))


def validate_trigger(trigger):
    if not isinstance(trigger, str) or not TRIGGER_RE.fullmatch(trigger):
        raise CharacterError("trigger must match [a-z][a-z0-9]{3,15}, got %r" % (trigger,))


def validate_class_noun(noun):
    if not isinstance(noun, str) or not CLASS_RE.fullmatch(noun):
        raise CharacterError("class noun must match [a-z]{3,12}, got %r" % (noun,))


def normalize_phrase(phrase):
    """Whitespace-collapsed phrase, case preserved. Raises CharacterError (spec 3.2)."""
    if not isinstance(phrase, str):
        raise CharacterError("phrase must be a string, got %r" % (phrase,))
    words = phrase.split()
    if not 1 <= len(words) <= MAX_PHRASE_WORDS:
        raise CharacterError("phrase must be 1-%d words, got %r" % (MAX_PHRASE_WORDS, phrase))
    for word in words:
        if not PHRASE_WORD_RE.fullmatch(word):
            raise CharacterError("phrase word %r may contain only letters, digits, apostrophes "
                                 "and hyphens (phrase %r)" % (word, phrase))
    if len(words) == 1 and words[0].lower() in ARTICLES:
        raise CharacterError("phrase must not be a lone article: %r" % (phrase,))
    return " ".join(words)


def validate_descriptor(text):
    """The descriptor rule of spec 2.3. Raises CharacterError("descriptor: <reason>")."""
    if not isinstance(text, str):
        raise CharacterError("descriptor: must be a string, got %r" % (text,))
    if text != text.strip():
        raise CharacterError("descriptor: must not have leading or trailing whitespace")
    words = len(text.split())
    if not 8 <= words <= 60:
        raise CharacterError("descriptor: must be 8-60 words, got %d" % words)
    if not (text.startswith("a ") or text.startswith("an ")):
        raise CharacterError('descriptor: must start with "a " or "an ", got %r' % (text[:30],))
    if text.endswith("."):
        raise CharacterError('descriptor: must not end with "."')


def _validate_lora_entry(field, entry):
    if not isinstance(entry, dict) or set(entry) != _LORA_KEYS:
        raise CharacterError("%s: must be null or an object with exactly the keys %s, got %r"
                             % (field, ", ".join(sorted(_LORA_KEYS)), entry))
    if not _is_abs_path(entry["path"]):
        raise CharacterError("%s: path must be an absolute path, got %r" % (field, entry["path"]))
    if not isinstance(entry["sha256"], str) or not SHA256_RE.fullmatch(entry["sha256"]):
        raise CharacterError("%s: sha256 must be 64 lowercase hex characters, got %r"
                             % (field, entry["sha256"]))
    if not isinstance(entry["base_model"], str) or not entry["base_model"]:
        raise CharacterError("%s: base_model must be a non-empty string, got %r"
                             % (field, entry["base_model"]))
    if not _is_int(entry["rank"]) or entry["rank"] < 1:
        raise CharacterError("%s: rank must be an int >= 1, got %r" % (field, entry["rank"]))
    if not _is_int(entry["alpha"]) or entry["alpha"] != entry["rank"]:
        raise CharacterError("%s: alpha must be an int equal to rank (%r), got %r"
                             % (field, entry["rank"], entry["alpha"]))
    if not _is_int(entry["steps"]) or entry["steps"] < 1:
        raise CharacterError("%s: steps must be an int >= 1, got %r" % (field, entry["steps"]))
    if not isinstance(entry["trained_at"], str) or not UTC_RE.fullmatch(entry["trained_at"]):
        raise CharacterError("%s: trained_at must be a UTC timestamp YYYY-MM-DDTHH:MM:SSZ, got %r"
                             % (field, entry["trained_at"]))
    for key in ("sample_path", "control_path"):
        if entry[key] is not None and not _is_abs_path(entry[key]):
            raise CharacterError("%s: %s must be null or an absolute path, got %r"
                                 % (field, key, entry[key]))


def validate_character(data, name=None):
    """Strict schema_version 1 validation (spec 2.3). Raises CharacterError("<field>:
    <reason>"). File existence is not checked here."""
    if not isinstance(data, dict):
        raise CharacterError("top level: must be a JSON object, got %s" % type(data).__name__)
    missing = sorted(_TOP_LEVEL_KEYS - set(data))
    if missing:
        raise CharacterError("top level: missing keys %s" % ", ".join(missing))
    extra = sorted(set(data) - _TOP_LEVEL_KEYS)
    if extra:
        raise CharacterError("top level: unexpected keys %s" % ", ".join(extra))
    if not _is_int(data["schema_version"]) or data["schema_version"] != SCHEMA_VERSION:
        raise CharacterError("schema_version: must be %d, got %r"
                             % (SCHEMA_VERSION, data["schema_version"]))
    if not isinstance(data["name"], str) or not NAME_RE.fullmatch(data["name"]):
        raise CharacterError("name: must match [a-z][a-z0-9-]{1,23}, got %r" % (data["name"],))
    if name is not None and data["name"] != name:
        raise CharacterError("name: %r does not match its directory name %r" % (data["name"], name))
    trigger = data["trigger"]
    if not isinstance(trigger, str) or not TRIGGER_RE.fullmatch(trigger):
        raise CharacterError("trigger: must match [a-z][a-z0-9]{3,15}, got %r" % (trigger,))
    class_noun = data["class_noun"]
    if not isinstance(class_noun, str) or not CLASS_RE.fullmatch(class_noun):
        raise CharacterError("class_noun: must match [a-z]{3,12}, got %r" % (class_noun,))
    if trigger == class_noun:
        raise CharacterError("trigger: must not equal class_noun %r" % (class_noun,))
    phrase = data["referring_phrase"]
    try:
        normalized = normalize_phrase(phrase)
    except CharacterError as e:
        raise CharacterError("referring_phrase: %s" % e)
    if normalized != phrase:
        raise CharacterError("referring_phrase: must be whitespace-normalized (%r), got %r"
                             % (normalized, phrase))
    if trigger in [w.lower() for w in phrase.split()]:
        raise CharacterError("trigger: %r must not be a word of referring_phrase %r"
                             % (trigger, phrase))
    validate_descriptor(data["descriptor"])
    if not _is_int(data["seed"]) or data["seed"] < 0:
        raise CharacterError("seed: must be an int >= 0, got %r" % (data["seed"],))
    source = data["source"]
    if not (source == {"type": "descriptor"}
            or (isinstance(source, dict) and set(source) == {"type", "path"}
                and source["type"] == "seed_image" and _is_abs_path(source["path"]))):
        raise CharacterError('source: must be {"type": "seed_image", "path": <absolute path>} '
                             'or {"type": "descriptor"}, got %r' % (source,))
    strength = data["strength"]
    if strength is not None and (not _is_number(strength) or not 0 < strength <= 1.0):
        raise CharacterError("strength: must be null or a number in (0, 1], got %r" % (strength,))
    if data["status"] not in STATUSES:
        raise CharacterError("status: must be one of %s, got %r"
                             % (", ".join(STATUSES), data["status"]))
    if not isinstance(data["created_at"], str) or not UTC_RE.fullmatch(data["created_at"]):
        raise CharacterError("created_at: must be a UTC timestamp YYYY-MM-DDTHH:MM:SSZ, got %r"
                             % (data["created_at"],))
    dataset = data["dataset"]
    if dataset is not None:
        if not isinstance(dataset, dict) or set(dataset) != _DATASET_KEYS:
            raise CharacterError("dataset: must be null or an object with exactly the keys %s, "
                                 "got %r" % (", ".join(sorted(_DATASET_KEYS)), dataset))
        if dataset["reference"] not in ("char_00", "char_01"):
            raise CharacterError("dataset: reference must be char_00 or char_01, got %r"
                                 % (dataset["reference"],))
        if (not _is_int(dataset["kept"]) or not _is_int(dataset["total"])
                or not 0 <= dataset["kept"] <= dataset["total"]):
            raise CharacterError("dataset: kept and total must be ints with 0 <= kept <= total, "
                                 "got kept=%r total=%r" % (dataset["kept"], dataset["total"]))
        if not _is_int(dataset["min_score"]) or not 1 <= dataset["min_score"] <= 10:
            raise CharacterError("dataset: min_score must be an int from 1 to 10, got %r"
                                 % (dataset["min_score"],))
        face = dataset["face_height"]
        if face is not None and (not _is_number(face) or not 0 <= face <= 1):
            raise CharacterError("dataset: face_height must be null or a number in [0, 1], got %r"
                                 % (face,))
        if not _is_abs_path(dataset["contact_sheet"]):
            raise CharacterError("dataset: contact_sheet must be an absolute path, got %r"
                                 % (dataset["contact_sheet"],))
    loras = data["loras"]
    if not isinstance(loras, dict) or set(loras) != {"video", "stills"}:
        raise CharacterError("loras: must be an object with exactly the keys stills, video, got %r"
                             % (loras,))
    for kind in ("video", "stills"):
        if loras[kind] is not None:
            _validate_lora_entry("loras.%s" % kind, loras[kind])
    reason = data["stills_skip_reason"]
    if reason is not None and (not isinstance(reason, str) or not reason):
        raise CharacterError("stills_skip_reason: must be null or a non-empty string, got %r"
                             % (reason,))
    if (data["status"] == "trained") != (loras["video"] is not None):
        raise CharacterError('status: %r is inconsistent with loras.video (%s); status is '
                             '"trained" exactly when a video LoRA is recorded'
                             % (data["status"], "null" if loras["video"] is None else "set"))
    if data["status"] in ("untrained", "trained") and (dataset is None
                                                        or dataset["kept"] < MIN_KEEP):
        raise CharacterError("status: %r requires a dataset with at least %d kept stills"
                             % (data["status"], MIN_KEEP))


def load_character(name):
    validate_name(name)
    path = character_json_path(name)
    if not os.path.isfile(path):
        raise CharacterError("unknown character: %s (no %s)" % (name, path))
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        validate_character(data, name=name)
    except (ValueError, CharacterError) as e:
        raise CharacterError("invalid character.json for %s: %s" % (name, e))
    return data


def write_character(data):
    """Validate, then atomically replace <lib>/<name>/character.json. The directory must
    already exist."""
    validate_character(data)
    path = character_json_path(data["name"])
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
                  if NAME_RE.fullmatch(n) and os.path.isfile(character_json_path(n)))


def registered_triggers():
    """{trigger: name}: the .triggers registry, then every readable character.json trigger.
    Registry entries win on conflict; triggers are never reused (spec 2.4)."""
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
            with open(character_json_path(name), encoding="utf-8") as f:
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


def auto_trigger(name, class_noun, taken, avoid=()):
    """Rare-token trigger: up to 5 letters of the name + up to 3 consonants of the class noun,
    padded with 'x' to 4 characters, then suffixed 2, 3, ... until unused (spec 2.4)."""
    stem = re.sub(r"[^a-z]", "", name)[:5]
    suffix = "".join(c for c in class_noun if c not in "aeiou")[:3] or class_noun[:3]
    base = stem + suffix
    if len(base) < 4:
        base = (base + "xxxx")[:4]
    blocked = set(taken) | {w.lower() for w in avoid} | {class_noun}
    candidate, k = base, 2
    while candidate in blocked:
        candidate = "%s%d" % (base, k)
        k += 1
    return candidate


def parse_cast_arg(value):
    """--cast PHRASE=NAME -> (normalized phrase, name), split on the LAST "=" (spec 3.4)."""
    if "=" not in value:
        raise CharacterError("--cast must be PHRASE=NAME, got %r" % (value,))
    phrase, name = value.rsplit("=", 1)
    try:
        validate_name(name.strip())
    except CharacterError as e:
        raise UnusableCharacterError(str(e))
    return normalize_phrase(phrase), name.strip()


def _readable_nonempty(p):
    return os.path.isfile(p) and os.access(p, os.R_OK) and os.path.getsize(p) > 0


def resolve_cast(entries):
    members = []
    for phrase, name in entries:
        try:
            data = load_character(name)
        except UnusableCharacterError:
            raise
        except CharacterError as e:
            raise UnusableCharacterError(str(e))
        if data["status"] != "trained":
            raise UnusableCharacterError("character %s is not trained (status %s); run "
                                         "bin/character train %s" % (name, data["status"], name))
        video = data["loras"]["video"]["path"]
        if not _readable_nonempty(video):
            raise UnusableCharacterError("character %s's video LoRA is missing or empty: %s"
                                         % (name, video))
        stills = data["loras"]["stills"]["path"] if data["loras"]["stills"] else None
        if stills is not None and not _readable_nonempty(stills):
            raise CharacterError("character %s's stills LoRA is missing or empty: %s" % (name, stills))
        phrase = normalize_phrase(phrase) if phrase is not None else data["referring_phrase"]
        if data["trigger"] in [w.lower() for w in phrase.split()]:
            raise CharacterError("character %s's trigger %s is a word of its cast phrase %r"
                                 % (name, data["trigger"], phrase))
        members.append(CastMember(name, phrase, data["trigger"], data["class_noun"],
                                  data["descriptor"], video, stills,
                                  data["stills_skip_reason"], data["strength"]))
    by_name, by_phrase, by_trigger = {}, {}, {}
    for m in members:
        if m.name in by_name:
            raise CharacterError("character %s is cast more than once" % m.name)
        if m.phrase.lower() in by_phrase:
            raise CharacterError("cast phrase %r is used for both %s and %s"
                                 % (m.phrase, by_phrase[m.phrase.lower()], m.name))
        if m.trigger in by_trigger:
            raise CharacterError("characters %s and %s share the trigger %s"
                                 % (by_trigger[m.trigger], m.name, m.trigger))
        by_name[m.name] = m
        by_phrase[m.phrase.lower()] = m.name
        by_trigger[m.trigger] = m.name
    return members


def _phrase_regex(phrase, trigger=None):
    words = phrase.split()
    esc = [re.escape(w) for w in words]
    trig = re.escape(trigger) if trigger else None
    if len(words) > 1 and words[0].lower() in ARTICLES:
        body = (esc[0] + (r"(?P<trig>\s+" + trig + r")?" if trig else "")
                + r"\s+" + r"\s+".join(esc[1:]))
    else:
        body = (r"(?P<trig>" + trig + r"\s+)?" if trig else "") + r"\s+".join(esc)
    return re.compile(r"(?<![\w-])" + body + r"(?![\w-])", re.IGNORECASE)


def phrase_occurs(text, phrase):
    return _phrase_regex(normalize_phrase(phrase)).search(text) is not None


def cast_text(text, members):
    """(text with each cast phrase's trigger inserted, sorted names of the members found).
    Longest phrase first; a match overlapping an already-claimed span is ignored; an
    occurrence that already carries the trigger is counted but not re-inserted (spec 3.6)."""
    found = []
    for member in sorted(members, key=lambda m: (-len(m.phrase), m.phrase.lower(), m.name)):
        for match in _phrase_regex(member.phrase, member.trigger).finditer(text):
            start, end = match.span()
            if any(start < e and s < end for s, e, _, _ in found):
                continue
            found.append((start, end, member, match.group("trig") is not None))
    out = text
    for start, _end, member, already in sorted(found, key=lambda f: f[0], reverse=True):
        if already:
            continue
        words = member.phrase.split()
        if len(words) > 1 and words[0].lower() in ARTICLES:
            cut = start + len(words[0])
            out = out[:cut] + " " + member.trigger + out[cut:]
        else:
            out = out[:start] + member.trigger + " " + out[start:]
    return out, sorted({member.name for _, _, member, _ in found})


def panel_strengths(names, members, character_strength):
    """{name: strength} for one panel: 1.0 when exactly one cast character is named; else each
    character's own character.json strength if set, otherwise character_strength (spec 6)."""
    by_name = {m.name: m for m in members}
    if len(names) == 1:
        return {names[0]: SINGLE_CHARACTER_STRENGTH}
    return {n: (by_name[n].strength if by_name[n].strength is not None else character_strength)
            for n in names}


def build_cast_block(members):
    lines = [CAST_BLOCK_HEADER]
    for m in members:
        lines.append('- "%s": %s.' % (m.phrase, m.descriptor))
    lines.append(CAST_BLOCK_RULES)
    return "\n".join(lines)


def usable_characters():
    """[(name, referring_phrase)] sorted by name, for every library character that
    resolve_cast would accept on its own (loadable, trained, video LoRA readable and non-empty,
    stills LoRA readable and non-empty when recorded)."""
    usable = []
    for name in list_names():
        try:
            member = resolve_cast([(None, name)])[0]
        except CharacterError:
            continue
        usable.append((member.name, member.phrase))
    return usable


def format_available_line(characters):
    """One line naming the usable characters; characters is usable_characters()'s list."""
    if not characters:
        return NO_CHARACTERS_AVAILABLE
    return "available characters: " + ", ".join("%s (%s)" % (n, p) for n, p in characters)


def character_table_lines():
    """The library table printed by bin/character list and bin/ltx-movie --list-characters."""
    names = list_names()
    if not names:
        return ["no characters in %s" % library_dir()]
    lines = [LIST_ROW_FORMAT % ("NAME", "TRIGGER", "STATUS", "VIDEO", "STILLS", "PHRASE")]
    for name in names:
        try:
            data = load_character(name)
        except CharacterError as e:
            lines.append("%-16s (invalid: %s)" % (name, e))
            continue
        lines.append(LIST_ROW_FORMAT % (
            name, data["trigger"], data["status"],
            "yes" if data["loras"]["video"] else "no",
            "yes" if data["loras"]["stills"] else "no",
            data["referring_phrase"]))
    return lines
