"""movie_ui_batch -- batch forks: the pure core of a bulk re-run of stories to compare settings
(docs/superpowers/specs/2026-10-30-batch-forks-design.md, deliverable G1).

The constants (spec 1.1), the request check of the preview and submit bodies (3.2, 6), the field
classification table (2.1), merge (2.2), the prompt edits (2.3), the cell plan with its
classification and refusals (2.4, 3.6), fork IDs (2.5), the copy plan (2.6), the submit order
(4.2), the totals (3.3), the eligibility texts (3.4) and the batch-record field fallback check
(3.5).

Standard library plus movie_ui_lib only (BF1). Valid on Python 3.9 and 3.13. This module never
writes. Every function is pure except copy_plan, which lists a story directory read-only, and
plan_cells, which reads only through the validate and exists functions its caller passes in.
"""

import json
import os
import re
import stat

import movie_ui_lib as lib

BATCH_SCHEMA = "movie-ui.batch.v1"
FORK_SCHEMA = "movie-ui.fork.v1"
MAX_VARIANTS = 6
MAX_CELLS = 24
MAX_REPLACES = 10                      # [spec choice] bounds the request
LABEL_MAX = 24                         # [spec choice] fits a grid column header
PROMPT_MAX = lib.NARRATIVE_MAX         # 20000, the Compose narrative limit
STORY_ID_MAX = 80                      # STORY_ID_RE, movie_ui_lib.py:37
MIN_FREE_BYTES = 20 * 1024 ** 3        # 20 GiB left after the copy
LEVELS = ("render", "stills", "replan")            # rank order
LEVEL_LABELS = {"render": "Render", "stills": "New stills", "replan": "Re-plan"}
FIXED_KEYS = ("ws", "action", "story_id", "overwrite_movie", "redo")
GROUPS = (("panels", "length"), ("width", "height", "seed_upload"))
FORK_SUFFIX_RE = re.compile(r"-b([0-9]+)-v[0-9]+$")

# Spec 2.1 (BF4, BK1): the level of every editable DEFAULT_FIELDS key.
FIELD_LEVELS = {
    "model": "render", "gemma": "render", "video_loras": "render", "action_loras": "render",
    "frames": "render", "fps": "render", "no_low_ram": "render", "panel_timeout": "render",
    "width": "stills", "height": "stills", "stills_loras": "stills", "location_strength": "stills",
    "narrative": "replan", "goal": "replan", "panels": "replan", "length": "replan",
    "seed_upload": "replan", "mode": "replan", "characters": "replan", "locations": "replan",
    "narration": "replan", "story_model": "replan", "story_legacy": "replan", "judge": "replan",
    "auto_lora": "replan",
}

# Spec 2.6 (BF16): the allowlist of the files a fork copies, by level.
COPY_FILES = {
    "render": ("story.md", "plan.json", "story_checks.json", "story_prompt.txt", "catalog_loras.json",
               "manifest.json"),
    "stills": ("story.md", "plan.json", "story_checks.json", "story_prompt.txt"),
    "replan": (),
}
STILL_RE = re.compile(r"^panel_\d{2}\.png$")
CLIP_RE = re.compile(r"^panel_\d{2}\.mp4$")

# Spec 6: the rows of the 400 table, in table order (errors are sorted by row, stably).
_ROWS = ("stories", "variants", "cells", "label", "key", "narrative", "both", "pair", "seed", "append",
         "replace", "find", "with", "per_story", "per_story_text")

# Spec 3.6 step 2: a cell's refusal when its original has no saved Compose settings.
NO_FIELDS = {
    "none": "story %s has no saved Compose settings (it was started from the command line)",
    "gone": "story %s has no saved Compose settings (its job and its batch %s were deleted)",
    "mismatch": ("story %s has no saved Compose settings (its job was deleted and batch %s has no "
                 "matching record of it)"),
}
IDENTICAL = "same settings and prompt as the original; nothing to compare"

