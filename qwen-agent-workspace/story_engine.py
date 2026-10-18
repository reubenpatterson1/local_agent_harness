"""story_engine -- bin/ltx-movie's robust Phase 1 (docs/superpowers/specs/2026-10-17-robust-story-
lora-catalog-design.md): the model writes small scoped pieces (a JSON story bible, then one panel
at a time) through bin/qwen-agent one-shot subprocesses, code assembles story.md and pastes every
fixed sentence verbatim, deterministic checks run on every round, and a local critic (the fleet
analyst skill) proposes per-panel patches that code applies to named fields only; bin/judge-story
--patches is an optional final gate. stdlib only; loaded by path by bin/ltx-movie and
bin/judge-story; loads character_lib.py, lora_catalog.py and fleet_lib.py by path, only inside
functions.
"""

import collections
import copy
import datetime
import hashlib
import importlib.machinery
import json
import os
import re
import shlex
import subprocess
import sys
import time
import uuid

PLAN_SCHEMA = "ltx-movie.plan.v1"
CHECKS_SCHEMA = "ltx-movie.story-checks.v1"
RUN_SCHEMA = "ltx-movie.story-run.v1"
CATALOG_LORAS_SCHEMA = "ltx-movie.catalog-loras.v1"
ONESHOT_SCHEMA = "qwen-agent.oneshot.v1"
SHOT_TYPES = ("extreme wide shot", "wide shot", "medium shot", "medium close-up", "close-up",
              "extreme close-up")
CAMERA_SENTENCES = (
    ("static", "The camera stays static."),
    ("slow push-in", "The camera slowly pushes in."),
    ("slow pull-back", "The camera slowly pulls back."),
    ("slow pan left", "The camera slowly pans left."),
    ("slow pan right", "The camera slowly pans right."),
    ("slow tilt up", "The camera slowly tilts up."),
    ("slow tilt down", "The camera slowly tilts down."),
    ("tracking", "The camera tracks alongside the movement."),
)
CAMERA_KEYS = tuple(key for key, _ in CAMERA_SENTENCES)
ARC_ROLES = ("introduction", "rising", "climax", "falling", "resolution")
WORD_RANGES = {"chained": {"image1": (120, 170), "motion1": (25, 50), "motion": (15, 35)},
               "no_stills": {"prompt": (150, 220)},
               "shots": {"image": (80, 170), "motion": (10, 25)}}
NARRATION_WORDS = (3, 30)
MIN_WRITER_WORDS = {"image": 20, "prompt": 20, "motion": 5}
MAX_CAST = {"chained": 4, "no_stills": 4, "shots": 2}
PLAN_MAX_CALLS = 2
PANEL_MAX_CALLS = 2
CRITIC_MAX_ROUNDS = 3
CRITIC_CALLS_PER_ROUND = 2
MAX_PATCHES = 8
MIN_OK_SCORE = 7
JUDGE_MIN_SCORE = 7
LORA_PANEL_LIMIT = 4
PANEL_MAX_TOKENS = 1536
CRITIC_MAX_TOKENS = 4096
PANEL_TIMEOUT = 600
CRITIC_TIMEOUT = 900
JUDGE_TIMEOUT = 900
REQUEST_TIMEOUT = 600
MAX_LISTED = 40
REPEAT_JACCARD = 0.6
SCORE_KEYS = ("continuity", "story", "renderability")

StoryContext = collections.namedtuple("StoryContext", [
    "ws", "story_id", "story_dir", "mode", "panels", "seconds", "narrative", "goal", "members",
    "seed_image", "seed_agent_image", "story_model", "context_window", "video_model",
    "auto_lora", "catalog", "pinned", "stills_pinned", "judge"])

# Injectable seams (tests replace them with monkeypatch.setattr).
_now = time.monotonic
_utc = lambda: datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")  # noqa: E731

_VIOLATION_RE = re.compile(r"^(?:(story|plan)|(beat|panel) (\d+)): ([A-Z]+\d+) ([^:]+): (.*)$",
                           re.DOTALL)
_WS_RE = re.compile(r"\s+")


def _character_lib(ws):
    return importlib.machinery.SourceFileLoader(
        "character_lib", os.path.join(ws, "character_lib.py")).load_module()


def _lora_catalog(ws):
    return importlib.machinery.SourceFileLoader(
        "lora_catalog", os.path.join(ws, "lora_catalog.py")).load_module()


def _load_fleet(ws):
    try:
        return importlib.machinery.SourceFileLoader(
            "fleet_lib_for_story", os.path.join(ws, "fleet_lib.py")).load_module()
    except Exception:
        return None


def _story_manifest(ws):
    return importlib.machinery.SourceFileLoader(
        "ltx_story_manifest_for_movie", os.path.join(ws, "bin", "ltx-story-manifest")).load_module()


def plan_max_tokens(n):
    return max(4096, n * 250)


def plan_timeout(n):
    return max(600, n * 40)


def wall_clock_cap(n):
    return max(2400, n * 180)


def _collapse(text):
    return _WS_RE.sub(" ", text).strip()


def _sentence(text):
    """text stripped, whitespace collapsed, with "." appended unless it ends in . ! or ?"""
    text = _collapse(text)
    if text and not text.endswith((".", "!", "?")):
        text += "."
    return text


def _words(text):
    return len(text.split())


def _write_text(path, text):
    """Atomic write: <path>.<uuid4 hex>.tmp, then os.replace."""
    temporary = "%s.%s.tmp" % (path, uuid.uuid4().hex)
    try:
        with open(temporary, "x", encoding="utf-8") as f:
            f.write(text)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _write_json(path, obj):
    _write_text(path, json.dumps(obj, indent=2, ensure_ascii=False) + "\n")


def agent_cmd(ctx, prompt, *, max_tokens, image=None, skill=None):
    """The bin/qwen-agent one-shot argv of every robust-engine model call (RS5)."""
    cmd = [sys.executable, os.path.join(ctx.ws, "bin", "qwen-agent"),
           "--workspace", ctx.ws,
           "--max-tokens", str(max_tokens), "--max-rounds", "1",
           "--request-timeout", str(REQUEST_TIMEOUT)]
    if ctx.story_model:
        cmd += ["--model", ctx.story_model]
    if ctx.context_window:
        cmd += ["--context-window", str(ctx.context_window)]
    if image:
        cmd += ["--image", image]
    if skill == "analyst":
        cmd += ["--skill=analyst"]
    return cmd + ["--user-prompt", prompt]


def run_agent(ctx, prompt, *, max_tokens, timeout, image=None, skill=None, preflight_done=False):
    """(status, answer) of one bin/qwen-agent one-shot call (RS5). status is the envelope's
    status, "timeout" or "no_envelope"; answer is the envelope's non-empty answer or None."""
    cmd = agent_cmd(ctx, prompt, max_tokens=max_tokens, image=image, skill=skill)
    env = dict(os.environ)
    if preflight_done:
        env["QWEN_AGENT_PREFLIGHT_DONE"] = "1"
    proc = subprocess.Popen(cmd, cwd=ctx.ws, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, text=True, errors="replace", env=env)
    try:
        out, _err = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.communicate()
        return "timeout", None
    lines = [line for line in (out or "").splitlines() if line.strip()]
    try:
        envelope = json.loads(lines[-1])
    except (IndexError, ValueError):
        return "no_envelope", None
    if not isinstance(envelope, dict) or envelope.get("schema") != ONESHOT_SCHEMA:
        return "no_envelope", None
    answer = envelope.get("answer")
    if not isinstance(answer, str) or not answer.strip():
        answer = None
    return str(envelope.get("status")), answer


def extract_json(text):
    """The JSON object in a model reply, or None (RS6): the body of the first ``` fence when
    there is one, then the span from the first { to the last }."""
    if text is None:
        return None
    try:
        if "```" in text:
            start = text.index("```") + 3
            newline = text.find("\n", start)
            if newline == -1:
                body = text[start:]
                if body.startswith("json"):
                    body = body[4:]
            else:
                body = text[newline + 1:]
            end = body.find("```")
            text = body if end == -1 else body[:end]
        first, last = text.find("{"), text.rfind("}")
        if first == -1 or last < first:
            return None
        value = json.loads(text[first:last + 1])
    except Exception:
        return None
    return value if isinstance(value, dict) else None


def parse_violation(text):
    """A violation string as the story_checks.json object of Section 2.5."""
    match = _VIOLATION_RE.match(text)
    if match is None:
        return {"id": "V0", "name": "structure", "scope": "story", "index": None, "message": text}
    return {"id": match.group(4), "name": match.group(5),
            "scope": match.group(1) or match.group(2),
            "index": int(match.group(3)) if match.group(3) else None, "message": text}


# ---------------------------------------------------------------------------
# The plan: prompt (RS7), the compatible catalog set (LC6), normalization (RS9), checks
# (RS10, RS11)
# ---------------------------------------------------------------------------

NO_TOOL_SENTENCE = ("Reply with the JSON object only, with no text before or after it. Do not "
                    "call any tool: do NOT read any file, do NOT run run_python or any other "
                    "tool to check it, and do NOT count or recount words.")

PLAN_PROMPT_TEMPLATE = (
    'You are planning a short narrated movie (story-id "@@STORY_ID@@").\n'
    "\n"
    "Narrative to adapt:\n"
    "@@NARRATIVE@@\n"
    "\n"
    "@@GOAL_PARAGRAPH@@How this movie is made: @@MODE_PARAGRAPH@@\n"
    "\n"
    "@@SEED_PARAGRAPH@@Write the story bible as one JSON object with exactly these seven keys:\n"
    "\n"
    "title: the movie's title, at most 8 words.\n"
    "logline: one sentence of 8 to 40 words that summarises the story.\n"
    "cast: a list with one object per character who is ever on screen, with the keys id, phrase "
    "and descriptor. id is c1, c2, c3 and so on, in order. phrase is the character's referring "
    "phrase: at most four words, built only from details in their descriptor or stated by the "
    "narrative; the movie names them by this exact phrase everywhere. descriptor is their full "
    'visual description in 8 to 60 words that starts with "a " or "an " and does not end with a '
    "full stop: apparent age group, build, skin tone, hair colour, length and style, clothing and "
    "accessories.@@CAST_FIXED@@\n"
    "locations: a list with one object per place, with the keys id and setting. id is l1, l2 and "
    'so on. setting is one sentence of 12 to 45 words that starts with "The setting is" and names '
    "the period, the place, the ground and the light.\n"
    "props: a list with one object per object that matters to the story, with the keys id and "
    "name. id is p1, p2 and so on; name is a short noun phrase for the object. Use an empty list "
    "when no object matters.\n"
    "beats: a list of EXACTLY @@PANELS@@ objects, one per panel in order, with the keys index, "
    "arc, action, shot, camera, location and cast. index runs from 1 to @@PANELS@@. arc is one of "
    "introduction, rising, climax, falling, resolution, in story order; @@ARC_RULE@@ action is "
    "one sentence of 6 to 40 words saying what the characters physically do during these "
    "@@SECONDS@@ seconds: one continuous physical action that a camera can film, not a sequence "
    "of steps, with no dialogue and no on-screen text. shot is exactly one of: @@SHOT_LIST@@. "
    "camera is exactly one of: @@CAMERA_LIST@@. location is the id of the place where the beat "
    "happens. cast is the list of ids of the characters on screen in the beat, at most "
    "@@MAX_CAST@@.\n"
    "loras: @@LORA_PARAGRAPH@@\n"
    "\n"
    "@@MODE_RULES@@" + NO_TOOL_SENTENCE)

MODE_PARAGRAPHS = {
    "chained": ("it is ONE continuous take, built @@SECONDS@@ seconds at a time. Panel 1 starts "
                "from a single still picture, and every later panel continues from the exact "
                "last frame of the panel before it. There are no cuts and no jumps in time or "
                "place: a new place, object or character must arrive through visible movement "
                "inside a beat."),
    "no_stills": ("every panel is a separate @@SECONDS@@-second shot rendered from text alone, "
                  "joined to the next panel by a hard cut. Nothing carries over between panels "
                  "except what the text states."),
    "shots": ("it is a sequence of separate shots joined by cuts, @@SECONDS@@ seconds each. "
              "Every panel is one shot that starts from its own still picture. One beat is one "
              "action: a fight or a chase takes several beats."),
}
SEED_PARAGRAPH = ("An image is attached to this message. It IS the first frame of this movie. "
                  "Describe every person it shows faithfully in cast -- each one's apparent age "
                  "group, build, skin tone, hair, clothing and accessories as actually visible "
                  "-- invent no person who is not visible, and make beat 1 start from the exact "
                  "scene it shows.\n\n")
MODE_RULES = {
    "chained": ("Rules for this movie: keep consecutive beats at the same location unless the "
                "action itself moves the characters there, and put every character who can be "
                "seen in the opening frame in beat 1's cast.\n\n"),
    "shots": ("Rules for this movie: two people never touch on screen. Split every strike, grab, "
              "push, block or hand-off into two consecutive beats -- first a beat whose cast is "
              "only the person who acts, then a beat whose cast is only the person acted on -- so "
              "the contact itself is never on screen.\n\n"),
    "no_stills": "",
}
LORA_EMPTY_PARAGRAPH = ("an object with the keys global, per_beat and stills, each empty: global "
                        "and stills are empty lists and per_beat is an empty object.")
