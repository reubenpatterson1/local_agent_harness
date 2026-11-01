"""movie_ui_seedfolder -- seed-folder Compose and Characters: the pure core of one job per seed
image (docs/superpowers/specs/2026-11-01-seed-folder-compose-design.md, deliverable G1).

The constants (spec 1.1, 2.4), the shared candidate loop first_free and the story-ID rules (2.1),
the taken sets (2.2, 2.4), the character-name rules (2.4), the request checks of
POST /api/jobs/seed-folder (3.1) and POST /api/characters/seed-folder (3.5), the status and
reason of a row (3.2), the run ID (3.3) and the seed-folder tag of a job (3.4).

Standard library plus movie_ui_lib only (SD1). Valid on Python 3.9 and 3.13. This module never
writes and never starts a process. Every function is pure except new_run_id, which reads the
clock and draws random digits.
"""

import re
import secrets
import time
import unicodedata

import movie_ui_lib as lib

SEEDS_MAX = 100
PREFIX_MAX = 40
ID_MAX = 80                                   # STORY_ID_RE, movie_ui_lib.py:37
DRY_RUN_WORKERS = 4
RUN_ID_RE = re.compile(r"^sf-[0-9]{8}-[0-9]{6}-[0-9a-f]{4}$")
_OUTSIDE = re.compile(r"[^A-Za-z0-9._-]+")
CHAR_MAX = 24                                 # CHARACTER_NAME_RE, movie_ui_lib.py:38
CHAR_PREFIX_MAX = 12


# ---------------------------------------------------------------------------
# Story IDs (spec 2.1, 2.2)
# ---------------------------------------------------------------------------

def seed_stem(name):
    """Rules 1-4: the cleaned stem of a seed's file name; never empty."""
    dot = name.rfind(".")
    stem = name[:dot] if dot > 0 else name                                    # 1
    stem = unicodedata.normalize("NFKD", stem).encode("ascii", "ignore").decode("ascii")   # 2
    stem = _OUTSIDE.sub("-", stem)                                            # 3
    stem = re.sub(r"\.{2,}", ".", stem)
    stem = re.sub(r"-{2,}", "-", stem)
    stem = re.sub(r"^[^A-Za-z0-9]+", "", stem).rstrip("-._")                  # 4
    return stem or "seed"


def valid_prefix(prefix):
    """SD6: the prefix is "" or a valid story ID of at most PREFIX_MAX characters. It is used
    exactly as typed."""
    return prefix == "" or (lib.valid_story_id(prefix) and len(prefix) <= PREFIX_MAX)


def first_free(head, stem, taken, limit, trim):
    """The first free head + cut stem [+ "-k"] of at most limit characters (SD7, SD38)."""
    def candidate(suffix):
        room = limit - len(head) - len(suffix)
        return head + stem[:room].rstrip(trim) + suffix

    first = candidate("")
    if first.lower() not in taken:
        return first
    for k in range(2, 12 * (len(taken) + 1) + 10):
        name = candidate("-%d" % k)
        if name.lower() not in taken:
            return name
    raise AssertionError("no free name")      # unreachable (bound below)


def story_id_for(stem, prefix, taken):
    """Rules 5-7: the first free story ID for one stem (SD7)."""
    return first_free(prefix + "-" if prefix else "", stem, taken, ID_MAX, "-._")


def assign_story_ids(names, prefix, taken):
    """Rules 1-7 for every name in order; taken is not modified (SD8)."""
    seen = set(taken)
    out = []
    for name in names:
        story_id = story_id_for(seed_stem(name), prefix, seen)
        seen.add(story_id.lower())
        out.append(story_id)
    return out


def taken_names(listing, busy_story_ids):
    """SD9: the lower-case names a seed's story ID must avoid: the listing of
    generated/stories, the story IDs of the busy jobs (strings only) and movie-ui-smoke."""
    return ({n.lower() for n in listing} | {s.lower() for s in busy_story_ids if isinstance(s, str)}
            | {lib.SMOKE_STORY_ID})


# ---------------------------------------------------------------------------
# Character names (spec 2.4)
# ---------------------------------------------------------------------------

def character_stem(name):
    """Character name rules 1-6 (SD36): lower case, at least 2 characters."""
    dot = name.rfind(".")
    stem = name[:dot] if dot > 0 else name                                    # 1 (as SD5)
    stem = unicodedata.normalize("NFKD", stem).encode("ascii", "ignore").decode("ascii").lower()   # 2, 3
    stem = re.sub(r"[^a-z0-9]+", "-", stem)                                   # 4
    stem = re.sub(r"^[^a-z]+", "", stem).rstrip("-")                          # 5
    if len(stem) < 2:                                                         # 6
        stem = stem + "-char" if stem else "char"
    return stem


def valid_character_prefix(prefix):
    """SD37: the prefix is "" or a character name of at most CHAR_PREFIX_MAX characters. It is
    used exactly as typed."""
    return prefix == "" or (isinstance(prefix, str) and lib.CHARACTER_NAME_RE.fullmatch(prefix) is not None
                            and len(prefix) <= CHAR_PREFIX_MAX)