_ABSENT_A, _ABSENT_B = object(), object()   # two missing keys never compare equal (BF41c)


# ---------------------------------------------------------------------------
# The request (spec 3.2, 6)
# ---------------------------------------------------------------------------

def validate_request(body):
    """(clean, errors) for a preview or submit body (spec 3.2, 6). clean is {"stories",
    "variants"}, each variant as {"label", "settings", "prompt": {"append", "replace",
    "per_story"}}; errors lists the 400 lines in the table order of spec 6, variant K and pair J
    ascending within a row. The caller resolves "ws" with resolve_ws before this."""
    found = []
    stories = body.get("stories")
    stories_ok = (isinstance(stories, list) and 1 <= len(stories) <= MAX_CELLS
                  and all(lib.valid_story_id(s) for s in stories) and len(set(stories)) == len(stories))
    if not stories_ok:
        found.append(("stories", "stories must be a list of 1 to 24 distinct story IDs"))
    variants = body.get("variants")
    variants_ok = (isinstance(variants, list) and 1 <= len(variants) <= MAX_VARIANTS
                   and all(isinstance(v, dict) for v in variants))
    if not variants_ok:
        found.append(("variants", "variants must be a list of 1 to 6 variants"))
    if stories_ok and variants_ok and len(stories) * len(variants) > MAX_CELLS:
        found.append(("cells", "a batch has at most 24 cells; this one has %d (%d stories x %d variants)"
                      % (len(stories) * len(variants), len(stories), len(variants))))
    names = set(stories) if stories_ok else set()
    clean_variants = [_check_variant(k, v, names, found)
                      for k, v in enumerate(variants if variants_ok else [], 1)]
    errors = [text for _row, text in sorted(found, key=lambda item: _ROWS.index(item[0]))]
    return {"stories": list(stories) if stories_ok else [], "variants": clean_variants}, errors


def _check_variant(k, variant, names, found):
    """Append variant K's 400 lines to found as (row, text); return its clean form."""
    head = "variant %d: " % k
    label = variant.get("label")
    if not (isinstance(label, str) and 1 <= len(label) <= LABEL_MAX and "\n" not in label
            and "\r" not in label):
        found.append(("label", head + "label must be 1 to 24 characters with no line breaks"))
    settings = variant.get("settings", {})
    if not isinstance(settings, dict):
        found.append(("key", head + "settings must be an object"))
        settings = {}
    for key in settings:
        if key == "narrative":
            found.append(("narrative", head + "change the prompt with append, replace or per-story text"))
        elif key not in FIELD_LEVELS:
            found.append(("key", head + "setting %s cannot be changed in a variant" % key))
    if "panels" in settings and "length" in settings:
        found.append(("both", head + "give panels or length, not both"))
    if ("width" in settings) != ("height" in settings):
        found.append(("pair", head + "give width and height together"))
    if settings.get("seed_upload") is not None and ("width" in settings or "height" in settings):
        found.append(("seed", head + "give a seed image or a resolution, not both"))
    prompt = variant.get("prompt", {})
    if not isinstance(prompt, dict):
        found.append(("append", head + "prompt must be an object"))
        prompt = {}
    append = prompt.get("append", "")
    if not (isinstance(append, str) and len(append) <= PROMPT_MAX):
        found.append(("append", head + "append must be a string of at most 20000 characters"))
        append = ""
    replace = prompt.get("replace", [])
    pairs = []
    if not (isinstance(replace, list) and len(replace) <= MAX_REPLACES
            and all(isinstance(p, dict) and set(p) == {"find", "with"} for p in replace)):
        found.append(("replace", head + "replace must be a list of at most 10 {find, with} pairs"))
    else:
        for j, pair in enumerate(replace, 1):
            if not (isinstance(pair["find"], str) and 1 <= len(pair["find"]) <= PROMPT_MAX):
                found.append(("find", head + "replace pair %d: find must be 1 to 20000 characters" % j))
            if not (isinstance(pair["with"], str) and len(pair["with"]) <= PROMPT_MAX):
                found.append(("with", head + "replace pair %d: with must be a string of at most 20000 "
                                             "characters" % j))
            pairs.append({"find": pair["find"], "with": pair["with"]})
    per_story = prompt.get("per_story", {})
    texts = {}
    if not (isinstance(per_story, dict)
            and all(sid in names and isinstance(text, str) for sid, text in per_story.items())):
        found.append(("per_story", head + "per_story must map story IDs of this batch to text"))
    else:
        for sid, text in per_story.items():
            if not 1 <= len(text) <= PROMPT_MAX:
                found.append(("per_story_text", head + "per-story prompt for %s must be 1 to 20000 "
                                                       "characters" % sid))
            texts[sid] = text
    return {"label": label, "settings": json.loads(json.dumps(settings)),
            "prompt": {"append": append, "replace": pairs, "per_story": texts}}