LORA_PICK_PARAGRAPH = (
    "an object with the keys global, per_beat and stills. Each pick is an object with the keys "
    "id and strength, taken from the LoRA catalog below; strength must lie inside that entry's "
    "range. global is a list of picks applied to every panel: at most one style LoRA, plus "
    "motion or physics LoRAs that suit the whole movie. per_beat maps a beat index, written as a "
    "string, to a list of motion or physics picks for that beat only; every beat may have at "
    "most one motion or physics LoRA in total, counting global. stills is a list of at most one "
    "stills LoRA.")


def _fill(template, fragments, scalars, narrative):
    """str.replace in the RS7 order: fragment tokens, then scalar tokens, then @@NARRATIVE@@
    last, so user text is never scanned for tokens."""
    text = template
    for token, value in fragments:
        text = text.replace(token, value)
    for token, value in scalars:
        text = text.replace(token, value)
    return text.replace("@@NARRATIVE@@", narrative)


def _goal_paragraph(goal):
    return "" if goal is None else "The target output goal is " + goal + ".\n\n"


def catalog_line(entry):
    """One catalog entry as the planner and the critic see it (RS7)."""
    lo, hi = entry["strength_range"]
    return "- %s: %s LoRA for %s, default strength %s, range %s to %s. %s Use when: %s Avoid when: %s" % (
        entry["id"], entry["kind"], entry["target"], repr(float(entry["default_strength"])),
        repr(float(lo)), repr(float(hi)), _sentence(entry["description"]),
        _sentence(entry["use_when"]),
        _sentence(entry["avoid_when"]) if entry["avoid_when"] else "nothing listed.")


def _pins_block(pins):
    if not pins:
        return ""
    lines = ["\nAlready applied to every panel by the user, not to be picked again:"]
    for pin in pins:
        if pin.get("catalog_id"):
            lines.append("\n- %s (%s) at strength %s"
                         % (pin["catalog_id"], pin["kind"], repr(float(pin["strength"]))))
        else:
            lines.append("\n- a LoRA outside the catalog at strength %s"
                         % repr(float(pin["strength"])))
    return "".join(lines)


def _arc_rule(n):
    if n >= 3:
        return ("the first beat is introduction, the last is resolution, and at least one beat "
                "is climax.")
    if n == 2:
        return "the first beat is introduction and the last is resolution."
    return "use climax."