def character_name_for(stem, prefix, taken):
    """SD38: the first free character name for one stem, through SD7's first_free."""
    return first_free(prefix + "-" if prefix else "", stem, taken, CHAR_MAX, "-")


def assign_character_names(names, prefix, taken):
    """SD38: SD8's loop with the character rules; taken is not modified."""
    seen = set(taken)
    out = []
    for name in names:
        character = character_name_for(character_stem(name), prefix, seen)
        seen.add(character.lower())
        out.append(character)
    return out


def character_taken_names(listing, busy_names):
    """SD39: the lower-cased library listing and the busy jobs' character names (strings only)."""
    return {n.lower() for n in listing} | {s.lower() for s in busy_names if isinstance(s, str)}


# ---------------------------------------------------------------------------
# The requests (spec 3.1, 3.5)
# ---------------------------------------------------------------------------

def _seeds_and_preview(body):
    """SD13 rows 4-7, shared by both endpoints (SD43): (seeds, preview, None) or (None, None,
    message). Rule 5 is checked for every item before rule 6 (plan ruling PR2). seeds is
    [{"name", "upload_id"}]; upload_id is the item's value, or None when the item has none."""
    seeds = body.get("seeds")
    if not isinstance(seeds, list) or not 1 <= len(seeds) <= SEEDS_MAX:
        return None, None, "seeds must be a list of 1 to 100 items"
    for k, item in enumerate(seeds, 1):
        if not isinstance(item, dict):
            return None, None, "seed %d must be an object" % k
    for k, item in enumerate(seeds, 1):
        name = item.get("name")
        if not isinstance(name, str) or "/" in name:
            return None, None, "seed %d: name must be a string without '/'" % k
    preview = body.get("preview")
    if not isinstance(preview, bool):
        return None, None, "preview must be true or false"
    return [{"name": item["name"], "upload_id": item.get("upload_id")} for item in seeds], preview, None


def validate_request(body):
    """SD12, SD13 rows 2-7: (clean, None), or (None, the message of the first failing rule).
    clean is {"prefix", "action", "seeds", "preview", "check_seams"}."""
    action = body.get("action", "story")
    if action not in ("movie", "story"):
        return None, "action must be movie or story"
    prefix = body.get("story_id")
    if prefix is None:
        prefix = ""
    if not isinstance(prefix, str) or not valid_prefix(prefix):
        return None, "story ID prefix must be a valid story ID of at most 40 characters"
    seeds, preview, error = _seeds_and_preview(body)
    if error is not None:
        return None, error
    return {"prefix": prefix, "action": action, "seeds": seeds, "preview": preview,
            "check_seams": body.get("check_seams") is True}, None


def validate_character_request(body):
    """SD43 rows 4-8: (clean, None), or (None, the message of the first failing rule). clean is
    {"prefix", "seeds", "preview"}; the prefix is the body's "name"."""
    prefix = body.get("name")
    if prefix is None:
        prefix = ""
    if not valid_character_prefix(prefix):
        return None, "character name prefix must match [a-z][a-z0-9-]{1,23} and be at most 12 characters"
    seeds, preview, error = _seeds_and_preview(body)
    if error is not None:
        return None, error
    return {"prefix": prefix, "seeds": seeds, "preview": preview}, None


# ---------------------------------------------------------------------------
# Rows, the run ID and the tag (spec 3.2-3.4)
# ---------------------------------------------------------------------------

def row_reason(v1, v6):
    """SD18: (status, reason) of a row from its V1 and V6 records, in the table's order."""
    if v1["status"] == "fail":
        return "refused", v1["detail"].replace("\n", "; ")
    if v6["status"] == "skip" and v6["detail"] == "skipped: shared checks failed":
        return "skipped", "skipped: shared checks failed"
    if v6["status"] == "fail":
        if v6["detail"] == "bin/ltx-movie --dry-run timed out after %d s" % lib.DRY_RUN_TIMEOUT:
            return "refused", "dry run timed out after %d s" % lib.DRY_RUN_TIMEOUT
        line = lib.last_line(v6["detail"])
        return "refused", ("dry run failed: " + line) if line else "dry run failed"
    return "ok", None


def new_run_id():
    """SD22: "sf-" + UTC %Y%m%d-%H%M%S + "-" + 4 hex digits (matches RUN_ID_RE). A display tag
    only, so there is no uniqueness loop."""
    return "sf-" + time.strftime("%Y%m%d-%H%M%S", time.gmtime()) + "-" + secrets.token_hex(2)


def seed_tag(fields):
    """SD23: {"run", "name"} of a job's fields["seed_folder"] when both are strings, else None."""
    value = fields.get("seed_folder") if isinstance(fields, dict) else None
    if isinstance(value, dict) and isinstance(value.get("run"), str) and isinstance(value.get("name"), str):
        return {"run": value["run"], "name": value["name"]}
    return None