# ---------------------------------------------------------------------------
# Merge, prompt edits and classification (spec 2.2-2.4)
# ---------------------------------------------------------------------------

def original_fields(last_fields, story_id, ws_real):
    """Merge step 1 (BF5): the original's fields with the fixed keys of a fork's run."""
    orig = lib.compose_fields(last_fields)
    orig.update(ws=ws_real, action="movie", story_id=story_id, overwrite_movie=False, redo=[])
    return orig


def edit_prompt(narrative, prompt, story_id):
    """(text, warnings): BF6's per-story text, then the find/replace pairs in order, then the
    appended paragraph, then the length warning. Raises TypeError when the text is not a string
    (a saved narrative of null), which BF12 turns into a refusal."""
    per_story = prompt.get("per_story") or {}
    text = per_story[story_id] if story_id in per_story else narrative
    if not isinstance(text, str):
        raise TypeError("the saved narrative is not a string")
    warnings = []
    for pair in prompt.get("replace") or []:
        if pair["find"] in text:
            text = text.replace(pair["find"], pair["with"])
        else:
            warnings.append('find text not in this prompt: "%s"' % pair["find"])
    append = (prompt.get("append") or "").strip()
    if append:
        text = text.rstrip() + "\n\n" + append
    if len(text) > PROMPT_MAX:
        warnings.append("edited prompt is %d characters; the limit is %d" % (len(text), PROMPT_MAX))
    return text, warnings


def merge(last_fields, variant, story_id, fork_id, ws_real):
    """(orig, fork, warnings) of spec 2.2 (BF5)."""
    orig = original_fields(last_fields, story_id, ws_real)
    fork = json.loads(json.dumps(orig))
    fork["story_id"] = fork_id or story_id
    for key, value in variant["settings"].items():
        fork[key] = json.loads(json.dumps(value))
        if key == "panels":
            fork["length"] = None
        elif key == "length":
            fork["panels"] = None
        elif key in ("width", "height"):
            fork["seed_upload"] = None
        elif key == "seed_upload" and value is not None:
            fork["width"] = fork["height"] = None
    fork["narrative"], warnings = edit_prompt(orig["narrative"], variant["prompt"], story_id)
    return orig, fork, warnings


def argv_of(fields, story_id, ws_real, state):
    """A(f) of spec 2.4: the bin/ltx-movie argv of fields with the original's story ID."""
    return lib.build_argv(dict(fields, story_id=story_id), ws_real, state)


def _group(key):
    for group in GROUPS:
        if key in group:
            return group
    return (key,)