def library_identities(ws):
    """[(name, trigger, referring_phrase)] for every character.json in the character library
    ($CHARACTER_LIBRARY_DIR, else <ws>/generated/characters) that parses as an object with
    string name, trigger and referring_phrase, sorted by name, whatever its status (RS37).
    Unreadable files are skipped. character_lib.py is not loaded."""
    root = os.environ.get("CHARACTER_LIBRARY_DIR") or os.path.join(ws, "generated", "characters")
    found = []
    try:
        names = sorted(os.listdir(root))
    except OSError:
        return found
    for entry in names:
        try:
            with open(os.path.join(root, entry, "character.json"), encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            continue
        if (isinstance(data, dict) and all(isinstance(data.get(k), str)
                                           for k in ("name", "trigger", "referring_phrase"))):
            found.append((data["name"], data["trigger"], data["referring_phrase"]))
    return sorted(found)


def undeclared_characters(ctx):
    """The library identities of characters that are not members of ctx (RS37)."""
    declared = {m.name for m in ctx.members}
    return [t for t in library_identities(ctx.ws) if t[0] not in declared]


def reserved_items(undeclared):
    return ", ".join('%s ("%s")' % (name, phrase) for name, _trigger, phrase in undeclared)


def _word_match(word, text):
    return re.search(r"(?<![\w-])" + re.escape(word) + r"(?![\w-])", text, re.IGNORECASE)


def undeclared_references(lib, text, undeclared, exact_phrase=False, masks=()):
    """[(name, kind, matched text)] for each undeclared character text refers to, first kind
    per character in the RS37 order: referring phrase, trigger, name. exact_phrase compares a
    cast entry's phrase by case-insensitive equality instead of occurrence. masks are
    phrases/words of declared or invented characters; in occurrence mode their spans are
    blanked before scanning so a reference contained in them is not reported."""
    scan = text
    if not exact_phrase and masks:
        for m in sorted({m for m in masks if m and m.strip()}, key=len, reverse=True):
            try:
                pattern = lib._phrase_regex(lib.normalize_phrase(m))
            except lib.CharacterError:
                pattern = None
            if pattern:
                scan = pattern.sub(lambda mo: "\x00" * len(mo.group(0)), scan)
            scan = re.sub(r"(?<![\w-])" + re.escape(m) + r"(?![\w-])",
                          lambda mo: "\x00" * len(mo.group(0)), scan, flags=re.IGNORECASE)
    hits = []
    for name, trigger, phrase in undeclared:
        hit = None
        if not phrase.strip():
            pass
        elif exact_phrase:
            if text.strip().lower() == phrase.strip().lower():
                hit = "referring phrase", text
        else:
            try:
                match = lib._phrase_regex(lib.normalize_phrase(phrase)).search(scan)
            except lib.CharacterError:
                match = None
            if match:
                hit = "referring phrase", match.group(0)
        for kind, word in (("trigger", trigger), ("name", name)):
            if hit is None and word.strip():
                match = _word_match(word, scan)
                if match:
                    hit = kind, match.group(0)
        if hit:
            hits.append((name, hit[0], hit[1]))
    return hits


def _undeclared_masks(lib, ctx, plan, undeclared):
    """Mask strings for undeclared_references: declared members' name, trigger and phrase, plus each
    plan cast phrase that does not itself name an undeclared character (RS37)."""
    masks = [m for member in ctx.members for m in (member.name, member.trigger, member.phrase)]
    if plan:
        masks += [e["phrase"] for e in plan["cast"] if isinstance(e.get("phrase"), str)
                  and (e.get("cast_name") or not undeclared_references(lib, e["phrase"], undeclared,
                                                                       exact_phrase=True))]
    return masks


def undeclared_message(prefix, where, hit):
    name, kind, matched = hit
    return ("%s %s names library character %s by its %s '%s'; library characters appear only "
            "when declared with --character %s" % (prefix, where, name, kind, matched, name))


def build_plan_prompt(ctx, compatible, pins):
    """The exact plan prompt of RS7."""
    undeclared = undeclared_characters(ctx)
    cast_fixed = ""
    if undeclared:
        cast_fixed = (" Never use these names or referring phrases, which belong to characters "
                      "who are not in this movie: " + reserved_items(undeclared) + ".")
    if ctx.members:
        cast_fixed += (" The following characters are already cast; list them first in cast with "
                      "exactly these ids, phrases and descriptors, and give your own characters "
                      "the next ids:")
        for i, member in enumerate(ctx.members, start=1):
            cast_fixed += '\n- id c%d, phrase "%s", descriptor "%s"' % (
                i, member.phrase, member.descriptor)
    if not ctx.auto_lora or not compatible:
        lora = LORA_EMPTY_PARAGRAPH
    else:
        lora = LORA_PICK_PARAGRAPH
        if ctx.mode == "no_stills":
            lora += " This movie has no stills, so stills stays empty."
        lora += (" Pick a LoRA only when its use-when text fits and its avoid-when text does "
                 "not; leave the lists empty when nothing fits.")
        lora += "\n\nLoRA catalog (pick only from these):\n"
        lora += "\n".join(catalog_line(e) for e in compatible) + _pins_block(pins)
    fragments = [
        ("@@GOAL_PARAGRAPH@@", _goal_paragraph(ctx.goal)),
        ("@@MODE_PARAGRAPH@@", MODE_PARAGRAPHS[ctx.mode]),
        ("@@SEED_PARAGRAPH@@", SEED_PARAGRAPH if ctx.seed_agent_image else ""),
        ("@@CAST_FIXED@@", cast_fixed),
        ("@@ARC_RULE@@", _arc_rule(ctx.panels)),
        ("@@SHOT_LIST@@", ", ".join(SHOT_TYPES)),
        ("@@CAMERA_LIST@@", ", ".join(CAMERA_KEYS)),
        ("@@LORA_PARAGRAPH@@", lora),
        ("@@MODE_RULES@@", MODE_RULES[ctx.mode]),
    ]
    scalars = [("@@STORY_ID@@", ctx.story_id), ("@@PANELS@@", str(ctx.panels)),
               ("@@SECONDS@@", ctx.seconds), ("@@MAX_CAST@@", str(MAX_CAST[ctx.mode]))]
    return _fill(PLAN_PROMPT_TEMPLATE, fragments, scalars, ctx.narrative)


def _readable(path):
    return isinstance(path, str) and os.path.isfile(path) and os.access(path, os.R_OK)


def _catalog_filter(ctx):
    """(compatible entries sorted by id, warning lines) for LC6's planner set."""
    if not ctx.auto_lora:
        return [], []
    lora_catalog = _lora_catalog(ctx.ws)
    member_triggers = {m.trigger.lower(): m.name for m in ctx.members}
    kept, warnings = [], []
    for entry in sorted(ctx.catalog.get("entries", []), key=lambda e: e["id"]):
        if entry["target"] == "video":
            ok = lora_catalog.compatible(entry, ctx.video_model)
        else:
            ok = (ctx.mode != "no_stills"
                  and lora_catalog.compatible(entry, lora_catalog.STILLS_BASE_MODEL))
        if not ok:
            continue
        if not _readable(entry["path"]):
            warnings.append("Warning: catalog LoRA %s is skipped: %s is not a readable file"
                            % (entry["id"], entry["path"]))
            continue
        clash = [t for t in entry["triggers"] if t.lower() in member_triggers]
        if clash:
            warnings.append("Warning: catalog LoRA %s is skipped: its trigger %s is character "
                            "%s's trigger" % (entry["id"], clash[0],
                                              member_triggers[clash[0].lower()]))
            continue
        kept.append(entry)
    return kept, warnings


def compatible_entries(ctx):
    """The planner's compatible catalog set (LC6), sorted by id. Prints nothing."""
    return _catalog_filter(ctx)[0]


def catalog_warnings(ctx):
    """The LC6 skip warnings for ctx's catalog (printed by run, recheck and the dry run)."""
    return _catalog_filter(ctx)[1]


def _clean_str(value):
    return _collapse(value) if isinstance(value, str) else ""


def _empty_loras():
    return {"global": [], "per_beat": {}, "stills": []}


def _list_of_objects(raw, key, shape, scope="plan"):
    value = raw.get(key)
    if key not in raw:
        shape.append("%s: P2 structure: the reply is missing the key '%s'" % (scope, key))
        return []
    if not isinstance(value, list):
        shape.append("%s: P2 structure: '%s' is not a list" % (scope, key))
        return []
    items = []
    for i, item in enumerate(value, start=1):
        if isinstance(item, dict):
            items.append(item)
        else:
            shape.append("%s: P2 structure: %s item %d is not an object" % (scope, key, i))
    return items


def _normalize_picks(picks, by_id):
    out = []
    for pick in picks if isinstance(picks, list) else []:
        if (isinstance(pick, dict) and "strength" not in pick and isinstance(pick.get("id"), str)
                and pick["id"] in by_id):
            pick = dict(pick, strength=by_id[pick["id"]]["default_strength"])
        out.append(pick)
    return out


def normalize_plan(ctx, raw):
    """(plan, shape): the Section 2.2 plan built from a parsed plan-writer reply (RS9), and the
    P2 violations for container shapes that normalization had to repair (a missing or non-list
    cast, locations, props or beats; an item that is not an object; a beat cast that is not a
    list). Wrong-typed string fields become "" and are reported by plan_checks."""
    shape = []
    plan = {"schema": PLAN_SCHEMA, "story_id": ctx.story_id, "mode": ctx.mode,
            "panels": ctx.panels, "seconds": ctx.seconds, "narrative": ctx.narrative,
            "goal": ctx.goal, "seed_image": ctx.seed_image, "video_model": ctx.video_model,
            "auto_lora": ctx.auto_lora,
            "title": _clean_str(raw.get("title")), "logline": _clean_str(raw.get("logline"))}
    cast = []
    for item in _list_of_objects(raw, "cast", shape):
        descriptor = _clean_str(item.get("descriptor"))
        if descriptor.endswith("."):
            descriptor = descriptor[:-1].rstrip()
        cast.append({"id": _clean_str(item.get("id")), "phrase": _clean_str(item.get("phrase")),
                     "descriptor": descriptor, "cast_name": None})
    for i, member in enumerate(ctx.members, start=1):
        fixed = {"id": "c%d" % i, "phrase": member.phrase, "descriptor": member.descriptor,
                 "cast_name": member.name}
        at = [j for j, c in enumerate(cast) if c["id"] == fixed["id"]]
        if at:
            cast[at[0]] = fixed
        else:
            cast.insert(i - 1, fixed)
    plan["cast"] = cast
    locations = []
    for item in _list_of_objects(raw, "locations", shape):
        setting = _clean_str(item.get("setting"))
        if setting and not setting.endswith((".", "!", "?")):
            setting += "."
        locations.append({"id": _clean_str(item.get("id")), "setting": setting})
    plan["locations"] = locations
    plan["props"] = [{"id": _clean_str(item.get("id")), "name": _clean_str(item.get("name"))}
                     for item in _list_of_objects(raw, "props", shape)]
    beats = []
    for k, item in enumerate(_list_of_objects(raw, "beats", shape), start=1):
        index = item.get("index")
        beat_cast = item.get("cast")
        if not isinstance(beat_cast, list):
            shape.append("beat %d: P2 structure: cast is not a list" % k)
            beat_cast = []
        beats.append({
            "index": index if isinstance(index, int) and not isinstance(index, bool) else 0,
            "arc": _clean_str(item.get("arc")).lower(), "action": _clean_str(item.get("action")),
            "shot": _clean_str(item.get("shot")).lower(),
            "camera": _clean_str(item.get("camera")).lower(),
            "location": _clean_str(item.get("location")),
            "cast": [_clean_str(c) if isinstance(c, str) else json.dumps(c) for c in beat_cast]})
    plan["beats"] = beats
    loras = raw.get("loras")
    if not ctx.auto_lora or not isinstance(loras, dict):
        picks = _empty_loras()
    else:
        by_id = {e["id"]: e for e in ctx.catalog.get("entries", [])}
        per_beat = loras.get("per_beat")
        picks = {"global": _normalize_picks(loras.get("global"), by_id),
                 "per_beat": {str(key): _normalize_picks(value, by_id)
                              for key, value in (per_beat.items()
                                                 if isinstance(per_beat, dict) else [])},
                 "stills": _normalize_picks(loras.get("stills"), by_id)}
    picks["pinned"] = [dict(pin) for pin in ctx.pinned]
    plan["loras"] = picks
    return plan, shape


_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")   # character_lib._SENTENCE_SPLIT_RE
_ID_RES = {"cast": re.compile(r"c[1-9][0-9]*"), "locations": re.compile(r"l[1-9][0-9]*"),
           "props": re.compile(r"p[1-9][0-9]*")}


def _q(text):
    return "'%s'" % text


def _setting_problems(setting):
    """The P4 details for one setting sentence (start, word count, one sentence)."""
    problems = []
    if not setting.startswith("The setting is "):
        problems.append('does not start with "The setting is"')
    words = _words(setting)
    if not 12 <= words <= 45:
        problems.append("is %d words; it must be 12-45" % words)
    if len([s for s in _SENTENCE_SPLIT_RE.split(setting.strip()) if s.strip()]) != 1:
        problems.append("is more than one sentence")
    return problems


def pasted_pieces(ctx, plan, k):
    """{field: [pasted sentences in assembly order]} for panel k (RS14): the pieces of each
    assembled field that the writer does not write."""
    beat = plan["beats"][k - 1]
    by_cast = {c["id"]: c for c in plan["cast"]}
    by_location = {l["id"]: l for l in plan["locations"]}
    setting = by_location[beat["location"]]["setting"] if beat["location"] in by_location else ""
    identities = [identity(by_cast[c]) for c in beat["cast"] if c in by_cast]
    shot = shot_sentence(beat) if beat["shot"] in SHOT_TYPES else ""
    camera = dict(CAMERA_SENTENCES).get(beat["camera"], "")
    pieces = [setting] + identities + [shot]
    if ctx.mode == "chained":
        if k == 1:
            return {"image": pieces, "motion": [camera], "narration": []}
        return {"motion": [], "narration": []}
    if ctx.mode == "no_stills":
        return {"prompt": identities + [setting, shot, camera], "narration": []}
    return {"image": pieces, "motion": [camera], "narration": []}


def identity(cast_entry):
    """The identity sentence of a plan cast entry (character_lib.identity_sentence format)."""
    phrase = cast_entry["phrase"]
    return phrase[:1].upper() + phrase[1:] + " is " + cast_entry["descriptor"] + "."


def shot_sentence(beat):
    shot = beat["shot"]
    return "The shot is " + ("an " if shot[:1] in "aeiou" else "a ") + shot + "."


def field_range(ctx, k, field):
    """(kind, (lo, hi)) of an assembled field with a word range, or None (Narration, and
    nothing else, has none)."""
    ranges = WORD_RANGES[ctx.mode]
    if ctx.mode == "chained":
        if field == "image" and k == 1:
            return "image", ranges["image1"]
        if field == "motion":
            return "motion", ranges["motion1"] if k == 1 else ranges["motion"]
    elif ctx.mode == "no_stills" and field == "prompt":
        return "prompt", ranges["prompt"]
    elif ctx.mode == "shots" and field in ("image", "motion"):
        return field, ranges[field]
    return None


def plan_checks(ctx, plan, shape=()):
    """(hard, advisory) violation strings for a normalized plan (RS10). shape holds
    normalize_plan's container-shape P2 violations, reported first."""
    hard, advisory = list(shape), []
    n = ctx.panels
    beats = plan["beats"]
    if len(beats) != n:
        hard.append("plan: P1 beat count: expected exactly %d beats, found %d" % (n, len(beats)))
    for i, beat in enumerate(beats):
        if beat["index"] != i + 1:
            hard.append("plan: P1 beat count: beat %d has index %r; beats must be numbered 1 to %d "
                        "in order" % (i + 1, beat["index"], n))
    for key in ("title", "logline"):
        if not plan[key]:
            hard.append("plan: P2 structure: %s must be a non-empty string" % key)
    valid = {}
    for kind, fields in (("cast", ("phrase", "descriptor")), ("locations", ("setting",)),
                         ("props", ("name",))):
        seen = set()
        valid[kind] = {}
        for pos, entry in enumerate(plan[kind], start=1):
            label = entry["id"] if _ID_RES[kind].fullmatch(entry["id"]) else None
            if label is None:
                hard.append("plan: P2 structure: %s entry %d has id %s; ids are %s1, %s2 and so on"
                            % (kind, pos, _q(entry["id"]), kind[0], kind[0]))
            elif label in seen:
                hard.append("plan: P2 structure: %s id %s is used twice" % (kind, _q(label)))
                label = None
            missing = [f for f in fields if not entry[f]]
            for field in missing:
                hard.append("plan: P2 structure: %s entry %d has no %s" % (kind, pos, field))
            if label is not None:
                seen.add(label)
                if not missing:
                    valid[kind][label] = entry
    if not plan["locations"]:
        hard.append("plan: P2 structure: there must be at least one location")
    for k, beat in enumerate(beats, start=1):
        for field in ("arc", "action", "shot", "camera", "location"):
            if not beat[field]:
                hard.append("beat %d: P2 structure: %s is missing or empty" % (k, field))
        if beat["location"] and beat["location"] not in valid["locations"]:
            hard.append("beat %d: P2 structure: location %s is not defined"
                        % (k, _q(beat["location"])))
        for c in beat["cast"]:
            if c not in valid["cast"]:
                hard.append("beat %d: P2 structure: cast id %s is not defined" % (k, _q(c)))
        for c in sorted(set(c for c in beat["cast"] if beat["cast"].count(c) > 1)):
            hard.append("beat %d: P2 structure: cast id %s is listed twice" % (k, _q(c)))
    lib = _character_lib(ctx.ws)
    phrases = {}
    for cid, entry in valid["cast"].items():
        try:
            lib.normalize_phrase(entry["phrase"])
        except lib.CharacterError as e:
            hard.append("plan: P3 cast entry: %s's %s" % (cid, e))
            continue
        words = _words(entry["phrase"])
        if entry["cast_name"] is None and words > 4:
            hard.append("plan: P3 cast entry: %s's phrase %s has %d words; at most 4"
                        % (cid, _q(entry["phrase"]), words))
        other = phrases.get(entry["phrase"].lower())
        if other is not None:
            hard.append("plan: P3 cast entry: %s's phrase %s is also %s's"
                        % (cid, _q(entry["phrase"]), other))
        else:
            phrases[entry["phrase"].lower()] = cid
        try:
            lib.validate_descriptor(entry["descriptor"])
        except lib.CharacterError as e:
            hard.append("plan: P3 cast entry: %s's %s" % (cid, e))
    for lid, entry in valid["locations"].items():
        for problem in _setting_problems(entry["setting"]):
            hard.append("plan: P4 setting sentence: %s's setting %s" % (lid, problem))
    arcs = [beat["arc"] if beat["arc"] in ARC_ROLES else None for beat in beats]
    for k, beat in enumerate(beats, start=1):
        if beat["arc"] and beat["arc"] not in ARC_ROLES:
            hard.append("beat %d: P5 arc: %s is not one of %s"
                        % (k, _q(beat["arc"]), ", ".join(ARC_ROLES)))
    required = (() if n == 1 else ("introduction", "resolution") if n == 2
                else ("introduction", "climax", "resolution"))
    for role in required:
        if role not in arcs:
            hard.append("plan: P5 arc: no beat has arc %s" % _q(role))
    for k in range(2, len(arcs) + 1):
        a, b = arcs[k - 2], arcs[k - 1]
        if a and b and ARC_ROLES.index(b) < ARC_ROLES.index(a):
            advisory.append("beat %d: P6 arc order: %s follows %s" % (k, _q(b), _q(a)))
    if n >= 2 and arcs:
        if arcs[0] and arcs[0] != "introduction":
            advisory.append("plan: P6 arc order: the first beat's arc is %s, not 'introduction'"
                            % _q(arcs[0]))
        if arcs[-1] and arcs[-1] != "resolution":
            advisory.append("plan: P6 arc order: the last beat's arc is %s, not 'resolution'"
                            % _q(arcs[-1]))
    for k, beat in enumerate(beats, start=1):
        if beat["shot"] and beat["shot"] not in SHOT_TYPES:
            hard.append("beat %d: P7 shot type: %s is not one of: %s"
                        % (k, _q(beat["shot"]), ", ".join(SHOT_TYPES)))
        if beat["camera"] and beat["camera"] not in CAMERA_KEYS:
            hard.append("beat %d: P8 camera: %s is not one of: %s"
                        % (k, _q(beat["camera"]), ", ".join(CAMERA_KEYS)))
        if len(beat["cast"]) > MAX_CAST[ctx.mode]:
            hard.append("beat %d: P9 cast count: %d characters on screen; at most %d in this mode"
                        % (k, len(beat["cast"]), MAX_CAST[ctx.mode]))
        if k <= n:
            for field, pasted in pasted_pieces(ctx, plan, k).items():
                spec = field_range(ctx, k, field)
                pasted = [p for p in pasted if p]
                if spec is None or not pasted:
                    continue
                kind, (lo, hi) = spec
                used = _words(" ".join(pasted))
                if hi - used < MIN_WRITER_WORDS[kind]:
                    hard.append("beat %d: P10 word budget: %s: the pasted sentences take %d of its "
                                "%d-%d words, leaving fewer than %d for the writer"
                                % (k, field.capitalize(), used, lo, hi, MIN_WRITER_WORDS[kind]))
    if ctx.mode == "chained":
        for k in range(2, len(beats) + 1):
            prev, cur = beats[k - 2]["location"], beats[k - 1]["location"]
            if (prev in valid["locations"] and cur in valid["locations"] and prev != cur):
                advisory.append("beat %d: P11 location change: moves from %s to %s with no cut; "
                                "the action must carry the characters there" % (k, prev, cur))
        opening = set(beats[0]["cast"]) if beats else set()
        for k in range(2, len(beats) + 1):
            for c in beats[k - 1]["cast"]:
                if c in valid["cast"] and c not in opening:
                    advisory.append("beat %d: P12 new character: %s is not in the opening frame; "
                                    "their look is left to the video model" % (k, c))
    undeclared = undeclared_characters(ctx)
    if undeclared:
        masks = _undeclared_masks(lib, ctx, plan, undeclared)
        texts = []
        for entry in plan["cast"]:
            if entry["cast_name"] is None:
                texts.append(("%s's phrase" % entry["id"], entry["phrase"], True))
                texts.append(("%s's descriptor" % entry["id"], entry["descriptor"], False))
        texts += [("the title", plan["title"], False), ("the logline", plan["logline"], False)]
        texts += [("%s's setting" % l["id"], l["setting"], False) for l in plan["locations"]]
        texts += [("%s's name" % p["id"], p["name"], False) for p in plan["props"]]
        texts += [("beat %d's action" % k, b["action"], False)
                  for k, b in enumerate(beats, start=1)]
        for where, text, exact in texts:
            for hit in undeclared_references(lib, text, undeclared, exact_phrase=exact,
                                        masks=masks):
                hard.append(undeclared_message("plan: P13 undeclared character:", where, hit))
    return hard, advisory


def _is_pick(pick):
    return (isinstance(pick, dict) and isinstance(pick.get("id"), str)
            and isinstance(pick.get("strength"), (int, float))
            and not isinstance(pick.get("strength"), bool))


def lora_checks(ctx, plan, compatible_by_id, catalog_by_id):
    """(hard, advisory) LoRA violations of a plan (RS11, LC12). Not run without auto LoRA."""
    hard, advisory = [], []
    if not ctx.auto_lora:
        return hard, advisory
    n = ctx.panels
    loras = plan["loras"]
    lora_catalog = _lora_catalog(ctx.ws)

    def check_pick(pick, scope, target):
        if not _is_pick(pick):
            hard.append("%s: L1 catalog id: pick %s is not an object with an id and a numeric "
                        "strength" % (scope, json.dumps(pick, ensure_ascii=False)))
            return None
        entry = catalog_by_id.get(pick["id"])
        if entry is None:
            hard.append("%s: L1 catalog id: %s is not in the catalog" % (scope, _q(pick["id"])))
            return None
        if target == "video" and entry["target"] != "video":
            hard.append("%s: L1 catalog id: %s is a stills LoRA; global and per-beat picks must "
                        "be video LoRAs" % (scope, _q(pick["id"])))
            return None
        if target == "stills" and entry["target"] != "stills":
            hard.append("%s: L1 catalog id: %s is a video LoRA; a stills pick must be a stills "
                        "LoRA" % (scope, _q(pick["id"])))
            return None
        model = ctx.video_model if target == "video" else lora_catalog.STILLS_BASE_MODEL
        if not lora_catalog.compatible(entry, model):
            hard.append("%s: L1 catalog id: %s does not support model %s"
                        % (scope, _q(pick["id"]), model))
            return None
        if pick["id"] not in compatible_by_id:
            hard.append("%s: L1 catalog id: %s is not in the catalog" % (scope, _q(pick["id"])))
            return None
        lo, hi = entry["strength_range"]
        if not lo <= pick["strength"] <= hi:
            hard.append("plan: L5 strength: %s strength %s is outside its range %s to %s"
                        % (_q(pick["id"]), repr(float(pick["strength"])), repr(float(lo)),
                           repr(float(hi))))
        return dict(entry, strength=pick["strength"])

    global_picks = [e for e in (check_pick(p, "plan", "video") for p in loras["global"]) if e]
    per_beat = {}
    for key, picks in loras["per_beat"].items():
        if key not in [str(k) for k in range(1, n + 1)]:
            hard.append("plan: L1 catalog id: per_beat key %s is not a beat number from 1 to %d"
                        % (_q(key), n))
            continue
        per_beat[int(key)] = [e for e in (check_pick(p, "beat %s" % key, "video")
                                          for p in picks) if e]
    stills = [e for e in (check_pick(p, "plan", "stills") for p in loras["stills"]) if e]
    pins = loras.get("pinned", [])

    def pin_label(pin):
        return pin["catalog_id"] or "pinned LoRA"

    styles = ([pin_label(p) for p in pins if p.get("kind") == "style"]
              + [e["id"] for e in global_picks if e["kind"] == "style"])
    if len(styles) > 1:
        hard.append("plan: L2 style: %d style LoRAs for every panel (%s); at most 1"
                    % (len(styles), ", ".join(styles)))
    for k in sorted(per_beat):
        for e in per_beat[k]:
            if e["kind"] == "style":
                hard.append("beat %d: L2 style: style LoRA %s can only be a global pick"
                            % (k, _q(e["id"])))
    by_cast = {c["id"]: c for c in plan["cast"]}
    reported_dupes = set()
    pin_paths = {os.path.realpath(p["path"]) for p in pins}
    for k in range(1, n + 1):
        beat = plan["beats"][k - 1] if k <= len(plan["beats"]) else {"cast": []}
        loras_k = ([(pin_label(p), p.get("kind"), p.get("catalog_id"), None) for p in pins]
                   + [(e["id"], e["kind"], e["id"], e["path"]) for e in global_picks]
                   + [(e["id"], e["kind"], e["id"], e["path"]) for e in per_beat.get(k, [])]
                   + [("character " + by_cast[c]["cast_name"], "character", None, None)
                      for c in beat["cast"] if c in by_cast and by_cast[c]["cast_name"]])
        motion = [label for label, kind, _i, _p in loras_k if kind in ("motion", "physics")]
        if len(motion) > 1:
            hard.append("beat %d: L3 motion: %d motion or physics LoRAs on this panel (%s); at "
                        "most 1" % (k, len(motion), ", ".join(motion)))
        if len(loras_k) > LORA_PANEL_LIMIT:
            message = ("beat %d: L4 LoRA count: %d LoRAs on this panel (%s); at most %d"
                       % (k, len(loras_k), ", ".join(l[0] for l in loras_k), LORA_PANEL_LIMIT))
            (hard if (global_picks or per_beat.get(k)) else advisory).append(message)
        ids = [i for _l, _k, i, _p in loras_k if i]
        for dup in sorted(set(i for i in ids if ids.count(i) > 1)):
            if dup not in reported_dupes:
                reported_dupes.add(dup)
                hard.append("beat %d: L6 duplicate: %s is applied twice on this panel"
                            % (k, _q(dup)))
        for label, _kind, catalog_id, path in loras_k:
            if (path and os.path.realpath(path) in pin_paths and catalog_id not in reported_dupes):
                reported_dupes.add(catalog_id)
                hard.append("beat %d: L6 duplicate: %s is applied twice on this panel"
                            % (k, _q(catalog_id)))
    if len(loras["stills"]) > 1:
        hard.append("plan: L7 stills: %d stills LoRAs; at most 1" % len(loras["stills"]))
    if ctx.mode == "no_stills" and loras["stills"]:
        hard.append("plan: L7 stills: this movie has no stills; stills must be empty")
    for e in stills:
        if os.path.realpath(e["path"]) in set(ctx.stills_pinned):
            hard.append("plan: L7 stills: %s is also passed with --stills-lora" % _q(e["id"]))
    return hard, advisory


# ---------------------------------------------------------------------------
# Panels: lexicons (RS16), the panel prompt (RS12), writer parts and cleanup (RS13),
# assembly (RS14), panel checks (RS15) and the undeclared-character check N15 (RS37)
# ---------------------------------------------------------------------------

APPEARANCE_WORDS = frozenset("""
    red orange yellow green blue purple violet pink brown black white grey gray silver gold golden
    crimson scarlet navy beige auburn blonde blond brunette ginger
    hair haired ponytail braid braided curls curly bald beard bearded moustache mustache stubble
    freckled wrinkled complexion
    wearing wears dressed dress shirt jacket coat cloak kimono robe hood hat helmet trousers pants
    jeans skirt boots shoes sandals gloves scarf belt armor armour uniform tunic vest apron glasses
    spectacles earrings necklace bracelet
    slender stocky muscular skinny plump pale tanned
    lighting lit sunlight moonlight palette colour color cinematic photorealistic rendered style
    camera lens zoom zooms dolly framing close-up""".split())
_APPEARANCE_RE = re.compile(r"(?<![\w-])(?:%s)(?![\w-])" % "|".join(
    re.escape(w) for w in sorted(APPEARANCE_WORDS, key=lambda w: (-len(w), w))), re.IGNORECASE)
DIALOGUE_RE = re.compile(
    r"\b(?:say|says|said|saying|shout|shouts|shouted|shouting|whisper|whispers|whispered|"
    r"whispering|yell|yells|yelled|yelling|ask|asks|asked|asking|reply|replies|replied|replying|"
    r"tell|tells|told|telling|speak|speaks|spoke|speaking|exclaim|exclaims|exclaimed|mutter|"
    r"mutters|muttered|murmur|murmurs|murmured|call(?:s|ed)?\s+out)\b", re.IGNORECASE)
ONSCREEN_TEXT_RE = re.compile(
    r"\b(?:captions?|subtitles?|title\s+cards?|on-screen\s+text|text\s+reading|that\s+reads|"
    r"which\s+reads|lettering|inscription|written\s+words)\b", re.IGNORECASE)
CUT_RE = re.compile(
    r"\b(?:cuts?\s+to|smash\s+cut|jump\s+cut|fades?\s+(?:in|out|to)|dissolves?\s+to|flashback|"
    r"hours\s+later|the\s+next\s+(?:day|morning))\b", re.IGNORECASE)
PLACEHOLDER_RE = re.compile(r"<[^<>]{1,80}>")
COPIED_EXAMPLES = (
    "The setting is a dense cedar forest in feudal Japan, tall trunks and ferns behind, the "
    "ground covered in leaf litter, under flat overcast grey light",
    "walking to a door, opening it, stepping through, and closing it behind them",
    "raising the blade, drawing back the arm, lunging forward",
    "recoiling, staggering, clutching the wound, falling",
    "her eyebrows angle down and her lips press together",
    "a charge, a draw and a strike",
)
_LABEL_RE = re.compile(r"^(?:title|image|motion|prompt|narration)\s*:\s*", re.IGNORECASE)
_QUOTE_PAIRS = (('"', '"'), ("“", "”"))
_TITLE_CHARS_RE = re.compile(r"[^A-Za-z0-9 '-]")
LABELS = {"image": "Image", "motion": "Motion", "prompt": "Prompt", "narration": "Narration"}

PANEL_PROMPT_TEMPLATE = (
    'You are writing panel @@K@@ of @@PANELS@@ of a short narrated movie (story-id '
    '"@@STORY_ID@@").\n'
    "\n"
    "Narrative to adapt:\n"
    "@@NARRATIVE@@\n"
    "\n"
    "@@GOAL_PARAGRAPH@@How this movie is made: @@MODE_PARAGRAPH@@\n"
    "\n"
    "@@PANEL_RULES@@The beats of the whole movie, one per panel (this panel is marked >>):\n"
    "@@BEAT_LINES@@\n"
    "\n"
    "This panel's beat: @@ACTION@@\n"
    "Characters on screen in this panel, named only by these exact referring phrases: "
    "@@CAST_PHRASES@@\n"
    "@@RESERVED@@@@PREVIOUS@@\n"
    "@@SEED_PANEL@@Write this panel as one JSON object with exactly these keys:\n"
    "\n"
    "@@KEY_LINES@@\n"
    "\n"
    "@@FIX_BLOCK@@" + NO_TOOL_SENTENCE)
SHOTS_PANEL_RULES = ("Rules for this shot: two people never touch on screen, nothing outside the "
                     "frame is ever mentioned, and who faces whom is shown with fixed left and "
                     "right screen direction.\n\n")
SEED_PANEL = ("An image is attached to this message. It IS this movie's first frame: describe in "
              "image exactly what it shows -- each person's pose and place in the frame, the "
              "background, the lighting, the colour palette and the visual style -- and start "
              "motion from that exact pose.\n\n")
KEY_LINE_TEMPLATES = {
    "title": "title: a short title for the panel, 2 to 6 words.",
    "chained_image": (
        "image: W1 to W2 words describing the opening frame as one still picture: where each "
        "character stands and which way they face, the background, the lighting and colour "
        "palette, the camera viewpoint and the rendering style. Do not describe any character's "
        "appearance or clothing, do not write a sentence about the place itself and do not name "
        "the shot type: the pipeline adds each character's description, the place's setting "
        "sentence and the shot type to this field itself."),
    "chained_motion1": (
        "motion: W1 to W2 words in one or two plain sentences: what the characters physically do "
        "during these @@SECONDS@@ seconds. Name each character only by their referring phrase, "
        "word for word. Describe ONE continuous physical motion, not a sequence of separate "
        "steps. Do not mention the camera: the pipeline adds the camera sentence."),
    "chained_motion": (
        "motion: W1 to W2 words in one or two plain sentences: what the characters physically do "
        "during these @@SECONDS@@ seconds, continuing from where the previous panel left them. "
        "Name each character only by their referring phrase, word for word. Describe ONE "
        "continuous physical motion, not a sequence of separate steps: @@SECONDS@@ seconds is "
        "enough for a single gesture, a few footsteps or the start of a movement. Do not describe "
        "appearance, clothing, setting, lighting, colour, style, camera or lens -- all of that is "
        "already on screen."),
    "no_stills_prompt": (
        "prompt: W1 to W2 words in the present tense: one flowing paragraph in strict "
        "chronological order that opens with the main action, carries enough separate beats to "
        "fill the full @@SECONDS@@ seconds, links them with temporal connectors (initially, as, "
        "then, while, a moment later), names the ambient and environmental sounds alongside the "
        "actions that make them, and states the camera viewpoint and the lighting and colour. "
        "Name each character only by their referring phrase. Do not describe any character's "
        "appearance or clothing, do not write a sentence about the place itself and do not name "
        "the shot type or the camera motion: the pipeline adds each character's description, the "
        "place's setting sentence, the shot type and the camera motion itself. Describe only what "
        "is physically observable, with no mood words, no spoken dialogue and no markdown."),
    "shots_image": (
        "image: W1 to W2 words describing this shot's first frame as one still picture: where "
        "each character stands and which way they face, using fixed left and right screen "
        "direction; the background; the lighting and colour palette; the camera viewpoint; and "
        "the rendering style. Do not describe any character's appearance or clothing, do not "
        "write a sentence about the place itself and do not name the shot type: the pipeline "
        "adds each character's description, the place's setting sentence and the shot type to "
        "this field itself. Never name a person who is not in this shot."),
    "shots_motion": (
        "motion: ONE sentence of W1 to W2 words naming ONE character by their referring phrase "
        "and the ONE physical action they perform during these @@SECONDS@@ seconds. Never chain "
        "actions with then, while, meanwhile, simultaneously, afterwards, followed by or a comma "
        "before and, and never use a semicolon. Do not mention the camera: the pipeline adds the "
        "camera sentence."),
    "narration": "narration: one sentence of voice-over narration, 3 to 30 words.",
}


def writer_keys(mode, k):
    """The writer parts of panel k (Section 2.3), in order."""
    if mode == "chained":
        return ("title", "image", "motion", "narration") if k == 1 else (
            "title", "motion", "narration")
    if mode == "no_stills":
        return ("title", "prompt", "narration")
    return ("title", "image", "motion", "narration")


def writer_targets(ctx, plan, k):
    """{field: (W1, W2)} for every writer field with a word range (RS14)."""
    targets = {}
    for field, pasted in pasted_pieces(ctx, plan, k).items():
        spec = field_range(ctx, k, field)
        if spec is None:
            continue
        kind, (lo, hi) = spec
        used = _words(" ".join(p for p in pasted if p))
        w1 = max(MIN_WRITER_WORDS[kind], lo - used)
        targets[field] = (w1, max(w1, hi - used))
    return targets


def title_fallback(action):
    """The first five words of the beat action, letters, digits, spaces, ' and - only."""
    return _collapse(_TITLE_CHARS_RE.sub("", " ".join(action.split()[:5])))


def clean_writer(lib, text, pasted=()):
    """RS13 cleanup of one writer string: strip; drop one leading field label and one pair of
    surrounding double quotes; collapse whitespace; blank every case- and whitespace-
    insensitive occurrence of a pasted sentence (character_lib._passage_spans and _blank, each
    span widened over the sentence's own full stop); collapse again."""
    if not isinstance(text, str):
        return ""
    text = _LABEL_RE.sub("", text.strip(), count=1).strip()
    for left, right in _QUOTE_PAIRS:
        if len(text) >= 2 and text.startswith(left) and text.endswith(right):
            text = text[1:-1]
            break
    text = _collapse(text)
    pasted = [p for p in pasted if p]
    if pasted:
        spans = [(s, e + 1 if text[e:e + 1] == "." else e)
                 for s, e in lib._passage_spans(text, pasted)]
        text = _collapse(lib._blank(text, spans))
    return text


def empty_parts(mode, k, plan):
    parts = {key: "" for key in writer_keys(mode, k)}
    parts["title"] = title_fallback(plan["beats"][k - 1]["action"]) or "Panel %d" % k
    return parts


def parse_panel_reply(ctx, plan, k, answer):
    """The cleaned writer parts of panel k from a reply, or None when the reply is not valid
    (RS13): every non-title key must hold a string that is non-empty after cleanup."""
    obj = extract_json(answer)
    if obj is None:
        return None
    lib = _character_lib(ctx.ws)
    pasted = pasted_pieces(ctx, plan, k)
    parts = {}
    for key in writer_keys(ctx.mode, k):
        if key == "title":
            continue
        value = clean_writer(lib, obj.get(key), pasted.get(key, ()))
        if not value:
            return None
        parts[key] = value
    title = clean_writer(lib, obj.get("title"))
    if not title or _words(title) > 6:
        title = title_fallback(plan["beats"][k - 1]["action"]) or "Panel %d" % k
    return dict({"title": title}, **parts)


def panel_fields(ctx, plan, parts, k):
    """[(Label, assembled text)] of panel k in file order (RS14)."""
    p = parts[k - 1]
    pasted = pasted_pieces(ctx, plan, k)

    def join(pieces):
        return " ".join(_sentence(piece) for piece in pieces if piece and piece.strip())

    fields = []
    if (ctx.mode == "chained" and k == 1) or ctx.mode == "shots":
        image = pasted["image"]
        fields.append(("Image", join(image[:-1] + [p.get("image", "")] + image[-1:])))
    if ctx.mode == "no_stills":
        fields.append(("Prompt", join([p.get("prompt", "")] + pasted["prompt"])))
    else:
        fields.append(("Motion", join([p.get("motion", "")] + pasted["motion"])))
    fields.append(("Narration", _sentence(p.get("narration", ""))))
    return fields


def assemble(ctx, plan, parts):
    """The story.md text of a plan and its writer parts (RS14)."""
    lines = ["# " + plan["title"], "", plan["logline"], ""]
    if ctx.mode == "shots":
        lines.append("## Characters")
        lines += ['- "%s": %s.' % (c["phrase"], c["descriptor"]) for c in plan["cast"]]
        lines.append("")
    for k in range(1, len(parts) + 1):
        lines.append("## Panel %d — %s" % (k, parts[k - 1]["title"]))
        lines += ["%s: %s" % (label, text) for label, text in panel_fields(ctx, plan, parts, k)]
        lines.append("")
    return "\n".join(lines[:-1]) + "\n"


def _norm_text(text):
    return " ".join(text.lower().split()).rstrip(".")


def _first(regex, text):
    match = regex.search(text)
    return " ".join(match.group(0).lower().split()) if match else None


def _valid_phrases(lib, plan):
    phrases = {}
    for c in plan["cast"]:
        try:
            phrases[lib.normalize_phrase(c["phrase"])] = c["id"]
        except lib.CharacterError:
            continue
    return phrases


def _field_checks(ctx, lib, plan, k, title, fields, writers, ids, undeclared):
    """(hard, advisory) of one panel: the RS15 checks named in ids, plus N15 when in ids.
    fields: [(Label, assembled text)]; writers: {Label: writer text}; plan may be None (then
    every check that needs the plan is skipped)."""
    hard, advisory = [], []
    beat = plan["beats"][k - 1] if plan and k <= len(plan["beats"]) else None
    phrases = _valid_phrases(lib, plan) if plan else {}
    by_cast = {c["id"]: c for c in plan["cast"]} if plan else {}
    by_location = {l["id"]: l for l in plan["locations"]} if plan else {}
    prefix = "panel %d:" % k

    def add(target, check, name, label, detail):
        target.append("%s %s %s: %s: %s" % (prefix, check, name, label, detail))

    action_fields = ("Image", "Motion", "Prompt")
    for label, text in fields:
        writer = writers.get(label, "")
        key = label.lower()
        if "N1" in ids and label != "Narration" and not (ctx.mode == "shots" and label == "Motion"):
            spec = field_range(ctx, k, key)
            if spec:
                lo, hi = spec[1]
                if not lo <= _words(text) <= hi:
                    add(hard, "N1", "word count", label,
                        "is %d words; it must be %d-%d" % (_words(text), lo, hi))
        if ctx.mode == "chained" and k >= 2 and label == "Motion" and plan:
            humans = [p for p in phrases if not lib.is_animal_phrase(p)]
            animals = [p for p in phrases if lib.is_animal_phrase(p)]
            if "N2" in ids:
                for sentence in lib._SENTENCE_SPLIT_RE.split(text.strip()):
                    refs = [r for r in lib._person_refs(sentence, humans, animals, [])
                            if r[2] in lib.SHOTS_PERSON_NOUNS]
                    if refs:
                        add(hard, "N2", "referring phrase", label,
                            "names %s outside every referring phrase; name each character by "
                            "their exact phrase" % _q(refs[0][2]))
                        break
            if "N3" in ids:
                blanked = lib._blank(text, lib._passage_spans(
                    text, list(phrases) + [p["name"] for p in plan["props"] if p["name"]]))
                word = _first(_APPEARANCE_RE, blanked)
                if word:
                    add(hard, "N3", "appearance", label,
                        "says %s; panels after the first never re-describe appearance, clothing, "
                        "setting, lighting, colour, style or camera" % _q(word))
        if "N4" in ids and label != "Narration" and beat is not None:
            for phrase in lib.find_phrases(writer, list(phrases)):
                if phrases[phrase] not in beat["cast"]:
                    add(hard, "N4", "stray cast", label,
                        "names %s, who is not in beat %d's cast" % (_q(phrase), k))
                    break
        pasted_field = ((ctx.mode == "chained" and k == 1 and label == "Image")
                        or (ctx.mode == "shots" and label == "Image")
                        or (ctx.mode == "no_stills" and label == "Prompt"))
        if pasted_field and beat is not None:
            norm = _norm_text(text)
            if "N5" in ids and beat["location"] in by_location:
                own = by_location[beat["location"]]
                if _norm_text(own["setting"]) not in norm:
                    add(hard, "N5", "setting sentence", label,
                        "lacks %s's setting sentence word for word" % own["id"])
                else:
                    for other in plan["locations"]:
                        if (other["id"] != own["id"] and other["setting"]
                                and _norm_text(other["setting"]) != _norm_text(own["setting"])
                                and _norm_text(other["setting"]) in norm):
                            add(hard, "N5", "setting sentence", label,
                                "contains %s's setting sentence; beat %d is at %s"
                                % (other["id"], k, own["id"]))
                            break
            if "N6" in ids:
                for cid in beat["cast"]:
                    entry = by_cast.get(cid)
                    if entry is None or (ctx.mode == "shots" and entry["cast_name"]):
                        continue
                    if _norm_text(entry["descriptor"]) not in norm:
                        add(hard, "N6", "description", label,
                            "lacks %s's description word for word" % cid)
                        break
        if label in action_fields:
            if "N7" in ids:
                if any(q in writer for q in ('"', "“", "”")):
                    add(hard, "N7", "dialogue and text", label, "contains a double quote")
                else:
                    word = _first(DIALOGUE_RE, writer) or _first(ONSCREEN_TEXT_RE, writer)
                    if word:
                        add(hard, "N7", "dialogue and text", label, "says %s" % _q(word))
            if "N8" in ids and ctx.mode != "shots":
                word = _first(lib._OFFSCREEN_RE, writer)
                if word:
                    add(hard, "N8", "off-screen", label,
                        "says %s; describe only what is in the frame" % _q(word))
            if "N9" in ids:
                word = _first(CUT_RE, writer)
                if word:
                    add(hard, "N9", "cut wording", label,
                        "says %s; one panel is one continuous shot" % _q(word))
        if "N10" in ids:
            found = PLACEHOLDER_RE.search(writer)
            copied = found.group(0) if found else next(
                (ex for ex in COPIED_EXAMPLES if _norm_text(ex) in _norm_text(writer)), None)
            if copied:
                add(hard, "N10", "copied example", label, "contains template text %s" % _q(copied))
        if "N11" in ids and label == "Narration" and not text.strip():
            hard.append("%s N11 narration: Narration: is empty" % prefix)
    if "N15" in ids and undeclared:
        masks = _undeclared_masks(lib, ctx, plan, undeclared)
        for label, text in [("Title", title)] + list(fields):
            for hit in undeclared_references(lib, text, undeclared, masks=masks):
                hard.append(undeclared_message("%s N15 undeclared character:" % prefix,
                                               label + ":", hit))
    if "N12" in ids and ctx.mode == "chained":
        writer = writers.get("Motion", "")
        chain = _first(lib._CHAIN_WORD_RE, writer)
        if chain is None and ";" in writer:
            chain = ";"
        if chain is None and lib._COMMA_AND_RE.search(writer):
            chain = ", and"
        if chain:
            add(advisory, "N12", "one action", "Motion", "chains actions with %s" % _q(chain))
    if "N14" in ids:
        narration = dict(fields).get("Narration", "")
        if narration.strip():
            sentences = [s for s in lib._SENTENCE_SPLIT_RE.split(narration.strip()) if s.strip()]
            lo, hi = NARRATION_WORDS
            if len(sentences) != 1:
                add(advisory, "N14", "narration form", "Narration",
                    "is %d sentences; it should be one sentence of %d-%d words"
                    % (len(sentences), lo, hi))
            elif not lo <= _words(narration) <= hi:
                add(advisory, "N14", "narration form", "Narration",
                    "is %d words; it should be one sentence of %d-%d words"
                    % (_words(narration), lo, hi))
    return hard, advisory


def _repeat_words(lib, text, phrase_words):
    return {w.lower() for w in lib._WORD_RE.findall(text) if len(w) >= 3} - phrase_words


def repeat_advisories(ctx, lib, plan, writers_by_panel):
    """N13 for consecutive panels' action writer text (Motion, or Prompt in no_stills)."""
    label = "Prompt" if ctx.mode == "no_stills" else "Motion"
    phrase_words = set()
    for c in plan["cast"] if plan else []:
        phrase_words.update(w.lower() for w in c["phrase"].split())
    out = []
    for k in range(2, len(writers_by_panel) + 1):
        a = _repeat_words(lib, writers_by_panel[k - 2].get(label, ""), phrase_words)
        b = _repeat_words(lib, writers_by_panel[k - 1].get(label, ""), phrase_words)
        if a or b:
            similarity = len(a & b) / float(len(a | b))
            if similarity >= REPEAT_JACCARD:
                out.append("panel %d: N13 repeat: %s: repeats panel %d's action (similarity %.2f)"
                           % (k, label, k - 1, similarity))
    return out


def plan_copied_examples(plan):
    """N10 at plan scope: every descriptor, setting and action of the plan."""
    out = []
    texts = ([("%s's descriptor" % c["id"], c["descriptor"]) for c in plan["cast"]]
             + [("%s's setting" % l["id"], l["setting"]) for l in plan["locations"]]
             + [("beat %d's action" % k, b["action"]) for k, b in enumerate(plan["beats"], 1)])
    for where, text in texts:
        found = PLACEHOLDER_RE.search(text)
        copied = found.group(0) if found else next(
            (ex for ex in COPIED_EXAMPLES if _norm_text(ex) in _norm_text(text)), None)
        if copied:
            out.append("plan: N10 copied example: %s contains template text %s" % (where, _q(copied)))
    return out


GENERATION_CHECKS = ("N1", "N2", "N3", "N4", "N5", "N6", "N7", "N8", "N9", "N10", "N11", "N12",
                     "N14", "N15")


def panel_checks(ctx, plan, parts, text, story_md_path):
    """(hard, advisory) of an assembled story (RS15): plan-scope N10, then per panel N1-N11 and
    N15 (hard) and N12-N14 (advisory), then (shots) character_lib.shots_violations and
    shots_advisories. story_md_path holds text (written by the caller) and is parsed with
    bin/ltx-story-manifest's _parse_prompts_md."""
    lib = _character_lib(ctx.ws)
    undeclared = undeclared_characters(ctx)
    hard, advisory = plan_copied_examples(plan), []
    writers_by_panel = []
    for k in range(1, len(parts) + 1):
        fields = panel_fields(ctx, plan, parts, k)
        writers = {LABELS[key]: parts[k - 1].get(key, "") for key in writer_keys(ctx.mode, k)
                   if key != "title"}
        writers_by_panel.append(writers)
        h, a = _field_checks(ctx, lib, plan, k, parts[k - 1]["title"], fields, writers,
                             GENERATION_CHECKS, undeclared)
        hard += h
        advisory += a
    advisory = _order_by_panel(advisory + repeat_advisories(ctx, lib, plan, writers_by_panel))
    if ctx.mode == "shots":
        panels = _story_manifest(ctx.ws)._parse_prompts_md(story_md_path)[1]
        hard += lib.shots_violations(text, panels, ctx.panels, ctx.members)
        advisory += lib.shots_advisories(panels, ctx.members)
    return hard, advisory


def _order_by_panel(lines):
    """Panel advisories sorted by panel, then N12, N13, N14 (stable)."""
    order = {"N12": 0, "N13": 1, "N14": 2}
    return sorted(lines, key=lambda l: (int(l.split(":", 1)[0].split()[1]),
                                        order.get(l.split()[2], 3)))


def build_panel_prompt(ctx, plan, parts, k, fix=None, no_stills_rules=""):
    """The exact panel prompt of RS12 (plus the RS37 reserved line)."""
    beat = plan["beats"][k - 1]
    by_cast = {c["id"]: c for c in plan["cast"]}
    targets = writer_targets(ctx, plan, k)
    if ctx.mode == "no_stills":
        rules = "Rules:\n" + no_stills_rules + "\n\n" if no_stills_rules else ""
    elif ctx.mode == "shots":
        rules = SHOTS_PANEL_RULES
    else:
        rules = ""
    beat_lines = "\n".join((">> " if b["index"] == k else "   ")
                           + "%d. (%s) %s" % (b["index"], b["arc"], b["action"])
                           for b in plan["beats"])
    phrases = "; ".join('"%s"' % by_cast[c]["phrase"] for c in beat["cast"] if c in by_cast)
    undeclared = undeclared_characters(ctx)
    reserved = ("Characters who are not in this movie, never to be named: "
                + reserved_items(undeclared) + ".\n") if undeclared else ""
    previous = ""
    if ctx.mode == "chained" and k >= 2:
        previous = ("The previous panel's Motion: "
                    + dict(panel_fields(ctx, plan, parts, k - 1))["Motion"] + "\n")
    seed = SEED_PANEL if ctx.mode == "chained" and k == 1 and ctx.seed_agent_image else ""
    key_lines = []
    for key in writer_keys(ctx.mode, k):
        if key == "title" or key == "narration":
            line = KEY_LINE_TEMPLATES[key]
        elif ctx.mode == "chained":
            line = KEY_LINE_TEMPLATES["chained_image" if key == "image" else
                                      "chained_motion1" if k == 1 else "chained_motion"]
        else:
            line = KEY_LINE_TEMPLATES["%s_%s" % (ctx.mode, key)]
        if key in targets:
            line = line.replace("W1", str(targets[key][0]), 1).replace("W2", str(targets[key][1]), 1)
        key_lines.append(line)
    fix_block = ""
    if fix is not None:
        keys = writer_keys(ctx.mode, k)
        current = parts[k - 1] if k <= len(parts) and parts[k - 1] else {}
        fix_block = ("Your previous version of this panel was rejected. Problems:\n"
                     + "\n".join("- " + m for m in fix[:MAX_LISTED])
                     + "\nPrevious version:\n"
                     + "\n".join("%s: %s" % (key, current.get(key, "")) for key in keys)
                     + "\n\n")
    fragments = [
        ("@@GOAL_PARAGRAPH@@", _goal_paragraph(ctx.goal)),
        ("@@MODE_PARAGRAPH@@", MODE_PARAGRAPHS[ctx.mode]),
        ("@@PANEL_RULES@@", rules),
        ("@@BEAT_LINES@@", beat_lines),
        ("@@ACTION@@", beat["action"]),
        ("@@CAST_PHRASES@@", phrases or "nobody"),
        ("@@RESERVED@@", reserved),
        ("@@PREVIOUS@@", previous),
        ("@@SEED_PANEL@@", seed),
        ("@@KEY_LINES@@", "\n".join(key_lines)),
        ("@@FIX_BLOCK@@", fix_block),
    ]
    scalars = [("@@K@@", str(k)), ("@@PANELS@@", str(ctx.panels)),
               ("@@STORY_ID@@", ctx.story_id), ("@@SECONDS@@", ctx.seconds)]
    return _fill(PANEL_PROMPT_TEMPLATE, fragments, scalars, ctx.narrative)


def unparseable_panel_problem(mode, k):
    return ("the reply is not one JSON object with the keys %s"
            % ", ".join(writer_keys(mode, k)))


# ---------------------------------------------------------------------------
# The critic: prompt (RS17), routing (RS18) and reply validation (RS19)
# ---------------------------------------------------------------------------

CRITIC_PROMPT_TEMPLATE = (
    'You are the critic for a short narrated movie (story-id "@@STORY_ID@@"). You will not see '
    "any other context: everything you need is below. Check the draft against its plan and "
    "propose small, exact fixes.\n"
    "\n"
    "How this movie is made: @@MODE_PARAGRAPH@@\n"
    "\n"
    "Narrative to adapt:\n"
    "@@NARRATIVE@@\n"
    "\n"
    "@@GOAL_PARAGRAPH@@The plan (JSON):\n"
    "@@PLAN_JSON@@\n"
    "\n"
    "The draft story.md:\n"
    "@@STORY_MD@@\n"
    "\n"
    "Problems the pipeline's own checks found in this draft (fix the hard ones first):\n"
    "@@VIOLATIONS@@\n"
    "\n"
    "Score the draft from 1 (worst) to 10 (best) on each of:\n"
    "- continuity: characters, places, objects and positions stay consistent from panel to "
    "panel.\n"
    "- story: the panels tell the narrative@@GOAL_CLAUSE@@, with a clear introduction, climax "
    "and resolution, and every panel moves the action forward.\n"
    "- renderability: every panel shows one concrete physical action that a video model can "
    "render in @@SECONDS@@ seconds, with no dialogue, no on-screen text and nothing outside the "
    "frame.\n"
    "\n"
    "Then propose at most 8 patches, most important first. Each patch is an object with exactly "
    "the keys target, index, field, reason and replacement. The allowed patches are:\n"
    "@@FIELD_LINES@@\n"
    "A panel replacement holds only the text the writer writes: never include a character's "
    "description, a setting sentence, the shot type or a camera sentence, because the pipeline "
    "adds those itself. The number of panels, the characters' referring phrases and their "
    "descriptions never change.\n"
    "\n"
    "@@REPLY_PARAGRAPH@@")
CRITIC_REPLY_PARAGRAPH = (
    "Reply with one JSON object with exactly the keys scores, verdict and patches: scores is an "
    "object with the integer keys continuity, story and renderability; verdict is \"ok\" when "
    "the draft needs no patch and \"revise\" otherwise; patches is the list of patches (empty "
    "when the verdict is \"ok\"). Reply with the JSON object only, with no text before or after "
    "it. Do not call any tool: do NOT read any file, and do NOT run any tool to check it.")
JUDGE_REPLY_PARAGRAPH = "Call submit_review with your scores, verdict and patches."
CRITIC_RETRY_SUFFIX = ("\n\nYour previous reply was not one JSON object with the keys scores, "
                       "verdict and patches in the required form. Reply with that JSON object "
                       "only.")
ONLY1 = " (only 1: later panels continue the same picture)"


def listed(lines):
    """At most MAX_LISTED lines, then "- ... and N more"."""
    if len(lines) <= MAX_LISTED:
        return list(lines)
    return list(lines[:MAX_LISTED]) + ["- ... and %d more" % (len(lines) - MAX_LISTED)]


def critic_field_lines(mode, catalog_lines):
    lines = [
        '- target "plan", field "beat.action", index = the beat number: replacement is the beat\'s '
        "new action, one sentence of 6 to 40 words; the pipeline rewrites that panel from it.",
        '- target "plan", field "beat.shot", index = the beat number@@ONLY1@@: replacement is '
        "exactly one of: " + ", ".join(SHOT_TYPES) + ".",
        '- target "plan", field "beat.camera", index = the beat number@@ONLY1@@: replacement is '
        "exactly one of: " + ", ".join(CAMERA_KEYS) + ".",
        '- target "plan", field "location.setting", index = the place\'s position in the plan\'s '
        "locations list (1 is the first): replacement is its new setting sentence, 12 to 45 "
        'words starting "The setting is"; it replaces that sentence in every panel at that '
        "place."]
    if catalog_lines:
        lines.append('- target "plan", field "lora", index 0 for the global picks or a beat '
                     "number for that beat's own picks: replacement is the complete new list of "
                     "picks, each an object with the keys id and strength, from this catalog:"
                     + "\n" + "\n".join(catalog_lines))
    if mode in ("chained", "shots"):
        lines.append('- target "panel", field "image", index = the panel number@@ONLY1@@: '
                     "replacement is the new writer text of that panel's Image: field.")
        lines.append('- target "panel", field "motion", index = the panel number: replacement is '
                     "the new writer text of that panel's Motion: field.")
    else:
        lines.append('- target "panel", field "prompt", index = the panel number: replacement is '
                     "the new writer text of that panel's Prompt: field.")
    lines.append('- target "panel", field "narration", index = the panel number: replacement is '
                 "the panel's new narration sentence.")
    return "\n".join(lines)


def build_critic_prompt(plan, story_md_text, violations, catalog_lines=None, for_judge=False):
    """The exact critic prompt of RS17. violations is (hard, advisory) of the judged state;
    mode, panels, seconds, narrative, goal and story_id come from the plan."""
    hard, advisory = violations
    lines = listed(["- [hard] " + m for m in hard] + ["- [advisory] " + m for m in advisory])
    plan_json = json.dumps({k: plan[k] for k in ("title", "logline", "cast", "locations", "props",
                                                 "beats", "loras")}, indent=1, ensure_ascii=False)
    fragments = [
        ("@@GOAL_PARAGRAPH@@", _goal_paragraph(plan["goal"])),
        ("@@MODE_PARAGRAPH@@", MODE_PARAGRAPHS[plan["mode"]]),
        ("@@VIOLATIONS@@", "\n".join(lines) if lines else "- none"),
        ("@@GOAL_CLAUSE@@", " and serve the target output goal" if plan["goal"] else ""),
        ("@@FIELD_LINES@@", critic_field_lines(plan["mode"], catalog_lines)),
        ("@@ONLY1@@", ONLY1 if plan["mode"] == "chained" else ""),
        ("@@REPLY_PARAGRAPH@@", JUDGE_REPLY_PARAGRAPH if for_judge else CRITIC_REPLY_PARAGRAPH),
    ]
    text = CRITIC_PROMPT_TEMPLATE
    for token, value in fragments:
        text = text.replace(token, value)
    for token, value in (("@@STORY_ID@@", plan["story_id"]), ("@@SECONDS@@", plan["seconds"])):
        text = text.replace(token, value)
    text = text.replace("@@PLAN_JSON@@", plan_json).replace("@@STORY_MD@@", story_md_text)
    return text.replace("@@NARRATIVE@@", plan["narrative"])


def run_critic(ctx, prompt):
    """(status, answer, route) of one critic call (RS18): the fleet's analyst peers in order
    when this host does not serve analyst, else (and on every failure) a local one-shot
    bin/qwen-agent --skill=analyst."""
    fleet = _load_fleet(ctx.ws)
    if fleet is not None:
        try:
            url, _warning = fleet.daemon_url_from_env(os.environ)
            view, _warning = fleet.fetch_view(url)
            candidates = fleet.route_candidates("analyst", view) if view is not None else []
        except Exception:
            url, candidates = None, []
        if candidates and candidates != [fleet.LOCAL]:
            for host_id in candidates:
                try:
                    outcome, envelope, detail = fleet.delegate_once(url, "analyst", prompt, host_id)
                except Exception as e:
                    outcome, envelope, detail = "error", None, type(e).__name__
                answer = envelope.get("answer") if isinstance(envelope, dict) else None
                if (outcome == "ok" and isinstance(envelope, dict)
                        and envelope.get("status") == "ok"
                        and isinstance(answer, str) and answer.strip()):
                    return "ok", answer, "fleet:" + host_id
                print("Warning: critic on %s failed: %s %s" % (host_id, outcome, detail or ""))
    status, answer = run_agent(ctx, prompt, max_tokens=CRITIC_MAX_TOKENS, timeout=CRITIC_TIMEOUT,
                               skill="analyst", preflight_done=True)
    return status, answer, "local"


def _score(value):
    return isinstance(value, int) and not isinstance(value, bool) and 1 <= value <= 10


def parse_critic(answer):
    """The critic reply dict, or None unless it has integer scores 1-10 for continuity, story
    and renderability, a verdict of "ok" or "revise", and a patches list (RS19)."""
    obj = extract_json(answer)
    if obj is None:
        return None
    scores = obj.get("scores")
    if not isinstance(scores, dict) or not all(_score(scores.get(k)) for k in SCORE_KEYS):
        return None
    if obj.get("verdict") not in ("ok", "revise") or not isinstance(obj.get("patches"), list):
        return None
    return {"scores": {k: scores[k] for k in SCORE_KEYS}, "verdict": obj["verdict"],
            "patches": obj["patches"]}


# ---------------------------------------------------------------------------
# Patches: the per-mode whitelist and application (RS20)
# ---------------------------------------------------------------------------

PATCH_KEYS = ("target", "index", "field", "reason", "replacement")


def lora_patches_allowed(ctx):
    """lora patches need auto LoRA and at least one compatible video catalog entry."""
    return ctx.auto_lora and any(e["target"] == "video" for e in compatible_entries(ctx))


def patch_ranges(ctx, plan, lora_allowed):
    """{(target, field): (lo, hi) | None} -- None means "field not allowed in this mode"."""
    n, mode = ctx.panels, ctx.mode
    first_only = (1, 1) if mode == "chained" else (1, n)
    return {("plan", "beat.action"): (1, n),
            ("plan", "beat.shot"): first_only,
            ("plan", "beat.camera"): first_only,
            ("plan", "location.setting"): (1, len(plan["locations"])),
            ("plan", "lora"): (0, n) if lora_allowed else None,
            ("panel", "image"): first_only if mode != "no_stills" else None,
            ("panel", "motion"): (1, n) if mode != "no_stills" else None,
            ("panel", "prompt"): (1, n) if mode == "no_stills" else None,
            ("panel", "narration"): (1, n)}


def _patch_problem(ranges, patch):
    if not isinstance(patch, dict) or not all(k in patch for k in PATCH_KEYS):
        return "not an object with the keys target, index, field, reason and replacement"
    key = (patch["target"], patch["field"])
    if not all(isinstance(v, str) for v in key) or key not in ranges:
        return "unknown target or field"
    span = ranges[key]
    if span is None:
        return "field not allowed in this mode"
    index = patch["index"]
    if not isinstance(index, int) or isinstance(index, bool):
        return "index is not an integer"
    if not span[0] <= index <= span[1]:
        allowed = "%d only" % span[0] if span[0] == span[1] else "%d to %d" % span
        return "index %d is out of range for %s (allowed: %s)" % (index, patch["field"], allowed)
    if patch["field"] == "lora":
        if not isinstance(patch["replacement"], list):
            return "replacement must be a list of picks"
    elif not isinstance(patch["replacement"], str):
        return "replacement must be a string"
    return None


def apply_patches(ctx, state, patches, regen=None, lora_allowed=None):
    """(new_state, applied, rejected, regenerate) for a state {"plan", "parts"} and a patch
    list (RS20). Works on a deep copy. regen(k, plan, parts) -> ("ok", parts_k) | ("failed",
    None) | ("budget", None) | ("time", None) regenerates panel k after a beat.action patch;
    without regen the panel keeps its parts. rejected items are {"patch", "reason"}."""
    new = copy.deepcopy(state)
    plan, parts = new["plan"], new["parts"]
    lib = _character_lib(ctx.ws)
    if lora_allowed is None:
        lora_allowed = lora_patches_allowed(ctx)
    ranges = patch_ranges(ctx, plan, lora_allowed)
    applied, rejected, regenerate = [], [], []
    accepted, seen = [], set()
    patches = patches if isinstance(patches, list) else []
    for i, patch in enumerate(patches):
        if i >= MAX_PATCHES:
            rejected.append({"patch": patch, "reason": "over the 8-patch limit"})
            continue
        problem = _patch_problem(ranges, patch)
        if problem is None:
            key = (patch["target"], patch["index"], patch["field"])
            if key in seen:
                problem = "duplicate patch target"
            seen.add(key)
        if problem:
            rejected.append({"patch": patch, "reason": problem})
        else:
            accepted.append(patch)
    compatible_by_id = {e["id"]: e for e in compatible_entries(ctx)}
    catalog_by_id = {e["id"]: e for e in ctx.catalog.get("entries", [])}
    for patch in accepted:
        if patch["target"] != "plan":
            continue
        field, index = patch["field"], patch["index"]
        if field == "beat.action":
            action = clean_writer(lib, patch["replacement"])
            words = _words(action)
            if not 6 <= words <= 40:
                rejected.append({"patch": patch, "reason": "the new action is %d words; it must "
                                                           "be 6 to 40" % words})
                continue
            plan["beats"][index - 1]["action"] = action
            regenerate.append(index)
        elif field in ("beat.shot", "beat.camera"):
            value = _collapse(patch["replacement"]).lower()
            allowed = SHOT_TYPES if field == "beat.shot" else CAMERA_KEYS
            if value not in allowed:
                rejected.append({"patch": patch, "reason": "%s is not one of: %s"
                                 % (_q(value), ", ".join(allowed))})
                continue
            plan["beats"][index - 1][field.split(".")[1]] = value
        elif field == "location.setting":
            setting = _collapse(patch["replacement"])
            if setting and not setting.endswith((".", "!", "?")):
                setting += "."
            problems = _setting_problems(setting)
            if problems:
                rejected.append({"patch": patch, "reason": "the new setting " + problems[0]})
                continue
            plan["locations"][index - 1]["setting"] = setting
        else:
            before = lora_checks(ctx, plan, compatible_by_id, catalog_by_id)[0]
            saved = copy.deepcopy(plan["loras"])
            if index == 0:
                plan["loras"]["global"] = patch["replacement"]
            elif patch["replacement"]:
                plan["loras"]["per_beat"][str(index)] = patch["replacement"]
            else:
                plan["loras"]["per_beat"].pop(str(index), None)
            broken = [h for h in lora_checks(ctx, plan, compatible_by_id, catalog_by_id)[0]
                      if h not in before]
            if broken:
                plan["loras"] = saved
                rejected.append({"patch": patch, "reason": "would break " + broken[0]})
                continue
        applied.append(patch)
    regenerate = sorted(set(regenerate))
    for k in regenerate:
        if regen is None:
            continue
        outcome, new_parts = regen(k, plan, parts)
        if outcome == "ok":
            parts[k - 1] = new_parts
        elif outcome in ("budget", "time"):
            action_patch = [p for p in accepted if p["field"] == "beat.action"
                            and p["index"] == k][0]
            rejected.append({"patch": action_patch, "reason": "panel %d regeneration skipped: %s"
                             % (k, "call budget exhausted" if outcome == "budget"
                                else "wall-clock cap reached")})
    for patch in accepted:
        if patch["target"] != "panel":
            continue
        k, field = patch["index"], patch["field"]
        if k in regenerate:
            rejected.append({"patch": patch,
                             "reason": "panel regenerated from a beat.action patch this round"})
            continue
        text = clean_writer(lib, patch["replacement"],
                            pasted_pieces(ctx, plan, k).get(field, ()))
        if not text:
            rejected.append({"patch": patch, "reason": "empty after cleanup"})
            continue
        parts[k - 1][field] = text
        applied.append(patch)
    return new, applied, rejected, regenerate


# ---------------------------------------------------------------------------
# The run: plan calls (RS8), panel calls (RS13), the round controller (RS21), ranking (RS22),
# budgets and the wall clock (RS23), outputs (RS25-RS27)
# ---------------------------------------------------------------------------

WRITER_CHECK_IDS = ("N1", "N2", "N3", "N4", "N7", "N8", "N9", "N10", "N11", "S4", "S5", "S7",
                    "S8", "S10", "S11")


def _unused_dir(path):
    """bin/ltx-movie's _unused_path for a directory path (no extension)."""
    candidate, k = path, 2
    while os.path.lexists(candidate):
        candidate = "%s-%d" % (path, k)
        k += 1
    return candidate


def _reply_text(status, answer):
    return answer if answer is not None else "<no answer: %s>" % status


def _scores_of(states, i):
    """The scores of states[i], else of its nearest scored ancestor, else None (RS22)."""
    for j in range(i, -1, -1):
        if states[j]["scores"]:
            return states[j]["scores"]
    return None


def _key(states, i):
    scores = _scores_of(states, i)
    low = min(scores.values()) if scores else 0
    total = sum(scores.values()) if scores else 0
    return (len(states[i]["hard"]), -low, -total)


def better(states, a, b):
    """True when states[a] is strictly better than states[b] (RS21)."""
    return _key(states, a) < _key(states, b)


def best_round(states):
    """The index of the state with the smallest (hard, -min, -total, -round) (RS22)."""
    return min(range(len(states)), key=lambda i: _key(states, i) + (-i,))


def _checks_doc(ctx, state, source="robust"):
    return {"schema": CHECKS_SCHEMA, "story_id": ctx.story_id, "mode": ctx.mode,
            "panels": ctx.panels, "checked_at": _utc(), "source": source,
            "round": state["round"] if source == "robust" else None,
            "hard": [parse_violation(m) for m in state["hard"]],
            "advisory": [parse_violation(m) for m in state["advisory"]],
            "scores": state.get("scores"), "verdict": state.get("verdict"), "stop_reason": None,
            "rounds": [], "best_round": None, "judge": None}


class _Run(object):
    """One robust Phase 1 run: budgets, files, run.json and the states of every round."""

    def __init__(self, ctx, no_stills_rules):
        self.ctx = ctx
        self.rules = no_stills_rules
        self.start = _now()
        self.cap = wall_clock_cap(ctx.panels)
        self.rounds_dir = os.path.join(ctx.story_dir, "story_rounds")
        self.agent_calls = 0
        self.panel_calls = dict((k, 0) for k in range(1, ctx.panels + 1))
        self.time_up = False
        self.shape = []
        self.states = []
        self.doc = {"schema": RUN_SCHEMA, "story_id": ctx.story_id, "mode": ctx.mode,
                    "panels": ctx.panels, "started_at": _utc(), "finished_at": None,
                    "budgets": {"plan_calls": PLAN_MAX_CALLS, "panel_calls": PANEL_MAX_CALLS,
                                "critic_rounds": CRITIC_MAX_ROUNDS,
                                "critic_calls_per_round": CRITIC_CALLS_PER_ROUND,
                                "max_patches": MAX_PATCHES, "wall_clock_s": self.cap},
                    "calls": [], "stop_reason": None, "best_round": None, "exit": None}
        compatible = compatible_entries(ctx)
        self.compatible_by_id = dict((e["id"], e) for e in compatible)
        self.catalog_by_id = dict((e["id"], e) for e in ctx.catalog.get("entries", []))
        self.catalog_lines = ([catalog_line(e) for e in compatible if e["target"] == "video"]
                              if lora_patches_allowed(ctx) else None)
        self.compatible = compatible

    def expired(self):
        return _now() - self.start >= self.cap

    def round_dir(self, r):
        path = os.path.join(self.rounds_dir, "round_%d" % r)
        os.makedirs(path, exist_ok=True)
        return path

    def write_run(self):
        _write_json(os.path.join(self.rounds_dir, "run.json"), self.doc)

    def record(self, stage, panel, rnd, attempt, route, status, started):
        self.doc["calls"].append({"stage": stage, "panel": panel, "round": rnd,
                                  "attempt": attempt, "route": route, "status": status,
                                  "seconds": round(_now() - started, 1)})
        self.write_run()

    def agent(self, prompt, max_tokens, timeout, image=None):
        preflight = self.agent_calls > 0
        self.agent_calls += 1
        return run_agent(self.ctx, prompt, max_tokens=max_tokens, timeout=timeout, image=image,
                         preflight_done=preflight)

    def round0_timeout(self):
        print("Error: story generation exceeded the wall-clock cap of %ds before every panel was "
              "written; partial work is kept in %s" % (self.cap, self.round_dir(0)),
              file=sys.stderr)
        return self.finish(1)

    def finish(self, code):
        self.doc["finished_at"] = _utc()
        self.doc["exit"] = code
        self.write_run()
        return code

    # -- plan ------------------------------------------------------------------------------

    def plan_round(self):
        ctx = self.ctx
        rdir = self.round_dir(0)
        prompt = build_plan_prompt(ctx, self.compatible, ctx.pinned)
        _write_text(os.path.join(rdir, "plan_prompt.txt"), prompt)
        text, found, problems = prompt, None, []
        for attempt in range(1, PLAN_MAX_CALLS + 1):
            if self.expired():
                return None, "timeout"
            print("plan: call %d of %d" % (attempt, PLAN_MAX_CALLS))
            started = _now()
            status, answer = self.agent(text, plan_max_tokens(ctx.panels),
                                        plan_timeout(ctx.panels), image=ctx.seed_agent_image)
            self.record("plan", None, 0, attempt, None, status, started)
            _write_text(os.path.join(rdir, "plan_reply_%d.txt" % attempt),
                        _reply_text(status, answer))
            raw = extract_json(answer)
            if raw is None:
                problems = ["the reply is not one JSON object"]
            else:
                plan, shape = normalize_plan(ctx, raw)
                hard = (plan_checks(ctx, plan, shape)[0]
                        + lora_checks(ctx, plan, self.compatible_by_id, self.catalog_by_id)[0])
                found = (plan, shape, hard)
                problems = hard
            if not problems:
                break
            text = (prompt + "\n\nYOUR PREVIOUS REPLY WAS REJECTED. Problems:\n"
                    + "\n".join(listed(["- " + m for m in problems]))
                    + "\nPrevious reply:\n"
                    + (answer[:20000] if answer is not None else "<no answer: %s>" % status)
                    + "\n\nReply with the complete corrected JSON object only.")
        return found, None

    # -- panels ----------------------------------------------------------------------------

    def panel_call(self, plan, parts, k, rnd, fix):
        """(valid parts or None) after one panel call; the caller checks the budget."""
        ctx = self.ctx
        self.panel_calls[k] += 1
        n = self.panel_calls[k]
        print("panel %d/%d: call %d" % (k, ctx.panels, n))
        rdir = self.round_dir(rnd)
        prompt = build_panel_prompt(ctx, plan, parts, k, fix=fix, no_stills_rules=self.rules)
        _write_text(os.path.join(rdir, "panel_%02d_prompt_%d.txt" % (k, n)), prompt)
        started = _now()
        image = ctx.seed_agent_image if ctx.mode == "chained" and k == 1 else None
        status, answer = self.agent(prompt, PANEL_MAX_TOKENS, PANEL_TIMEOUT, image=image)
        self.record("panel", k, rnd, n, None, status, started)
        _write_text(os.path.join(rdir, "panel_%02d_reply_%d.txt" % (k, n)),
                    _reply_text(status, answer))
        return parse_panel_reply(ctx, plan, k, answer)

    def regenerate(self, state, k, plan, parts, rnd):
        """("ok", parts_k) | ("failed", None) | ("budget", None) | ("time", None)."""
        if self.panel_calls[k] >= PANEL_MAX_CALLS:
            return "budget", None
        if self.expired():
            self.time_up = True
            return "time", None
        fix = [m for m in state["hard"] + state["advisory"]
               if parse_violation(m)["index"] == k
               and parse_violation(m)["scope"] in ("panel", "beat")]
        if not fix:
            fix = ["this panel's beat was revised; rewrite the panel for the new beat"]
        new = self.panel_call(plan, parts, k, rnd, fix)
        return ("ok", new) if new is not None else ("failed", None)

    # -- states ----------------------------------------------------------------------------

    def make_state(self, rnd, plan, parts):
        ctx = self.ctx
        rdir = self.round_dir(rnd)
        text = assemble(ctx, plan, parts)
        story_md = os.path.join(rdir, "story.md")
        _write_text(story_md, text)
        ph, pa = plan_checks(ctx, plan, self.shape)
        lh, la = lora_checks(ctx, plan, self.compatible_by_id, self.catalog_by_id)
        nh, na = panel_checks(ctx, plan, parts, text, story_md)
        state = {"round": rnd, "plan": plan, "parts": parts, "text": text, "hard": ph + lh + nh,
                 "advisory": pa + la + na, "scores": None, "verdict": None, "dir": rdir}
        _write_json(os.path.join(rdir, "plan.json"), plan)
        _write_json(os.path.join(rdir, "parts.json"), {"panels": [
            dict([("index", k)] + [(key, p.get(key, "")) for key in writer_keys(ctx.mode, k)])
            for k, p in enumerate(parts, start=1)]})
        _write_json(os.path.join(rdir, "story_checks.json"), _checks_doc(ctx, state))
        print("round %d: %d hard, %d advisory" % (rnd, len(state["hard"]), len(state["advisory"])))
        self.states.append(state)
        return state

    # -- critic rounds ---------------------------------------------------------------------

    def critic_round(self, k, judged, passed_only=False):
        """One RS21 iteration on states[judged]. Returns a stop reason or None (a new state was
        appended)."""
        ctx = self.ctx
        prev = self.states[judged]
        rdir = os.path.join(self.rounds_dir, "round_%d" % k)
        base = build_critic_prompt(prev["plan"], prev["text"], (prev["hard"], prev["advisory"]),
                                   self.catalog_lines)
        prompt, reply, route, calls = base, None, None, 0
        for attempt in range(1, CRITIC_CALLS_PER_ROUND + 1):
            if self.expired():
                if calls == 0:
                    return "time_cap"
                break
            calls += 1
            self.round_dir(k)
            _write_text(os.path.join(rdir, "critic_prompt_%d.txt" % attempt), prompt)
            started = _now()
            self.agent_calls += 1
            status, answer, route = run_critic(ctx, prompt)
            self.record("critic", None, k, attempt, route, status, started)
            _write_text(os.path.join(rdir, "critic_reply_%d.txt" % attempt),
                        _reply_text(status, answer))
            reply = parse_critic(answer)
            if reply is not None:
                break
            prompt = base + CRITIC_RETRY_SUFFIX
        critic = {"route": route, "calls": calls, "reply": reply, "applied": [], "rejected": []}
        critic_path = os.path.join(rdir, "critic.json")
        if reply is not None:
            prev["scores"], prev["verdict"] = reply["scores"], reply["verdict"]
            scores = reply["scores"]

            def line(applied, rejected):
                print("critic round %d (%s): continuity=%d story=%d renderability=%d verdict=%s; "
                      "%d patch(es): %d applied, %d rejected"
                      % (k, route, scores["continuity"], scores["story"],
                         scores["renderability"], reply["verdict"], len(reply["patches"]),
                         applied, rejected))

            if (not prev["hard"] and reply["verdict"] == "ok"
                    and min(scores.values()) >= MIN_OK_SCORE):
                _write_json(critic_path, critic)
                line(0, 0)
                return "passed"
            if not passed_only and judged >= 1 and not better(self.states, judged, judged - 1):
                _write_json(critic_path, critic)
                line(0, 0)
                return "plateau"
            new, applied, rejected, _regen = apply_patches(
                ctx, {"plan": prev["plan"], "parts": prev["parts"]}, reply["patches"],
                regen=lambda kk, plan, parts: self.regenerate(prev, kk, plan, parts, k))
            critic["applied"], critic["rejected"] = applied, rejected
            _write_json(critic_path, critic)
            line(len(applied), len(rejected))
            self.make_state(k, new["plan"], new["parts"])
            return None
        print("critic round %d: no valid reply after %d call(s); code-only round" % (k, calls))
        _write_json(critic_path, critic)
        if (not passed_only and judged >= 1
                and len(prev["hard"]) >= len(self.states[judged - 1]["hard"])):
            return "plateau"
        parts = copy.deepcopy(prev["parts"])
        plan = copy.deepcopy(prev["plan"])
        for kk in range(1, ctx.panels + 1):
            mine = [m for m in prev["hard"] if parse_violation(m)["scope"] == "panel"
                    and parse_violation(m)["index"] == kk
                    and parse_violation(m)["id"] in WRITER_CHECK_IDS]
            if not mine or self.panel_calls[kk] >= PANEL_MAX_CALLS:
                continue
            if self.expired():
                self.time_up = True
                break
            new = self.panel_call(plan, parts, kk, k, mine)
            if new is not None:
                parts[kk - 1] = new
        self.make_state(k, plan, parts)
        return None

    # -- judge -----------------------------------------------------------------------------

    def judge_gate(self):
        ctx = self.ctx
        best = self.states[best_round(self.states)]
        if best["hard"]:
            return {"status": "skipped", "detail": "best round has hard violations",
                    "scores": None, "min_score": None, "applied": False}
        if self.expired():
            return {"status": "skipped", "detail": "wall-clock cap reached", "scores": None,
                    "min_score": None, "applied": False}
        started = _now()
        status, detail, reply = run_judge(ctx, best["dir"])
        self.record("judge", None, best["round"], 1, None, status, started)
        if status != "ok":
            print("Warning: judge-story failed (%s); keeping the critic's best round" % detail)
            return {"status": "error", "detail": detail, "scores": None, "min_score": None,
                    "applied": False}
        low = min(reply["scores"].values())
        judge = {"status": "ok", "detail": "min score %d" % low, "scores": reply["scores"],
                 "min_score": low, "applied": False}
        if low >= JUDGE_MIN_SCORE:
            return judge
        j = len(self.states)
        rdir = self.round_dir(j)
        new, applied, rejected, _regen = apply_patches(
            ctx, {"plan": best["plan"], "parts": best["parts"]}, reply["patches"],
            regen=lambda kk, plan, parts: self.regenerate(best, kk, plan, parts, j),
            lora_allowed=False)
        _write_json(os.path.join(rdir, "judgment.patches.json"), reply)
        _write_json(os.path.join(rdir, "critic.json"), {
            "route": None, "calls": 0, "reply": reply, "applied": applied, "rejected": rejected})
        self.make_state(j, new["plan"], new["parts"])
        if not self.expired():
            self.critic_round(j + 1, j, passed_only=True)
        judge["applied"] = True
        return judge

    # -- the whole run ---------------------------------------------------------------------

    def go(self):
        ctx = self.ctx
        if os.path.lexists(self.rounds_dir):
            os.replace(self.rounds_dir, _unused_dir(os.path.join(
                ctx.story_dir, "story_rounds-%s-%d"
                % (time.strftime("%Y%m%dT%H%M%SZ", time.gmtime()), os.getpid()))))
        self.round_dir(0)
        self.write_run()
        for warning in catalog_warnings(ctx):
            print(warning)
        found, why = self.plan_round()
        if why == "timeout":
            return self.round0_timeout()
        fatal = ([h for h in found[2] if parse_violation(h)["id"] in ("P1", "P2")]
                 if found else ["the reply is not one JSON object"])
        if fatal:
            calls = len([c for c in self.doc["calls"] if c["stage"] == "plan"])
            print("Error: the story model did not return a usable plan after %d call(s)" % calls,
                  file=sys.stderr)
            for message in fatal:
                print("  - %s" % message, file=sys.stderr)
            print("Raw replies are kept in %s. Rerun the same command to try again."
                  % self.round_dir(0), file=sys.stderr)
            return self.finish(1)
        plan, self.shape, _hard = found
        parts = [empty_parts(ctx.mode, k, plan) for k in range(1, ctx.panels + 1)]
        valid = 0
        for k in range(1, ctx.panels + 1):
            if self.expired():
                return self.round0_timeout()
            new = self.panel_call(plan, parts, k, 0, None)
            if new is None and self.panel_calls[k] < PANEL_MAX_CALLS:
                if self.expired():
                    return self.round0_timeout()
                new = self.panel_call(plan, parts, k, 0,
                                      [unparseable_panel_problem(ctx.mode, k)])
            if new is not None:
                parts[k - 1] = new
                valid += 1
        if not valid:
            print("Error: the story model returned no valid panel in round 0; see %s"
                  % self.round_dir(0), file=sys.stderr)
            return self.finish(1)
        self.make_state(0, plan, parts)
        stop = None
        for k in range(1, CRITIC_MAX_ROUNDS + 1):
            if self.expired():
                stop = "time_cap"
                break
            stop = self.critic_round(k, k - 1)
            if stop:
                break
            if self.time_up:
                stop = "time_cap"
                break
            if k == CRITIC_MAX_ROUNDS:
                stop = "max_rounds"
        judge = self.judge_gate() if ctx.judge else None
        best = best_round(self.states)
        state = self.states[best]
        print("stop: %s; best round %d (%d hard)" % (stop, best, len(state["hard"])))
        doc = _checks_doc(ctx, state)
        doc.update({"stop_reason": stop, "best_round": best, "judge": judge,
                    "rounds": [{"round": s["round"], "hard": len(s["hard"]),
                                "advisory": len(s["advisory"]), "scores": s["scores"],
                                "verdict": s["verdict"]} for s in self.states]})
        _write_json(os.path.join(ctx.story_dir, "plan.json"), state["plan"])
        _write_json(os.path.join(ctx.story_dir, "story_checks.json"), doc)
        _write_text(os.path.join(ctx.story_dir, "story.md"), state["text"])
        self.doc["stop_reason"], self.doc["best_round"] = stop, best
        self.advisories = state["advisory"]
        if not state["hard"]:
            return self.finish(0)
        print("Error: story.md has %d hard violation(s) after the critic rounds (best round %d of "
              "%d):" % (len(state["hard"]), best, len(self.states) - 1), file=sys.stderr)
        for message in state["hard"]:
            print("  - %s" % message, file=sys.stderr)
        print("story.md, plan.json and story_checks.json are saved in %s. Hand-edit story.md to "
              "fix the violations above and rerun: story.md already exists, so Phase 1 re-checks "
              "it instead of regenerating it (pass --force-story to regenerate)." % ctx.story_dir,
              file=sys.stderr)
        return self.finish(2)


def run(ctx, no_stills_rules=""):
    """Generate story.md with the robust engine. Returns (exit code, advisories)."""
    runner = _Run(ctx, no_stills_rules)
    runner.advisories = []
    code = runner.go()
    return code, runner.advisories


def run_judge(ctx, round_dir):
    """("ok", "", reply) or ("error", detail, None) for bin/judge-story --patches on
    <round_dir>/story.md (RS24); reply is {"scores", "verdict", "patches"}."""
    cmd = ([sys.executable, os.path.join(ctx.ws, "bin", "judge-story"),
            "--story-md", os.path.join(round_dir, "story.md"), "--patches"]
           + (["--goal", ctx.goal] if ctx.goal else []))
    try:
        proc = subprocess.run(cmd, cwd=ctx.ws, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                              stderr=subprocess.STDOUT, text=True, timeout=JUDGE_TIMEOUT)
    except subprocess.TimeoutExpired:
        return "error", "timeout", None
    if proc.returncode != 0:
        return "error", "exit %d" % proc.returncode, None
    try:
        with open(os.path.join(round_dir, "judgment.patches.json"), encoding="utf-8") as f:
            data = json.load(f)
        reply = {"scores": {k: data["scores"][k] for k in SCORE_KEYS},
                 "verdict": data["verdict"], "patches": data["patches"]}
        if not all(_score(v) for v in reply["scores"].values()) or not isinstance(
                reply["patches"], list):
            raise ValueError("invalid judgment.patches.json")
    except Exception as e:
        return "error", " ".join(str(e).split()) or type(e).__name__, None
    return "ok", "", reply
