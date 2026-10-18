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


def undeclared_references(lib, text, undeclared, exact_phrase=False):
    """[(name, kind, matched text)] for each undeclared character text refers to, first kind
    per character in the RS37 order: referring phrase, trigger, name. exact_phrase compares a
    cast entry's phrase by case-insensitive equality instead of occurrence."""
    hits = []
    for name, trigger, phrase in undeclared:
        hit = None
        if exact_phrase:
            if text.strip().lower() == phrase.strip().lower():
                hit = "referring phrase", text
        else:
            try:
                match = lib._phrase_regex(lib.normalize_phrase(phrase)).search(text)
            except lib.CharacterError:
                match = None
            if match:
                hit = "referring phrase", match.group(0)
        for kind, word in (("trigger", trigger), ("name", name)):
            if hit is None:
                match = _word_match(word, text)
                if match:
                    hit = kind, match.group(0)
        if hit:
            hits.append((name, hit[0], hit[1]))
    return hits


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
            for hit in undeclared_references(lib, text, undeclared, exact_phrase=exact):
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