def classify(orig, fork, story_id, ws_real, state, has_story):
    """(level, diff, warnings) of a fork whose argv differs from its original's (BF8-BF10)."""
    base = argv_of(orig, story_id, ws_real, state)
    diff = []
    for key in lib.DEFAULT_FIELDS:
        if key not in FIELD_LEVELS or fork[key] == orig[key]:
            continue
        probe = dict(orig)
        for k in _group(key):
            probe[k] = fork[k]
        if argv_of(probe, story_id, ws_real, state) != base:
            diff.append({"key": key, "from": orig[key], "to": fork[key]})
    if fork["length"] is not None and "panels" not in [d["key"] for d in diff]:
        before, after = lib.resolved_panels(orig), lib.resolved_panels(fork)
        if after != before:
            diff.append({"key": "panels", "from": before, "to": after, "note": "resolved from length"})
    level = LEVELS[max(LEVELS.index(FIELD_LEVELS[d["key"]]) for d in diff)]
    warnings = []
    if not has_story:
        level = "replan"
        warnings.append("the original has no story.md; this fork writes a new story")
    elif level in ("render", "stills"):
        clip, was = fork["frames"] / float(fork["fps"]), orig["frames"] / float(orig["fps"])
        if clip < was:
            warnings.append("shorter clips (%.2f s, was %.2f s): the copied story.md is re-checked and "
                            "can fail its spoken-line timing" % (clip, was))
    return level, diff, warnings


# ---------------------------------------------------------------------------
# Fork IDs (spec 2.5)
# ---------------------------------------------------------------------------

def fork_id(story_id, n, m):
    """BF13: <story_id>-b<n>-v<m>, the stem cut so the whole is at most 80 characters and never
    ends in "-", "." or "_"."""
    suffix = "-b%d-v%d" % (n, m)
    stem = story_id
    if len(story_id) + len(suffix) > STORY_ID_MAX:
        stem = story_id[:STORY_ID_MAX - len(suffix)].rstrip("-._")
    return stem + suffix


def next_number(batch_records, story_names, ws_real):
    """BF14: 1 plus the largest number of a batch record of ws_real and of a fork suffix among the
    workspace's story directory names (0 when there are none)."""
    top = 0
    for rec in batch_records:
        if not isinstance(rec, dict) or rec.get("workspace") != ws_real:
            continue
        number = rec.get("number")
        if isinstance(number, int) and not isinstance(number, bool):
            top = max(top, number)
    for name in story_names:
        found = FORK_SUFFIX_RE.search(name)
        if found:
            top = max(top, int(found.group(1)))
    return top + 1


# ---------------------------------------------------------------------------
# The cell plan (spec 3.6)
# ---------------------------------------------------------------------------

def no_fields_reason(story_id, code, batch_id):
    """The spec 3.6 step 2 refusal for BF41 code "none", "gone" or "mismatch"."""
    if code == "none":
        return NO_FIELDS["none"] % story_id
    return NO_FIELDS[code] % (story_id, batch_id)


def eligibility_reason(busy_job, code, batch_id):
    """Spec 3.4's reason of one Stories row (busy wins), or None when the story is eligible."""
    if busy_job is not None:
        return "Job %s is queued or running for this story" % busy_job
    if code == "none":
        return "Started from the command line: no saved Compose settings to fork"
    if code == "gone":
        return "Its job and its batch %s were deleted: no saved Compose settings to fork" % batch_id
    if code == "mismatch":
        return ("Its job was deleted and batch %s has no matching record of this fork: no saved "
                "Compose settings to fork" % batch_id)
    return None


def _unusable(story_id, error):
    return "the saved settings of story %s cannot be used: %s: %s" % (story_id, type(error).__name__, error)


def _early_refusal(story_id, info, fid, earlier, exists):
    """Steps 1-4 of spec 3.6, or None."""
    if not info["dir"]:
        return "story %s no longer exists in this workspace" % story_id
    if info["fields"] is None:
        return no_fields_reason(story_id, info["code"], info["batch"])
    if info["busy_job"] is not None:
        return "story %s has a job queued or running (job %s)" % (story_id, info["busy_job"])
    if not lib.valid_story_id(fid):
        return "the fork ID would not be a valid story ID: %s" % fid
    for other in earlier:
        if other["status"] == "ok" and other["fork_id"].lower() == fid.lower():
            return "fork ID %s is also the fork ID of story %s in this batch" % (fid, other["story_id"])
    if exists(fid):
        return "fork ID %s already exists; it is never overwritten" % fid
    return None


def _build(cell, info, variant, labels, ws_real, state, validate, earlier, argvs):
    """Steps 5-7 of spec 3.6 for a cell that passed steps 1-4."""
    story_id = cell["story_id"]
    try:
        orig, fork, warnings = merge(info["fields"], variant, story_id, cell["fork_id"], ws_real)
    except Exception as e:  # BF12, widened by controller ruling: any odd saved field refuses the cell
        cell["reason"] = _unusable(story_id, e)
        return
    cell["warnings"] = warnings
    errors = validate(fork)
    if errors:
        cell["status"], cell["reason"] = "invalid", "\n".join(errors)
        return
    try:
        argv = argv_of(fork, story_id, ws_real, state)
        if argv == argv_of(orig, story_id, ws_real, state):
            cell["reason"] = IDENTICAL
            return
        for other in earlier:
            if (other["story_id"] == story_id and other["status"] == "ok"
                    and argvs[(story_id, other["variant"])] == argv):
                cell["reason"] = "same settings and prompt as variant %d (%s) for this story" % (
                    other["variant"], labels[other["variant"] - 1])
                return
        level, diff, notes = classify(orig, fork, story_id, ws_real, state, info["has_story"])
    except Exception as e:  # BF12, widened by controller ruling: any odd saved field refuses the cell
        cell["reason"] = _unusable(story_id, e)
        return
    argvs[(story_id, cell["variant"])] = argv
    cell.update(status="ok", level=level, diff=diff, warnings=warnings + notes, fields=fork)


def plan_cells(stories, variants, number, ws_real, state, originals, validate, exists):
    """Spec 3.6 for every cell in grid order (story-major, then variant): a list of {"story_id",
    "variant", "fork_id", "status", "reason", "level", "diff", "warnings", "fields"} with status
    "ok", "refused" or "invalid" (V1 failed) and fields the fork's fields when "ok".

    originals maps each story ID to {"dir", "has_story", "busy_job", "fields", "code", "batch"}
    (fields None when the story has no saved Compose settings, with code "none", "gone" or
    "mismatch"); validate(fields) is V1 and exists(fork_id) says whether the fork's directory
    exists. BF11 and BF15 compare a cell only with earlier cells whose status is "ok"."""
    labels = [v["label"] for v in variants]
    cells, argvs = [], {}
    for story_id in stories:
        info = originals[story_id]
        for m, variant in enumerate(variants, 1):
            cell = {"story_id": story_id, "variant": m, "fork_id": fork_id(story_id, number, m),
                    "status": "refused", "reason": None, "level": None, "diff": [], "warnings": [],
                    "fields": None}
            earlier = list(cells)
            cells.append(cell)
            cell["reason"] = _early_refusal(story_id, info, cell["fork_id"], earlier, exists)
            if cell["reason"] is None:
                _build(cell, info, variant, labels, ws_real, state, validate, earlier, argvs)
    return cells


def totals(cells):
    """Spec 3.3's totals of a cell plan: "ok" cells are jobs; "refused" and "invalid" are refused."""
    ok = [c for c in cells if c["status"] == "ok"]
    counts = dict((level, sum(1 for c in ok if c["level"] == level)) for level in LEVELS)
    refused = sum(1 for c in cells if c["status"] in ("refused", "invalid"))
    text = "%d jobs: %d re-plan, %d new stills, %d render-only" % (
        len(ok), counts["replan"], counts["stills"], counts["render"])
    if refused:
        text += "; %d refused" % refused
    return {"jobs": len(ok), "replan": counts["replan"], "stills": counts["stills"],
            "render": counts["render"], "refused": refused, "text": text}


def submit_order(cells, stories):
    """BF27: the indices of the "pending" cells, Re-plan first, then New stills, then Render, and
    within a level by story order, then by variant."""
    pending = [i for i, c in enumerate(cells) if c["status"] == "pending"]
    return sorted(pending, key=lambda i: (-LEVELS.index(cells[i]["level"]),
                                          stories.index(cells[i]["story_id"]), cells[i]["variant"]))


# ---------------------------------------------------------------------------
# The copy plan (spec 2.6)
# ---------------------------------------------------------------------------

def _mode(path):
    try:
        return os.lstat(path).st_mode
    except OSError:
        return 0


def _names(directory):
    """The names in directory when it is a real directory (never through a symlink), else []."""
    if not stat.S_ISDIR(_mode(directory)):
        return []
    try:
        return os.listdir(directory)
    except OSError:
        return []


def copy_plan(sdir, level):
    """[(relpath, bytes)] sorted by relpath: the regular files a fork at level copies from sdir
    (BF16). Symlinks and anything off the allowlist are never listed; images/ and clips/ are read
    only when they are real directories; a clip is listed only together with its provenance."""
    rels = list(COPY_FILES.get(level, ()))
    if level == "render":
        images = os.path.join(sdir, "images")
        rels += [os.path.join("images", n) for n in _names(images)
                 if STILL_RE.fullmatch(n) or n == "images.json"]
        clips = os.path.join(sdir, "clips")
        for name in _names(clips):
            prov = name + ".provenance.json"
            if (CLIP_RE.fullmatch(name) and stat.S_ISREG(_mode(os.path.join(clips, name)))
                    and stat.S_ISREG(_mode(os.path.join(clips, prov)))):
                rels += [os.path.join("clips", name), os.path.join("clips", prov)]
    out = []
    for rel in rels:
        try:
            st = os.lstat(os.path.join(sdir, rel))
        except OSError:
            continue
        if stat.S_ISREG(st.st_mode):
            out.append((rel, st.st_size))
    return sorted(out)


# ---------------------------------------------------------------------------
# The batch-record field fallback (spec 3.5, BF41c)
# ---------------------------------------------------------------------------

def fork_fallback(fork_rec, batch_rec, story_id, ws_real):
    """(code, fields, batch_id, number) of BF41c: "none", "gone", "mismatch" or "ok" (with a
    copy of the cell's submitted fields and the record's number)."""
    if not (isinstance(fork_rec, dict) and fork_rec.get("schema") == FORK_SCHEMA
            and fork_rec.get("fork_id") == story_id and isinstance(fork_rec.get("batch"), str)
            and lib.JOB_ID_RE.fullmatch(fork_rec["batch"])):
        return "none", None, None, None
    batch_id = fork_rec["batch"]
    if batch_rec is None:
        return "gone", None, batch_id, None
    mismatch = ("mismatch", None, batch_id, None)
    if not (isinstance(batch_rec, dict) and batch_rec.get("schema") == BATCH_SCHEMA
            and batch_rec.get("id") == batch_id and batch_rec.get("workspace") == ws_real
            and isinstance(batch_rec.get("cells"), list)):
        return mismatch
    found = [c for c in batch_rec["cells"] if isinstance(c, dict) and isinstance(c.get("fork_id"), str)
             and c["fork_id"].lower() == story_id.lower()]
    if len(found) != 1 or found[0]["fork_id"] != story_id:
        return mismatch
    cell = found[0]
    fields = cell.get("fields")
    if not (cell.get("story_id", _ABSENT_A) == fork_rec.get("source_story", _ABSENT_B)
            and cell.get("variant", _ABSENT_A) == fork_rec.get("variant", _ABSENT_B)
            and cell.get("status") == "queued" and isinstance(cell.get("job_id"), str)
            and isinstance(fields, dict) and fields.get("story_id") == story_id):
        return mismatch
    return "ok", json.loads(json.dumps(fields)), batch_id, batch_rec.get("number")
