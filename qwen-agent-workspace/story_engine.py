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
# --speech-only: characters speak on screen, so a framed beat stays medium to close-up.
SPEECH_SHOT_TYPES = ("medium shot", "medium close-up", "close-up")
SPEECH_SHOT_NOTE = (" (characters speak on screen in this movie, so only these framings keep "
                    "the speaker's lips readable)")
SPEECH_FRAMING_SENTENCE = (" Characters speak on screen in this movie: keep each character within "
                           "medium to close-up range of the camera while they speak, and never "
                           "have a character shrink into the distance or leave the frame before "
                           "their line ends.")


def shot_types(narration):
    return SPEECH_SHOT_TYPES if narration == "speech" else SHOT_TYPES
CAMERA_SENTENCES = (
    ("static", "The camera stays static."),
    ("slow push-in", "The camera pushes in."),
    ("slow pull-back", "The camera pulls back."),
    ("slow pan left", "The camera pans left."),
    ("slow pan right", "The camera pans right."),
    ("slow tilt up", "The camera tilts up."),
    ("slow tilt down", "The camera tilts down."),
    ("tracking", "The camera tracks alongside the movement."),
)
CAMERA_KEYS = tuple(key for key, _ in CAMERA_SENTENCES)
ARC_ROLES = ("introduction", "rising", "climax", "falling", "resolution")
WORD_RANGES = {"chained": {"image1": (120, 170), "motion1": (15, 35), "motion": (15, 35)},
               "no_stills": {"prompt": (150, 220)},
               "shots": {"image": (80, 170), "motion": (10, 25)}}
NARRATION_WORDS = (3, 30)
MIN_WRITER_WORDS = {"image": 20, "prompt": 20, "motion": 5}
# Word counts are advisory: a count is flagged only when it is more than this fraction outside
# its range (the writer prompts still ask for the exact range).
WORD_TOLERANCE = 0.25
MAX_CAST = {"chained": 4, "no_stills": 4, "shots": 2}
PLAN_MAX_CALLS = 2
PANEL_MAX_CALLS = 2
CRITIC_MAX_ROUNDS = 2
CRITIC_CALLS_PER_ROUND = 2
MAX_PATCHES = 8
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
    "auto_lora", "catalog", "pinned", "stills_pinned", "judge", "narration", "clip_seconds"],
    defaults=(True, None))
# narration True: Narration: is voice-over or a character's spoken line. "speech"
# (bin/ltx-movie --speech-only): Narration: is optional and, when present, a character's spoken
# line. False (--no-narration): panels have no Narration: field and no narration check runs.
# clip_seconds: the exact clip length (frames / fps) the timing rules use; None means
# float(seconds) (docs/superpowers/specs/2026-10-24-on-camera-dialogue-design.md 2.4).


def engine_seconds(ctx):
    """The clip length in seconds that the timing rules use (dialogue spec 2.4)."""
    return ctx.clip_seconds if ctx.clip_seconds is not None else float(ctx.seconds)

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


def _report_no_answer(status, err):
    """A Warning (stdout, like the other Warning: lines) with the last lines of bin/qwen-agent's
    stderr when a call gave no answer, so the reason (a server that is down, a refused
    preflight) is not lost."""
    tail = [line for line in (err or "").splitlines() if line.strip()][-10:]
    if tail:
        print("Warning: bin/qwen-agent gave no answer (%s); the last lines of its stderr:\n%s"
              % (status, "\n".join("  " + line for line in tail)))


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
        out, err = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        _out, err = proc.communicate()
        _report_no_answer("timeout", err)
        return "timeout", None
    lines = [line for line in (out or "").splitlines() if line.strip()]
    try:
        envelope = json.loads(lines[-1])
    except (IndexError, ValueError):
        _report_no_answer("no_envelope", err)
        return "no_envelope", None
    if not isinstance(envelope, dict) or envelope.get("schema") != ONESHOT_SCHEMA:
        _report_no_answer("no_envelope", err)
        return "no_envelope", None
    answer = envelope.get("answer")
    if not isinstance(answer, str) or not answer.strip():
        answer = None
        _report_no_answer(str(envelope.get("status")), err)
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
    "cast: a list with one object per individual character who acts or speaks on screen, with "
    "the keys id, phrase and descriptor; a group of people (a crowd, an audience, fans, "
    "spectators, a team) is never a cast entry, and belongs in the setting sentence of its "
    "place. id is c1, c2, c3 and so on, in order. phrase is the character's referring "
    "phrase: at most four words, built only from details in their descriptor or stated by the "
    "narrative; the movie names them by this exact phrase everywhere. descriptor is their full "
    'visual description in 8 to 60 words that starts with "a " or "an " and does not end with a '
    "full stop: apparent age group, build, skin tone, hair colour, length and style, clothing and "
    "accessories.@@CAST_FIXED@@\n"
    "locations: a list with one object per place, with the keys id and setting. id is l1, l2 and "
    'so on. setting is one sentence of 12 to 45 words that starts with "The setting is" and names '
    "the period, the place, the ground, the light and any crowd or other group of people in the "
    "background.\n"
    "props: a list with one object per object that matters to the story, with the keys id and "
    "name. id is p1, p2 and so on; name is a short noun phrase for the object. Use an empty list "
    "when no object matters.\n"
    "beats: a list of EXACTLY @@PANELS@@ objects, one per panel in order, with the keys index, "
    "arc, action, shot, camera, location, @@BEAT_KEYS@@. index runs from 1 to @@PANELS@@. arc "
    "is one of "
    "introduction, rising, climax, falling, resolution, in story order; @@ARC_RULE@@ action is "
    "one sentence of 6 to 40 words saying what the characters physically do during these "
    "@@SECONDS@@ seconds: one continuous physical action that a camera can film, not a sequence "
    "of steps, with no on-screen text. shot is exactly one of: @@SHOT_LIST@@. "
    "camera is exactly one of: @@CAMERA_LIST@@. location is the id of the place where the beat "
    "happens. cast is the list of ids of the characters on screen in the beat, at most "
    "@@MAX_CAST@@.@@SPEAKER_RULE@@@@LINES_RULE@@\n"
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
SPEAKER_RULE = (" speaker is the id of the one character who says something aloud on screen "
                "during the beat, or an empty string when nobody speaks; give a speaker only where "
                "a spoken line moves the story. A beat with a speaker shows only that character "
                "(its cast is just their id), facing the camera, in a medium shot, medium close-up "
                "or close-up; the speaker may move during the beat, and the camera may stay static, "
                "push in, pull back or track them, as long as their face stays in frame and lit "
                "while they speak.")
SILENT_SPEAKER_RULE = " speaker is always an empty string: nobody speaks in this movie."
# Narrative dialogue fidelity spec 7.1 (e): only when the narrative quotes spoken lines.
LINES_RULE = (" lines is the list of the numbers of the spoken lines above that the speaker says "
              "aloud during the beat, in order, or an empty list. Every spoken line belongs to "
              "exactly one beat, in the narrative's order: give each line to the beat whose action "
              "surrounds it in the narrative, and give a speaker to every beat with lines and to no "
              "other beat. A beat may hold two or more consecutive lines only when together they "
              "are at most @@LINE_WORDS@@ words. Give each line its own beat whenever there are at "
              "least as many beats as lines.")
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


# Narrative dialogue fidelity (docs/superpowers/specs/2026-10-26-narrative-dialogue-fidelity-
# design.md QL1, GC1): the narrative's quoted spoken lines are required on-camera dialogue (Q1),
# and a group of people is setting, never cast.
QUOTE_RE = re.compile(r'"([^"]*)"')
_LINE_WORD_RE = re.compile(r"[^\W_]+(?:'[^\W_]+)*")
_CLAUSE_BREAK_RE = re.compile(r"[.!?;,]")
_QUOTE_EDGE_CHARS = " \t\n,:;—–-"
BEFORE_WINDOW_WORDS = 6
AFTER_WINDOW_WORDS = 4
SPEECH_VERBS = frozenset("""
    say says said saying ask asks asked asking reply replies replied replying
    answer answers answered answering shout shouts shouted shouting yell yells yelled yelling
    scream screams screamed screaming cry cries cried crying
    whisper whispers whispered whispering murmur murmurs murmured murmuring
    mutter mutters muttered muttering exclaim exclaims exclaimed exclaiming
    announce announces announced announcing declare declares declared declaring
    tell tells told telling speak speaks spoke speaking""".split())
CALL_VERBS = frozenset(("call", "calls", "called", "calling"))     # speech only before "out"
CLAUSE_STOP_WORDS = frozenset("and then as but while before after until so or when".split())
NOT_SPEAKER_WORDS = frozenset("""
    that which it sign signs banner banners logo logos screen screens scoreboard jumbotron
    board boards billboard poster posters label caption display shirt jersey note card""".split())
GROUP_NOUNS = frozenset("""
    crowd crowds audience audiences fans spectators onlookers bystanders passers-by passersby
    pedestrians commuters supporters cheerleaders throng throngs mob mobs masses public
    congregation team teams squad squads band bands people extras""".split())
GROUP_DESCRIPTOR_RE = re.compile(
    r"^an?\s+(?:[A-Za-z-]+\s+){0,2}(?:group|crowd|throng|mob|row|pack|band|team|"
    r"squad|horde|swarm|flock|herd)\s+of\b", re.IGNORECASE)
COLLECTIVE_NOUNS = frozenset("group sea line mass row pack horde swarm flock herd bunch band team "
                             "squad mob throng crowd".split())
SPOKEN_LINES_HEADER = ("Spoken lines (the narrative quotes these words; the movie must speak "
                       "every one of them on camera, word for word, in this order):")


def line_words(text):
    """The words of a text for spoken-line matching (QL2): lower case, curly apostrophes made
    straight, an apostrophe inside a word kept, every other non-letter, non-digit character a
    word break (so case, punctuation and an ellipsis never matter)."""
    return _LINE_WORD_RE.findall(text.replace("’", "'").replace("‘", "'").lower())


def _speech_verb_at(words, p):
    """True when words[p] is a speech verb (a call verb only right before "out") whose word
    before it is not that, which, it, a text surface or a group noun (QL2 step 5)."""
    word = words[p]
    verb = word in SPEECH_VERBS or (word in CALL_VERBS and p + 1 < len(words)
                                    and words[p + 1] == "out")
    return verb and (words[p - 1] if p > 0 else "") not in NOT_SPEAKER_WORDS | GROUP_NOUNS


def classify_quotes(narrative):
    """[(inner, spoken)] for every double-quoted span of the narrative, in order (QL2): curly
    double quotes count as straight ones and pair left to right (an unmatched last quote is
    ignored); inner is the quoted text with its whitespace collapsed; spoken is True when a
    speech verb lies in the clause before the quote (at most 6 words back, after the last
    conjunction) or in the clause after it (at most 4 words on, before the first conjunction)."""
    text = narrative.replace("“", '"').replace("”", '"')
    matches = list(QUOTE_RE.finditer(text))
    out = []
    for i, match in enumerate(matches):
        prev_end = matches[i - 1].end() if i > 0 else 0
        next_start = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        before = line_words(_CLAUSE_BREAK_RE.split(
            text[prev_end:match.start()].rstrip(_QUOTE_EDGE_CHARS))[-1])
        stops = [j for j, w in enumerate(before) if w in CLAUSE_STOP_WORDS]
        if stops:
            before = before[stops[-1] + 1:]
        after = line_words(_CLAUSE_BREAK_RE.split(
            text[match.end():next_start].lstrip(_QUOTE_EDGE_CHARS))[0])
        stops = [j for j, w in enumerate(after) if w in CLAUSE_STOP_WORDS]
        if stops:
            after = after[:stops[0]]
        spoken = (any(_speech_verb_at(before, p)
                      for p in range(max(0, len(before) - BEFORE_WINDOW_WORDS), len(before)))
                  or any(_speech_verb_at(after, p)
                         for p in range(min(AFTER_WINDOW_WORDS, len(after)))))
        out.append((" ".join(match.group(1).split()), spoken))
    return out


def spoken_display(inner):
    """The display text of a quoted spoken line (QL3): one surrounding pair of straight or curly
    double quotes removed, every other double quote an apostrophe, whitespace collapsed (the
    three steps of character_lib.clean_line), "…" written as "...", trailing commas, semicolons,
    colons and dashes removed, and a full stop added unless it ends in . ! or ?. The author's
    ellipsis is kept."""
    line = inner.strip()
    for left, right in (('"', '"'), ("“", "”")):
        if len(line) >= 2 and line.startswith(left) and line.endswith(right):
            line = line[1:-1].strip()
            break
    for quote in ('"', "“", "”"):
        line = line.replace(quote, "'")
    line = " ".join(line.split()).replace("…", "...").rstrip(" ,;:—–-")
    if not line.endswith((".", "!", "?")):
        line += "."
    return line


def spoken_lines(narrative):
    """The display text of every spoken quote of the narrative that has a word, in order (QL3)."""
    return [spoken_display(inner) for inner, spoken in classify_quotes(narrative)
            if spoken and line_words(inner)]


def required_lines(ctx):
    """The spoken lines the movie must speak on camera (QL4): none with --no-narration."""
    return [] if ctx.narration is False else spoken_lines(ctx.narrative)


def spoken_lines_block(lines):
    """The numbered spoken-lines block appended to the narrative in the plan and critic prompts
    (QL6, QL11), or "" when there are no lines."""
    if not lines:
        return ""
    return "\n\n" + SPOKEN_LINES_HEADER + "".join('\n%d. "%s"' % (i, line)
                                                 for i, line in enumerate(lines, start=1))


def _n_sentences(n):
    """The text "1 sentence" or "<n> sentences" (QL5's new messages only)."""
    return "1 sentence" if n == 1 else "%d sentences" % n


def _lines_fit(lib, seconds, group):
    """True when the consecutive spoken lines of group, joined, fit one clip of seconds (QL5)."""
    text = " ".join(group)
    n = len(lib.split_fragments(text))
    return (n <= lib.DIALOGUE_MAX_FRAGMENTS
            and len(text.split()) <= lib.dialogue_word_cap(seconds, n))


def panels_needed(lib, seconds, lines):
    """The fewest panels that speak lines in order, packing consecutive lines greedily (QL5)."""
    needed, i = 0, 0
    while i < len(lines):
        j = i
        while j + 1 < len(lines) and _lines_fit(lib, seconds, lines[i:j + 2]):
            j += 1
        needed += 1
        i = j + 1
    return needed


def spoken_lines_problem(ctx):
    """Why the narrative's spoken lines cannot be spoken in this movie, or None (QL5): a line no
    clip fits, a line this clip length does not fit, or more lines than the panels can hold."""
    lines = required_lines(ctx)
    if not lines:
        return None
    lib = _character_lib(ctx.ws)
    secs = engine_seconds(ctx)
    for i, line in enumerate(lines, start=1):
        n = len(lib.split_fragments(line))
        words = len(line.split())
        if n > lib.DIALOGUE_MAX_FRAGMENTS or words > lib.DIALOGUE_MAX_WORDS:
            return ("the narrative's spoken line %d (\"%s\") is %d words in %s; no clip fits it, "
                    "because a spoken line has at most %d words in at most %d sentences; split it "
                    "into shorter quoted lines in the narrative"
                    % (i, line, words, _n_sentences(n), lib.DIALOGUE_MAX_WORDS,
                       lib.DIALOGUE_MAX_FRAGMENTS))
        cap = lib.dialogue_word_cap(secs, n)
        if words > cap:
            return ("the narrative's spoken line %d (\"%s\") is %d words in %s; a %s-second clip "
                    "fits at most %d words in %s; use longer clips (a larger --frames) or split it "
                    "into shorter quoted lines in the narrative"
                    % (i, line, words, _n_sentences(n), ctx.seconds, cap, _n_sentences(n)))
    needed = panels_needed(lib, secs, lines)
    if needed > ctx.panels:
        return ("the narrative quotes %d spoken lines, which need at least %d panels of %s seconds "
                "(one panel speaks at most %d words), but this movie has %d; use --panels %d or "
                "more, or longer clips (a larger --frames)"
                % (len(lines), needed, ctx.seconds, lib.dialogue_word_cap(secs, 1), ctx.panels,
                   needed))
    return None


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


def _mask_spans(lib, text, masks):
    """(start, end) of every occurrence in text of each mask string: its referring-phrase regex
    when it normalizes as a phrase, and its whole-word, case-insensitive literal."""
    spans = []
    for m in {m for m in masks if m and m.strip()}:
        try:
            pattern = lib._phrase_regex(lib.normalize_phrase(m))
        except lib.CharacterError:
            pattern = None
        if pattern:
            spans += [mo.span() for mo in pattern.finditer(text)]
        spans += [mo.span() for mo in re.finditer(r"(?<![\w-])" + re.escape(m) + r"(?![\w-])",
                                                  text, re.IGNORECASE)]
    return spans


def _first_unmasked(matches, spans):
    """The first match whose span lies inside no mask span, else None."""
    for mo in matches:
        if not any(s <= mo.start() and mo.end() <= e for s, e in spans):
            return mo
    return None


def undeclared_references(lib, text, undeclared, exact_phrase=False, masks=()):
    """[(name, kind, matched text)] for each undeclared character text refers to, first kind
    per character in the RS37 order: referring phrase, trigger, name. exact_phrase compares a
    cast entry's phrase by case-insensitive equality instead of occurrence. masks are strings of
    declared or invented characters; in occurrence mode a reference lying wholly inside an
    occurrence of a mask is not reported, but one that only overlaps a mask (an undeclared phrase
    that starts with an invented phrase, say) still is."""
    spans = _mask_spans(lib, text, masks) if not exact_phrase and masks else []
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
                pattern = lib._phrase_regex(lib.normalize_phrase(phrase))
            except lib.CharacterError:
                pattern = None
            match = _first_unmasked(pattern.finditer(text), spans) if pattern else None
            if match:
                hit = "referring phrase", match.group(0)
        for kind, word in (("trigger", trigger), ("name", name)):
            if hit is None and word.strip():
                match = _first_unmasked(re.finditer(r"(?<![\w-])" + re.escape(word) + r"(?![\w-])",
                                                    text, re.IGNORECASE), spans)
                if match:
                    hit = kind, match.group(0)
        if hit:
            hits.append((name, hit[0], hit[1]))
    return hits


def _undeclared_masks(lib, ctx, plan, undeclared):
    """Mask strings for undeclared_references: declared members' name, trigger, phrase and
    descriptor (their identity sentences are never flagged, RS37), plus each invented plan cast
    phrase (cast_name null) that does not itself name an undeclared character."""
    masks = [m for member in ctx.members
             for m in (member.name, member.trigger, member.phrase, member.descriptor)]
    if plan:
        masks += [e["phrase"] for e in plan["cast"] if isinstance(e.get("phrase"), str)
                  and not e.get("cast_name")
                  and not undeclared_references(lib, e["phrase"], undeclared, exact_phrase=True)]
    return masks


def undeclared_message(prefix, where, hit):
    name, kind, matched = hit
    return ("%s %s names library character %s by its %s '%s'; library characters appear only "
            "when declared with --character %s" % (prefix, where, name, kind, matched, name))


def build_plan_prompt(ctx, compatible, pins):
    """The exact plan prompt of RS7 (narrative dialogue fidelity spec QL6: the spoken-lines block
    after the narrative, the lines key and LINES_RULE when the narrative quotes spoken lines)."""
    lines = required_lines(ctx)
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
        ("@@SHOT_LIST@@", ", ".join(shot_types(ctx.narration))
         + (SPEECH_SHOT_NOTE if ctx.narration == "speech" else "")),
        ("@@CAMERA_LIST@@", ", ".join(CAMERA_KEYS)),
        ("@@LORA_PARAGRAPH@@", lora),
        ("@@MODE_RULES@@", MODE_RULES[ctx.mode]),
        ("@@SPEAKER_RULE@@", SILENT_SPEAKER_RULE if ctx.narration is False else SPEAKER_RULE),
        ("@@BEAT_KEYS@@", "cast, speaker and lines" if lines else "cast and speaker"),
        ("@@LINES_RULE@@", LINES_RULE if lines else ""),
    ]
    # character_lib is loaded only for a narrative with spoken lines, so an uncast dry run still
    # never loads it (test_rst47, test_s53).
    line_cap = (str(_character_lib(ctx.ws).dialogue_word_cap(engine_seconds(ctx), 2))
                if lines else "")
    scalars = [("@@STORY_ID@@", ctx.story_id), ("@@PANELS@@", str(ctx.panels)),
               ("@@SECONDS@@", ctx.seconds), ("@@MAX_CAST@@", str(MAX_CAST[ctx.mode])),
               ("@@LINE_WORDS@@", line_cap)]
    return _fill(PLAN_PROMPT_TEMPLATE, fragments, scalars,
                 ctx.narrative + spoken_lines_block(lines))


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


def _clean_lines(value):
    """A beat reply's "lines" (narrative dialogue fidelity spec QL7): its integers (not bools) and
    digit strings, as ints, in order; [] when it is not a list. Anything else is dropped,
    including a digit string int() cannot read (such as "²")."""
    if not isinstance(value, list):
        return []
    out = []
    for item in value:
        if isinstance(item, int) and not isinstance(item, bool):
            out.append(item)
        elif isinstance(item, str) and item.strip().isdigit():
            try:
                out.append(int(item))
            except ValueError:
                continue
    return out


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
            "cast": [_clean_str(c) if isinstance(c, str) else json.dumps(c) for c in beat_cast],
            "speaker": _clean_str(item.get("speaker")),
            "lines": _clean_lines(item.get("lines"))})
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
    plan["spoken_lines"] = required_lines(ctx)
    groups = [entry for entry in plan["cast"] if is_group_entry(entry)]
    plan["cast_notes"] = drop_groups(plan)
    plan["speech_notes"] = coerce_speakers(ctx, plan, groups)
    return plan, shape


# Narrative dialogue fidelity spec SM1: a speaking beat may be a medium shot, and its camera may
# stay static, push in, pull back or track the speaker.
SPEAKING_SHOTS = ("medium shot", "medium close-up", "close-up")
SPEAKING_CAMERAS = ("static", "slow push-in", "slow pull-back", "tracking")


def speaking_camera(beat):
    """The beat's camera when a speaking shot may keep it, else "static" (SM1)."""
    return beat["camera"] if beat["camera"] in SPEAKING_CAMERAS else "static"


def coerce_speakers(ctx, plan, groups=()):
    """The P14 notes of the speaking-beat coercion (dialogue spec SP2; narrative dialogue fidelity
    spec QL7), in beat order. Every beat gets a "speaker" (a cast id or "") and "lines" (the
    numbers of the narrative's spoken lines the beat says, ascending). A speaker the movie cannot
    have (--no-narration) or that is not a plan cast id is dropped. A line number is dropped when
    the narrative has no such line, when an earlier beat already says it or a later one, when the
    beat has no speaker and no sole cast member to become the speaker, or (the last line first)
    while the beat's lines together do not fit the clip. A beat that keeps a speaker gets
    speaking_coercion. No other beat is ever changed. groups are the cast entries drop_groups
    removed: a speaker that names one (by id or phrase) gets the P15 note of the controller
    ruling (plan Spec amendment 1) in place of the "not a cast id" and "speaker set to" notes."""
    notes = []
    cast_ids = [c["id"] for c in plan["cast"]]
    spoken = plan["spoken_lines"]
    lib = _character_lib(ctx.ws) if spoken else None
    last = 0
    for k, beat in enumerate(plan["beats"], start=1):
        raw, raw_lines = beat["speaker"], beat["lines"]
        beat["speaker"], beat["lines"] = "", []
        if ctx.narration is False:
            if raw:
                notes.append("beat %d: P14 speaking beat: speaker %s dropped: this movie has no "
                             "spoken lines" % (k, _q(raw)))
            continue
        sid, group, at = "", None, len(notes)
        if raw:
            for entry in plan["cast"]:
                if (raw not in cast_ids and entry.get("phrase")
                        and raw.strip().lower() == entry["phrase"].strip().lower()):
                    raw = entry["id"]
            if raw in cast_ids:
                sid = raw
            else:
                group = next((entry["phrase"] for entry in groups
                              if raw == entry["id"] or raw.strip().lower()
                              == (entry.get("phrase") or "").strip().lower()), None)
                if group is None:
                    notes.append("beat %d: P14 speaking beat: speaker %s is not a cast id, so "
                                 "nobody speaks in this beat" % (k, _q(raw)))
        if spoken:
            lines = []
            for n in sorted(set(raw_lines)):
                if not 1 <= n <= len(spoken):
                    notes.append("beat %d: P14 speaking beat: line %d dropped: the narrative has "
                                 "no spoken line %d" % (k, n, n))
                elif n <= last:
                    notes.append("beat %d: P14 speaking beat: line %d dropped: an earlier beat "
                                 "already speaks line %d or a later one" % (k, n, last))
                else:
                    lines.append(n)
            if lines and not sid:
                if len(beat["cast"]) == 1 and beat["cast"][0] in cast_ids:
                    sid = beat["cast"][0]
                    if group is None:
                        notes.append("beat %d: P14 speaking beat: speaker set to %s, the only "
                                     "character in the beat, to say line(s) %s"
                                     % (k, _q(sid), _nums(lines)))
                else:
                    notes.append("beat %d: P14 speaking beat: line(s) %s dropped: the beat has no "
                                 "speaker" % (k, _nums(lines)))
                    lines = []
            while lines and line_problem(ctx, lib, " ".join(spoken[n - 1] for n in lines)):
                n = lines.pop()
                notes.append("beat %d: P14 speaking beat: line %d dropped: together with the "
                             "beat's other lines it does not fit a %s-second clip"
                             % (k, n, ctx.seconds))
            run = 0
            while run < len(lines) and (run == 0 or lines[run] == lines[run - 1] + 1):
                run += 1
            if run < len(lines):
                notes.append("beat %d: P14 speaking beat: line(s) %s dropped: the beat's lines are "
                             "not consecutive" % (k, _nums(lines[run:])))
                lines = lines[:run]
            beat["lines"] = lines
            if lines:
                last = lines[-1]
        if group is not None:
            notes.insert(at, "beat %d: P15 group cast: %s is part of the setting, not a speaker; %s"
                         % (k, group, "the beat's line goes to %s" % speaker_phrase_of(plan, sid)
                            if sid else "the beat has no speaker"))
        if not sid:
            continue
        beat["speaker"] = sid
        notes += speaking_coercion(ctx, plan, k)
    return notes


def line_assignment_problems(plan):
    """The plan-scope Q1 messages (QL8): one for each of the narrative's spoken lines that no
    beat's lines hold. They make the plan call retry; they never enter a state."""
    held = set(n for beat in plan["beats"] for n in beat.get("lines", []))
    return ["plan: Q1 spoken line: spoken line %d \"%s\" is in no beat's lines; put %d in the "
            "lines of the beat whose action surrounds it in the narrative, and give that beat a "
            "speaker" % (n, line, n)
            for n, line in enumerate(plan.get("spoken_lines", []), start=1) if n not in held]


def speaking_coercion(ctx, plan, k):
    """The P14 notes of SP2 step 4 for beat k, whose speaker is already set (narrative dialogue
    fidelity spec QL7, SM2): the speaker is alone in the beat's cast, and when the beat frames
    its own shot (not a chained continuation, k >= 2) a shot wider than a medium shot becomes a
    medium close-up (an extreme close-up a close-up), and a camera that does not stay static,
    push in, pull back or track becomes static. Tracking is never coerced away."""
    notes = []
    beat = plan["beats"][k - 1]
    speaker = beat["speaker"]
    if beat["cast"] != [speaker]:
        notes.append("beat %d: P14 speaking beat: cast [%s] changed to [%s] so the speaker is "
                     "alone on screen" % (k, ", ".join(beat["cast"]), speaker))
        beat["cast"] = [speaker]
    if ctx.mode != "chained" or k == 1:
        if beat["shot"] not in SPEAKING_SHOTS:
            shot = "close-up" if beat["shot"] == "extreme close-up" else "medium close-up"
            notes.append("beat %d: P14 speaking beat: shot %s changed to %s so the speaker's "
                         "face stays readable" % (k, _q(beat["shot"]), _q(shot)))
            beat["shot"] = shot
        if beat["camera"] not in SPEAKING_CAMERAS:
            notes.append("beat %d: P14 speaking beat: camera %s changed to 'static' so the "
                         "speaker's face stays readable" % (k, _q(beat["camera"])))
            beat["camera"] = "static"
    return notes


def is_group_entry(entry):
    """True when a plan cast entry is a group of people, not a character (narrative dialogue
    fidelity spec GC2): it is not a library character, and the head word of its phrase (the last
    word before the first standalone "of", "from", "in", "at", "on" or "with", lowercased,
    without trailing punctuation (,.;:!?) or a trailing 's or ') is a GROUP_NOUNS word, or is a
    COLLECTIVE_NOUNS word cut at "of" ("a group of fans"), or its descriptor starts like
    "a group of" (GROUP_DESCRIPTOR_RE)."""
    if entry.get("cast_name") is not None:
        return False
    words = (entry.get("phrase") or "").split()
    cut = None
    for k, word in enumerate(words):
        if word.lower() in ("of", "from", "in", "at", "on", "with"):
            cut = word.lower()
            words = words[:k]
            break
    head = words[-1].lower().rstrip(",.;:!?") if words else ""
    for tail in ("'s", "’s", "'", "’"):
        if head.endswith(tail):
            head = head[:-len(tail)]
            break
    if cut == "of" and head in COLLECTIVE_NOUNS:
        return True
    return head in GROUP_NOUNS or bool(GROUP_DESCRIPTOR_RE.match(entry.get("descriptor") or ""))


def drop_groups(plan):
    """The P15 notes of GC3, in cast order: every group entry is removed from plan["cast"], and
    each removed id that no kept entry also uses is removed from every beat's cast (order kept)."""
    flags = [is_group_entry(entry) for entry in plan["cast"]]
    groups = [entry for entry, flag in zip(plan["cast"], flags) if flag]
    if not groups:
        return []
    plan["cast"] = [entry for entry, flag in zip(plan["cast"], flags) if not flag]
    gone = set(entry["id"] for entry in groups) - set(entry["id"] for entry in plan["cast"])
    listed = {}
    for k, beat in enumerate(plan["beats"], start=1):
        for cid in beat["cast"]:
            if cid in gone and k not in listed.setdefault(cid, []):
                listed[cid].append(k)
        beat["cast"] = [cid for cid in beat["cast"] if cid not in gone]
    notes = []
    for entry in groups:
        beats = listed.get(entry["id"], [])
        where = ("" if not beats else " and from beat%s %s"
                 % ("s" if len(beats) > 1 else "", ", ".join(str(k) for k in beats)))
        notes.append("plan: P15 group cast: %s %s is a group of people, not a character, so it is "
                     "removed from the cast%s; describe it in the setting sentence instead"
                     % (entry["id"], _q(entry["phrase"]), where))
    return notes


_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")   # character_lib._SENTENCE_SPLIT_RE
_ID_RES = {"cast": re.compile(r"c[1-9][0-9]*"), "locations": re.compile(r"l[1-9][0-9]*"),
           "props": re.compile(r"p[1-9][0-9]*")}


def _q(text):
    return "'%s'" % text


def _nums(numbers):
    """Spoken-line numbers as "1, 2" (QL7)."""
    return ", ".join(str(n) for n in numbers)


def speaker_phrase_of(plan, cid):
    """The referring phrase of plan cast id cid (plan Spec amendment 1)."""
    return next(c["phrase"] for c in plan["cast"] if c["id"] == cid)


def outside_range(words, lo, hi):
    """True when a word count is outside lo-hi by more than WORD_TOLERANCE."""
    return words < lo * (1 - WORD_TOLERANCE) or words > hi * (1 + WORD_TOLERANCE)


def _setting_length(setting):
    """The advisory P4 detail for a setting sentence's word count, or None."""
    words = _words(setting)
    return "is %d words; aim for 12-45" % words if outside_range(words, 12, 45) else None


def _setting_problems(setting):
    """The hard P4 details for one setting sentence (start, one sentence); its word count is
    advisory (_setting_length)."""
    problems = []
    if not setting.startswith("The setting is "):
        problems.append('does not start with "The setting is"')
    if len([s for s in _SENTENCE_SPLIT_RE.split(setting.strip()) if s.strip()]) != 1:
        problems.append("is more than one sentence")
    return problems


FACING_SENTENCE = "%s faces the camera."
SPEAKING_CAMERA = "The camera stays static."
# CM4: on a non-speaking panel, a writer camera sentence that names one of these movements takes
# the place of the planned camera sentence in the assembled field.
CAMERA_MOTION_RE = re.compile(r"\b(?:static|still|holds?|locked-off|push(?:es)?\s+in|push-in|"
                              r"pull(?:s)?\s+back|pull-back|pans?|tilts?|tracks?|tracking|dolly|"
                              r"dollies|zooms?|orbits?|cranes?|handheld|follows?)\b", re.IGNORECASE)


def _sentences(text):
    """The non-empty sentences of a text, stripped."""
    return [s.strip() for s in _SENTENCE_SPLIT_RE.split(text.strip()) if s.strip()]


def _facing(ctx, plan, k):
    """[the pasted "<Speaker> faces the camera." sentence] on a speaking panel, else [] (SP4)."""
    phrase = speaker_phrase(plan, k) if panel_speaks(ctx, plan, k) else None
    return [FACING_SENTENCE % (phrase[:1].upper() + phrase[1:])] if phrase else []


def _moves_camera(ctx, plan, text):
    """True when writer text holds a camera sentence (_is_camera_sentence with the plan's cast
    phrases) that names a camera movement (CAMERA_MOTION_RE) (CM4)."""
    if not CAMERA_MOTION_RE.search(text or ""):
        return False
    lib = _character_lib(ctx.ws)
    phrases = [c["phrase"] for c in plan["cast"] if c["phrase"]]
    return any(lib._is_camera_sentence(s, phrases) and CAMERA_MOTION_RE.search(s)
               for s in _sentences(text))


def pasted_pieces(ctx, plan, k):
    """{field: [pasted sentences in assembly order]} for panel k (RS14; dialogue spec SP4): the
    pieces of each assembled field that the writer does not write. A speaking panel adds the
    facing sentence (and, chained k >= 2, the camera sentence of speaking_camera: the planned
    camera, or "The camera stays static." for a pan or tilt; narrative dialogue fidelity spec
    SM3). The planned camera sentence is always listed, even when CM4 leaves it out of the
    assembled field."""
    beat = plan["beats"][k - 1]
    by_cast = {c["id"]: c for c in plan["cast"]}
    by_location = {l["id"]: l for l in plan["locations"]}
    setting = by_location[beat["location"]]["setting"] if beat["location"] in by_location else ""
    identities = [identity(by_cast[c]) for c in beat["cast"] if c in by_cast]
    shot = shot_sentence(beat) if beat["shot"] in SHOT_TYPES else ""
    camera = dict(CAMERA_SENTENCES).get(beat["camera"], "")
    facing = _facing(ctx, plan, k)
    pieces = [setting] + identities + facing + [shot]
    if ctx.mode == "chained":
        if k == 1:
            return {"image": pieces, "motion": facing + [camera], "narration": []}
        return {"motion": facing + ([dict(CAMERA_SENTENCES)[speaking_camera(beat)]]
                                    if facing else []), "narration": []}
    if ctx.mode == "no_stills":
        return {"prompt": identities + [setting, shot] + facing + [camera], "narration": []}
    return {"image": pieces, "motion": facing + [camera], "narration": []}


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
    normalize_plan's container-shape P2 violations, reported first. Hard: P1, P2 and P3's
    normalize and duplicate-phrase messages; every other P message is advisory (dialogue spec
    6.3)."""
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
            advisory.append("plan: P3 cast entry: %s's phrase %s has %d words; at most 4"
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
            advisory.append("plan: P3 cast entry: %s's %s" % (cid, e))
    for lid, entry in valid["locations"].items():
        for problem in _setting_problems(entry["setting"]):
            advisory.append("plan: P4 setting sentence: %s's setting %s" % (lid, problem))
        length = _setting_length(entry["setting"])
        if length:
            advisory.append("plan: P4 setting sentence: %s's setting %s" % (lid, length))
    arcs = [beat["arc"] if beat["arc"] in ARC_ROLES else None for beat in beats]
    for k, beat in enumerate(beats, start=1):
        if beat["arc"] and beat["arc"] not in ARC_ROLES:
            advisory.append("beat %d: P5 arc: %s is not one of %s"
                        % (k, _q(beat["arc"]), ", ".join(ARC_ROLES)))
    required = (() if n == 1 else ("introduction", "resolution") if n == 2
                else ("introduction", "climax", "resolution"))
    for role in required:
        if role not in arcs:
            advisory.append("plan: P5 arc: no beat has arc %s" % _q(role))
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
            advisory.append("beat %d: P7 shot type: %s is not one of: %s"
                        % (k, _q(beat["shot"]), ", ".join(SHOT_TYPES)))
        elif (beat["shot"] and beat["shot"] not in shot_types(ctx.narration)
              and (ctx.mode != "chained" or k == 1)):
            advisory.append("beat %d: P7 shot type: %s is too wide for on-screen speech; use one of: %s"
                        % (k, _q(beat["shot"]), ", ".join(shot_types(ctx.narration))))
        if beat["camera"] and beat["camera"] not in CAMERA_KEYS:
            advisory.append("beat %d: P8 camera: %s is not one of: %s"
                        % (k, _q(beat["camera"]), ", ".join(CAMERA_KEYS)))
        if len(beat["cast"]) > MAX_CAST[ctx.mode]:
            advisory.append("beat %d: P9 cast count: %d characters on screen; at most %d in this mode"
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
                    advisory.append("beat %d: P10 word budget: %s: the pasted sentences take %d of its "
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
                advisory.append(undeclared_message("plan: P13 undeclared character:", where, hit))
    advisory += plan.get("cast_notes", [])
    if ctx.narration is False:
        silent = spoken_lines(ctx.narrative)
        if silent:
            advisory.append("plan: Q2 spoken lines: the narrative quotes %d spoken line(s), but "
                            "--no-narration makes this movie silent, so none of them is spoken"
                            % len(silent))
    quotes = ctx.narrative.replace("“", '"').replace("”", '"').count('"')
    if quotes % 2:
        advisory.append("plan: Q3 quotes: the narrative has an odd number of double quotes (%d), "
                        "so its last quote is unmatched and ignored; close every quoted line"
                        % quotes)
    advisory += plan["speech_notes"]
    return hard, advisory


def _is_pick(pick):
    return (isinstance(pick, dict) and isinstance(pick.get("id"), str)
            and isinstance(pick.get("strength"), (int, float))
            and not isinstance(pick.get("strength"), bool))


def lora_checks(ctx, plan, compatible_by_id, catalog_by_id):
    """(hard, advisory) LoRA violations of a plan (RS11, LC12). Not run without auto LoRA. Hard:
    L1, L6, L7 and a strength outside (0, 2], which the renderer refuses; L2-L4 and a strength
    outside the entry's own range are advisory (dialogue spec 6.3, Q4)."""
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
        if not 0 < pick["strength"] <= 2:
            hard.append("plan: L5 strength: %s strength %s is outside (0, 2], which the renderer "
                        "refuses" % (_q(pick["id"]), repr(float(pick["strength"]))))
        elif not lo <= pick["strength"] <= hi:
            advisory.append("plan: L5 strength: %s strength %s is outside its range %s to %s"
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
        advisory.append("plan: L2 style: %d style LoRAs for every panel (%s); at most 1"
                    % (len(styles), ", ".join(styles)))
    for k in sorted(per_beat):
        for e in per_beat[k]:
            if e["kind"] == "style":
                advisory.append("beat %d: L2 style: style LoRA %s can only be a global pick"
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
            advisory.append("beat %d: L3 motion: %d motion or physics LoRAs on this panel (%s); at "
                        "most 1" % (k, len(motion), ", ".join(motion)))
        if len(loras_k) > LORA_PANEL_LIMIT:
            message = ("beat %d: L4 LoRA count: %d LoRAs on this panel (%s); at most %d"
                       % (k, len(loras_k), ", ".join(l[0] for l in loras_k), LORA_PANEL_LIMIT))
            advisory.append(message)
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
    """.split())
_APPEARANCE_RE = re.compile(r"(?<![\w-])(?:%s)(?![\w-])" % "|".join(
    re.escape(w) for w in sorted(APPEARANCE_WORDS, key=lambda w: (-len(w), w))), re.IGNORECASE)
# Camera language is never an N3 fault (dialogue spec CM2, D5).
# N17: a speaking character needs a visible, moving mouth.
WIDE_SHOTS = ("extreme wide shot", "wide shot")
HELD_EXPRESSION_RE = re.compile(r"\b(?:broad\s+|wide\s+|big\s+)?(?:smil(?:e|es|ing)|grin(?:s|ning)?|"
                                r"beam(?:s|ing)|smirk(?:s|ing)?)\b", re.IGNORECASE)
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
_LABEL_RE = re.compile(r"^(?:title|image|motion|prompt|narration|dialogue)\s*:\s*",
                       re.IGNORECASE)
_QUOTE_PAIRS = (('"', '"'), ("“", "”"))
_TITLE_CHARS_RE = re.compile(r"[^A-Za-z0-9 '-]")
LABELS = {"image": "Image", "motion": "Motion", "prompt": "Prompt", "narration": "Narration",
          "dialogue": "Dialogue"}

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
        "steps: @@SECONDS@@ seconds is enough for a single gesture, a few footsteps or the "
        "start of a movement. The motion plays at natural, real-time speed: use plain action "
        "verbs with no adverbs of speed or manner. You may add one camera direction; without "
        "one, the pipeline adds the planned camera sentence."),
    "chained_motion": (
        "motion: W1 to W2 words in one or two plain sentences: what the characters physically do "
        "during these @@SECONDS@@ seconds, continuing from where the previous panel left them. "
        "Name each character only by their referring phrase, word for word. Describe ONE "
        "continuous physical motion, not a sequence of separate steps: @@SECONDS@@ seconds is "
        "enough for a single gesture, a few footsteps or the start of a movement. Do not describe "
        "appearance, clothing, setting, lighting, colour or style -- all of that is already on "
        "screen. You may add one camera direction."),
    "no_stills_prompt": (
        "prompt: W1 to W2 words in the present tense: one flowing paragraph in strict "
        "chronological order that opens with the main action, carries enough separate beats to "
        "fill the full @@SECONDS@@ seconds, links them with temporal connectors (initially, as, "
        "then, while, a moment later), names the ambient and environmental sounds alongside the "
        "actions that make them, and states the camera viewpoint and the lighting and colour; you "
        "may also state a camera movement. Name each character only by their referring phrase. Do "
        "not describe any character's appearance or clothing, do not write a sentence about the "
        "place itself and do not name the shot type: the pipeline adds each character's "
        "description, the place's setting sentence, the shot type and, unless you state one, the "
        "camera movement itself. Describe only what is physically observable, with no mood words, "
        "no spoken words and no markdown."),
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
        "before and, and never use a semicolon. You may follow it with one camera sentence; "
        "without one, the pipeline adds the planned camera sentence."),
    "narration": ("narration: one sentence of 3 to 30 words of voice-over that nobody on screen "
                  "says aloud. Never put a spoken line here."),
    "narration_with_dialogue": ("narration: one sentence of 3 to 30 words of voice-over that "
                                "nobody on screen says aloud, or an empty string: this panel's "
                                "spoken line goes in dialogue, never here."),
    "dialogue": ("dialogue: the exact words @@SPEAKER@@ says aloud in this panel: at most "
                 "@@DWORDS@@ words as one sentence, about one word fewer for each further "
                 "sentence, and at most three sentences; no quotation marks, no speaker name and "
                 "no description of how the words are said -- the pipeline adds who says them and "
                 "how."),
}
# Narrative dialogue fidelity spec QL9, 7.2: the dialogue key line of a beat that says the
# narrative's spoken lines (@@LINE@@ is those lines, quoted; the pipeline pastes them itself).
KEY_LINE_TEMPLATES["dialogue_fixed"] = (
    "dialogue: exactly @@LINE@@ -- the narrative's own words, which @@SPEAKER@@ says aloud in "
    "this panel; copy them unchanged, because the pipeline uses the narrative's words whatever "
    "this field holds.")
KEY_LINE_TEMPLATES["no_stills_prompt_speaking"] = KEY_LINE_TEMPLATES["no_stills_prompt"].replace(
    "carries enough separate beats to fill the full @@SECONDS@@ seconds, links them with temporal "
    "connectors (initially, as, then, while, a moment later), ",
    "fills the full @@SECONDS@@ seconds with the one continuous movement of @@SPEAKER@@ that the "
    "beat describes, keeping their face toward the camera while they speak, ")
# Appended to a speaking panel's key lines (dialogue spec 8.2; narrative dialogue fidelity spec
# 7.2); @@SPEAKER@@ is the speaker's quoted referring phrase.
SPEAKING_ACTION_SENTENCE = (" In this panel @@SPEAKER@@ speaks the dialogue: they may move as the "
                            "beat says, but write the motion so that their face is toward the "
                            "camera, in frame and lit while they speak -- a speaker who approaches "
                            "the camera speaks once close -- and do not write the spoken words or "
                            "a speaking verb here; the pipeline adds them.")
SPEAKING_PROMPT_SENTENCE = (" Do not write the spoken words or a speaking verb here; the pipeline "
                            "adds them.")
SPEAKING_IMAGE_SENTENCE = (" @@SPEAKER@@ is the only person in the foreground, facing the camera; "
                           "any crowd stays in the background.")
SPEAKING_SENTENCES = {"image": SPEAKING_IMAGE_SENTENCE, "motion": SPEAKING_ACTION_SENTENCE,
                      "prompt": SPEAKING_PROMPT_SENTENCE}
FIX_INSTRUCTION = ("\nFix only these problems. Keep every camera direction, every descriptive "
                   "sentence and the dialogue word for word, and change only the sentence or "
                   "sentences that cause them.")


def writer_keys(mode, k, narration=True, speaks=False):
    """The writer parts of panel k (Section 2.3; dialogue spec SP5), in order: title, image
    (chained panel 1 and shots), motion or prompt, dialogue when the panel speaks and the movie
    has spoken lines, narration only when narration is True (--speech-only has none)."""
    if mode == "chained":
        keys = ["title", "image", "motion"] if k == 1 else ["title", "motion"]
    elif mode == "no_stills":
        keys = ["title", "prompt"]
    else:
        keys = ["title", "image", "motion"]
    if speaks and narration is not False:
        keys.append("dialogue")
    if narration is True:
        keys.append("narration")
    return tuple(keys)


def panel_speaks(ctx, plan, k):
    """True when beat k has a speaker and the movie has spoken lines (dialogue spec SP4)."""
    return bool(plan["beats"][k - 1]["speaker"]) and ctx.narration is not False


def speaker_phrase(plan, k):
    """The referring phrase of beat k's speaker, or None when nobody speaks."""
    speaker = plan["beats"][k - 1]["speaker"]
    for entry in plan["cast"]:
        if speaker and entry["id"] == speaker:
            return entry["phrase"]
    return None


def assigned_dialogue(plan, k):
    """The narrative's spoken lines that beat k says, joined by spaces, or "" (narrative dialogue
    fidelity spec QL9): the pasted Dialogue text of a beat with lines, whatever the writer
    replied. A plan without spoken_lines or lines (an older plan.json) gives ""."""
    spoken = plan.get("spoken_lines", [])
    return " ".join(spoken[n - 1] for n in plan["beats"][k - 1].get("lines", [])
                    if 1 <= n <= len(spoken))


def panel_keys(ctx, plan, k):
    """writer_keys for panel k of a plan (dialogue spec SP5)."""
    return writer_keys(ctx.mode, k, ctx.narration, speaks=bool(plan["beats"][k - 1]["speaker"]))


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


def empty_parts(mode, k, plan, ctx=None):
    keys = panel_keys(ctx, plan, k) if ctx is not None else writer_keys(mode, k)
    parts = {key: "" for key in keys}
    parts["title"] = title_fallback(plan["beats"][k - 1]["action"]) or "Panel %d" % k
    if ctx is not None and assigned_dialogue(plan, k):
        parts["dialogue"] = assigned_dialogue(plan, k)
    return parts


def parse_panel_reply(ctx, plan, k, answer):
    """The cleaned writer parts of panel k from a reply, or None when the reply is not valid
    (RS13): every non-title key must hold a string that is non-empty after cleanup."""
    obj = extract_json(answer)
    if obj is None:
        return None
    lib = _character_lib(ctx.ws)
    pasted = pasted_pieces(ctx, plan, k)
    speaks = panel_speaks(ctx, plan, k)
    parts = {}
    for key in panel_keys(ctx, plan, k):
        if key == "title":
            continue
        value = clean_writer(lib, obj.get(key), pasted.get(key, ()))
        if key == "dialogue":
            value = assigned_dialogue(plan, k) or _clean_dialogue(lib, value,
                                                                  speaker_phrase(plan, k))
        if not value and not (key == "narration" and speaks):
            return None
        parts[key] = value
    title = clean_writer(lib, obj.get("title"))
    if not title or _words(title) > 6:
        title = title_fallback(plan["beats"][k - 1]["action"]) or "Panel %d" % k
    return dict({"title": title}, **parts)


def _clean_dialogue(lib, text, phrase):
    """A writer's or critic's spoken line: a leading "<phrase>:" removed (case-insensitive), then
    one surrounding pair of quotes off and every other double quote turned into an apostrophe
    (dialogue spec SP5, PG4; DG3 step 4)."""
    if phrase:
        text = lib._speaker_regex(phrase).sub("", text, count=1)
    return lib.clean_line(text)


def panel_fields(ctx, plan, parts, k):
    """[(Label, assembled text)] of panel k in file order (RS14; dialogue spec SP4): Image: where
    the mode has one (setting, identities, writer image, facing, shot), Motion: or Prompt: (the
    writer text, then the pasted sentences; on a non-speaking panel the planned camera sentence
    is left out when the writer text moves the camera, CM4), Dialogue: on a speaking panel
    ("<phrase>: <line>"), then Narration: when narration is True and the part is non-empty or the
    panel does not speak."""
    p = parts[k - 1]
    pasted = pasted_pieces(ctx, plan, k)
    facing = _facing(ctx, plan, k)

    def join(pieces):
        return " ".join(_sentence(piece) for piece in pieces if piece and piece.strip())

    fields = []
    if (ctx.mode == "chained" and k == 1) or ctx.mode == "shots":
        image = pasted["image"]
        cut = len(image) - 1 - len(facing)
        fields.append(("Image", join(image[:cut] + [p.get("image", "")] + image[cut:])))
    key = "prompt" if ctx.mode == "no_stills" else "motion"
    pieces = pasted[key]
    if not facing and pieces and _moves_camera(ctx, plan, p.get(key, "")):
        pieces = pieces[:-1]
    fields.append((LABELS[key], join([p.get(key, "")] + pieces)))
    if facing:
        line = _sentence(assigned_dialogue(plan, k)
                         or _character_lib(ctx.ws).clean_line(p.get("dialogue", "")))
        fields.append(("Dialogue", (speaker_phrase(plan, k) + ": " + line).rstrip()))
    if ctx.narration is True and (p.get("narration", "").strip() or not facing):
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


# Dialogue spec 6.2: the timing and action rules.
ACTION_SECONDS = 3.0
NO_STILLS_BEAT_SECONDS = 1.0
SEQUENCE_RE = re.compile(r"\b(?:then|afterwards?|whereupon|followed\s+by|as\s+soon\s+as)\b",
                         re.IGNORECASE)
NO_STILLS_CONNECTOR_RE = re.compile(r"\b(?:initially|a\s+moment\s+later|moments\s+later|finally|"
                                    r"after\s+that|soon\s+after)\b", re.IGNORECASE)
# N17: the CAMERA_MOTION_RE words a speaking shot may use: it stays still, pushes in, pulls back
# or tracks the speaker (narrative dialogue fidelity spec SM1, SM5).
STILL_CAMERA_MOVES = ("static", "still", "hold", "holds", "locked-off", "push in", "pushes in",
                      "push-in", "pull back", "pulls back", "pull-back", "track", "tracks",
                      "tracking", "follow", "follows")
SPLIT_INSTRUCTION = ("shorten the line, or split it across alternating close-up panels (the "
                     "speaker, then the listener, then the speaker again)")


def cast_phrases(ctx, plan):
    """The plan's cast phrases, or the cast members' phrases when there is no plan."""
    if plan:
        return [c["phrase"] for c in plan["cast"] if c.get("phrase")]
    return [m.phrase for m in ctx.members]


def action_units(ctx, lib, text, phrases):
    """(action sentences, action units, the most actions the clip fits) of a writer action text
    (dialogue spec 6.2): chained 1 + sequence markers + sentences beyond two; shots sentences +
    sequence markers; no_stills 1 + sequence markers + connectors. A camera sentence
    (_is_camera_sentence with phrases) is not an action sentence."""
    actions = len([s for s in _sentences(text) if not lib._is_camera_sentence(s, phrases)])
    seq = len(SEQUENCE_RE.findall(text))
    if ctx.mode == "chained":
        units = 1 + seq + max(0, actions - 2)
    elif ctx.mode == "shots":
        units = actions + seq
    else:
        units = 1 + seq + len(NO_STILLS_CONNECTOR_RE.findall(text))
    per = NO_STILLS_BEAT_SECONDS if ctx.mode == "no_stills" else ACTION_SECONDS
    return actions, units, max(1, int(engine_seconds(ctx) / per + 1e-9))


def over_cap(ctx, lib, line):
    """The T1 detail when a spoken line does not fit this clip (more words than its fragment-aware
    cap, or more than three sentences), else None (dialogue spec 6.2)."""
    n = len(lib.split_fragments(line))
    words = len(line.split())
    cap = lib.dialogue_word_cap(engine_seconds(ctx), n)
    if words <= cap and n <= lib.DIALOGUE_MAX_FRAGMENTS:
        return None
    return ("%d words in %d sentences; a %s-second clip fits at most %d words in %d sentences, and "
            "a line has at most 3 sentences; %s" % (words, n, ctx.seconds, cap, n,
                                                    SPLIT_INSTRUCTION))


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
    """(hard, advisory) of one panel: the RS15 checks named in ids, plus N15 when in ids. Hard:
    N11 (Narration: empty with no Dialogue:), N18, T1, T2, T3; every other N rule is advisory
    (dialogue spec 6.3, D6).
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
                if outside_range(_words(text), lo, hi):
                    add(advisory, "N1", "word count", label,
                        "is %d words; aim for %d-%d" % (_words(text), lo, hi))
        if ctx.mode == "chained" and k >= 2 and label == "Motion" and plan:
            humans = [p for p in phrases if not lib.is_animal_phrase(p)]
            animals = [p for p in phrases if lib.is_animal_phrase(p)]
            if "N2" in ids:
                for sentence in lib._SENTENCE_SPLIT_RE.split(text.strip()):
                    refs = [r for r in lib._person_refs(sentence, humans, animals, [])
                            if r[2] in lib.SHOTS_PERSON_NOUNS]
                    if refs:
                        add(advisory, "N2", "referring phrase", label,
                            "names %s outside every referring phrase; name each character by "
                            "their exact phrase" % _q(refs[0][2]))
                        break
            if "N3" in ids:
                blanked = lib._blank(text, lib._passage_spans(
                    text, list(phrases) + [p["name"] for p in plan["props"] if p["name"]]))
                word = _first(_APPEARANCE_RE, blanked)
                if word:
                    add(advisory, "N3", "appearance", label,
                        "says %s; panels after the first never re-describe appearance, clothing, "
                        "setting, lighting, colour or style" % _q(word))
        if "N4" in ids and label not in ("Narration", "Dialogue") and beat is not None:
            for phrase in lib.find_phrases(writer, list(phrases)):
                if phrases[phrase] not in beat["cast"]:
                    add(advisory, "N4", "stray cast", label,
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
                    add(advisory, "N5", "setting sentence", label,
                        "lacks %s's setting sentence word for word" % own["id"])
                else:
                    for other in plan["locations"]:
                        if (other["id"] != own["id"] and other["setting"]
                                and _norm_text(other["setting"]) != _norm_text(own["setting"])
                                and _norm_text(other["setting"]) in norm):
                            add(advisory, "N5", "setting sentence", label,
                                "contains %s's setting sentence; beat %d is at %s"
                                % (other["id"], k, own["id"]))
                            break
            if "N6" in ids:
                for cid in beat["cast"]:
                    entry = by_cast.get(cid)
                    if entry is None or (ctx.mode == "shots" and entry["cast_name"]):
                        continue
                    if _norm_text(entry["descriptor"]) not in norm:
                        add(advisory, "N6", "description", label,
                            "lacks %s's description word for word" % cid)
                        break
        if label in action_fields:
            if "N7" in ids:
                if any(q in writer for q in ('"', "“", "”")):
                    add(advisory, "N7", "dialogue and text", label, "contains a double quote")
                else:
                    word = _first(DIALOGUE_RE, writer) or _first(ONSCREEN_TEXT_RE, writer)
                    if word:
                        add(advisory, "N7", "dialogue and text", label, "says %s" % _q(word))
            if "N8" in ids and ctx.mode != "shots":
                word = _first(lib._OFFSCREEN_RE, writer)
                if word:
                    add(advisory, "N8", "off-screen", label,
                        "says %s; describe only what is in the frame" % _q(word))
            if "N9" in ids:
                word = _first(CUT_RE, writer)
                if word:
                    add(advisory, "N9", "cut wording", label,
                        "says %s; one panel is one continuous shot" % _q(word))
        if "N10" in ids and label != "Dialogue":
            found = PLACEHOLDER_RE.search(writer)
            copied = found.group(0) if found else next(
                (ex for ex in COPIED_EXAMPLES if _norm_text(ex) in _norm_text(writer)), None)
            if copied:
                add(advisory, "N10", "copied example", label, "contains template text %s" % _q(copied))
        if ("N11" in ids and label == "Narration" and not text.strip() and ctx.narration is True
                and not dict(fields).get("Dialogue", "").strip()):
            hard.append("%s N11 narration: Narration: is empty" % prefix)
    if "N15" in ids and undeclared:
        masks = _undeclared_masks(lib, ctx, plan, undeclared)
        for label, text in [("Title", title)] + list(fields):
            for hit in undeclared_references(lib, text, undeclared, masks=masks):
                advisory.append(undeclared_message("%s N15 undeclared character:" % prefix,
                                               label + ":", hit))
    known = cast_phrases(ctx, plan)
    dialogue = dict(fields).get("Dialogue", "")
    if dialogue.strip():
        _phrase, line, problem = lib.parse_dialogue(dialogue, known)
        if problem:
            if "N18" in ids:
                hard.append("%s N18 dialogue: Dialogue: %s" % (prefix, problem))
        elif "T1" in ids:
            detail = over_cap(ctx, lib, line)
            if detail:
                hard.append("%s T1 spoken timing: Dialogue: is %s" % (prefix, detail))
    elif "T1" in ids:
        spoken = dict(fields).get("Narration", "")
        speaker, speech = lib.split_speaker(spoken, known) if ":" in spoken else (None, "")
        detail = over_cap(ctx, lib, speech) if speaker else None
        if detail:
            advisory.append("%s T1 spoken timing: Narration: speaks %s" % (prefix, detail))
    action_label = "Prompt" if ctx.mode == "no_stills" else "Motion"
    if ("T2" in ids or "T3" in ids) and action_label in dict(fields) \
            and not dict(fields)[action_label].strip():
        hard.append("%s S3 fields: missing/empty %s: field" % (prefix, action_label))
    if ("T2" in ids or "T3" in ids) and action_label in dict(fields):
        actions, units, most = action_units(ctx, lib, writers.get(action_label, ""), known)
        if actions == 0:
            if "T2" in ids:
                hard.append("%s T2 action amount: %s: has no physical action; a %s-second clip "
                            "needs one, so add one action sentence and keep every other sentence "
                            "word for word" % (prefix, action_label, ctx.seconds))
        elif units > 2 * most:
            if "T3" in ids:
                hard.append("%s T3 action overload: %s: holds %d actions; a %s-second clip fits at "
                            "most %d and cannot render more than %d; give the extra actions their "
                            "own panels" % (prefix, action_label, units, ctx.seconds, most,
                                            2 * most))
        elif units > most:
            if "T2" in ids:
                hard.append("%s T2 action amount: %s: holds %d actions; a %s-second clip fits at "
                            "most %d, so cut the extra actions and keep every other sentence word "
                            "for word" % (prefix, action_label, units, ctx.seconds, most))
    if "N19" in ids and ctx.mode == "chained" and plan and beat is not None:
        motion = dict(fields).get("Motion", "")
        cast_members = dict((m.name, m) for m in ctx.members)
        for cid in beat["cast"]:
            entry = by_cast.get(cid)
            member = cast_members.get(entry.get("cast_name")) if entry else None
            if member is None or lib.member_referenced(motion, member):
                continue
            how = ("refers to %s only by pronoun" if lib._PRONOUN_RE.search(writers.get("Motion", ""))
                   else "never names %s")
            add(advisory, "N19", "cast reference", "Motion",
                (how % _q(member.phrase)) + "; the pipeline attaches %s's LoRA from the plan "
                "and prefixes the trigger" % member.name)
    if "N12" in ids and ctx.mode == "chained":
        writer = writers.get("Motion", "")
        chain = _first(lib._CHAIN_WORD_RE, writer)
        if chain is None and ";" in writer:
            chain = ";"
        if chain is None and lib._COMMA_AND_RE.search(writer):
            chain = ", and"
        if chain:
            add(advisory, "N12", "one action", "Motion", "chains actions with %s" % _q(chain))
    narration = dict(fields).get("Narration", "")
    on_screen = ([by_cast[c]["phrase"] for c in beat["cast"] if c in by_cast]
                 if beat is not None else [])
    spoken_by = lib.parse_dialogue(dialogue, known)[0] if dialogue.strip() else None
    if "N16" in ids and beat is not None:
        found = lib.speaker_prefix(narration)
        speech_only = ctx.narration == "speech"
        if spoken_by is not None:
            if spoken_by.lower() not in [p.lower() for p in on_screen]:
                add(advisory, "N16", "speaker", "Dialogue",
                    "is spoken by %s, who is not in this shot; put %s in the shot or move the "
                    "line to a panel that shows them" % (_q(spoken_by), _q(spoken_by)))
        elif speech_only and narration.strip() and (
                not found or lib.split_speaker(narration, known)[0] is None):
            add(advisory, "N16", "speaker", "Narration",
                "is voice-over, but this story is speech-only; start it with the referring "
                "phrase of the character in the shot who says it and a colon, or leave it empty")
        elif found:
            if lib.split_speaker(narration, on_screen)[0] is not None:
                pass
            elif lib.split_speaker(narration, known)[0] is not None:
                add(advisory, "N16", "speaker", "Narration",
                    "is spoken by %s, who is not in this shot; only a character on screen can "
                    "speak, so make it voice-over (no prefix) or put %s in the shot"
                    % (_q(found[0]), _q(found[0])))
            else:
                add(advisory, "N16", "speaker", "Narration",
                    "starts with %s, which is no character's referring phrase, so it is read as "
                    "voice-over; start a spoken line with the speaker's referring phrase, or drop "
                    "the colon" % _q(found[0] + ":"))
    if "N17" in ids and beat is not None:
        if spoken_by is not None:
            speech_label = "Dialogue"
            speaker = (spoken_by if spoken_by.lower() in [p.lower() for p in on_screen] else None)
        else:
            speech_label = "Narration"
            speaker = lib.split_speaker(narration, on_screen)[0] if narration.strip() else None
        if speaker:
            shot_applies = ctx.mode != "chained" or k == 1
            if shot_applies and beat["shot"] in WIDE_SHOTS:
                add(advisory, "N17", "speaking shot", speech_label,
                    "%s speaks in a %s, too small to read the lips, so it plays as voice-over; "
                    "use a medium shot or closer" % (_q(speaker), beat["shot"]))
            held = next((w for w in (_first(HELD_EXPRESSION_RE, writers.get(field, ""))
                                     for field in action_fields) if w), None)
            if held:
                add(advisory, "N17", "speaking shot", speech_label,
                    "%s speaks, but the panel holds the expression %s, which freezes the mouth; "
                    "describe the speaking instead" % (_q(speaker), _q(held)))
            others = [p for p in on_screen if p.lower() != speaker.lower()]
            if speech_label == "Dialogue" and others:
                add(advisory, "N17", "speaking shot", "Dialogue",
                    "%s speaks in a shot that also shows %s; a speaking shot shows only the "
                    "speaker" % (_q(speaker), ", ".join(_q(p) for p in others)))
            for sentence in _sentences(writers.get(action_label, "")):
                move = CAMERA_MOTION_RE.search(sentence)
                if (move and lib._is_camera_sentence(sentence, known)
                        and " ".join(move.group(0).lower().split()) not in STILL_CAMERA_MOVES):
                    add(advisory, "N17", "speaking shot", action_label,
                        "has the camera direction %s while %s speaks; while someone speaks the "
                        "camera stays static, pushes in, pulls back or tracks them, so their face "
                        "stays readable" % (_q(sentence), _q(speaker)))
                    break
    if "N14" in ids:
        if plan:
            narration = lib.split_speaker(narration, [c["phrase"] for c in plan["cast"]])[1]
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


# Narrative dialogue fidelity spec QL10: a quoted spoken line of the narrative is missing from
# every panel's Dialogue:, or is spoken out of order. Hard and blocking; story scope.
Q1_MISSING = ("story: Q1 spoken line: the narrative's spoken line %d \"%s\" is in no panel's "
              "Dialogue:; give it word for word to the panel that shows it being said (Dialogue: "
              "<speaker's referring phrase>: <the line>)")
Q1_ORDER = ("story: Q1 spoken line: the narrative's spoken line %d \"%s\" is spoken out of the "
            "narrative's order; the Dialogue: fields must say the spoken lines in the order the "
            "narrative gives them")


def _find_run(words, run, start):
    """The first j >= start with words[j:j + len(run)] == run, else None."""
    for j in range(start, len(words) - len(run) + 1):
        if words[j:j + len(run)] == run:
            return j
    return None


def spoken_line_problems(ctx, lib, phrases, dialogues):
    """The Q1 violations of a story (QL10), in line order. dialogues is one Dialogue: value per
    panel, in order ("" for none); a value that names no known phrase counts as empty. Each
    required line must lie, word for word (line_words: case and punctuation ignored), inside one
    panel's line, later than the line before it; a line found only earlier is out of order."""
    required = required_lines(ctx)
    if not required:
        return []
    found = []
    for value in dialogues:
        phrase, line = (lib.parse_dialogue(value, phrases)[:2] if value.strip()
                        else (None, ""))
        found.append(line_words(line) if phrase else [])
    kpos, jpos, out = 0, 0, []
    for i, text in enumerate(required, start=1):
        run = line_words(text)
        hit = None
        for p in range(kpos, len(found)):
            j = _find_run(found[p], run, jpos if p == kpos else 0)
            if j is not None:
                hit = (p, j)
                break
        if hit:
            kpos, jpos = hit[0], hit[1] + len(run)
            continue
        anywhere = any(_find_run(words, run, 0) is not None for words in found)
        out.append((Q1_ORDER if anywhere else Q1_MISSING) % (i, text))
    return out


GENERATION_CHECKS = ("N1", "N2", "N3", "N4", "N5", "N6", "N7", "N8", "N9", "N10", "N11", "N12",
                     "N14", "N15", "N16", "N17", "N18", "T1", "T2", "T3", "Q1", "N19")


def panel_checks(ctx, plan, parts, text, story_md_path):
    """(hard, advisory) of an assembled story (RS15; dialogue spec 6.3): per panel the
    _field_checks classes; plan-scope N10 is advisory; in shots mode S1 and S3 are hard and every
    other character_lib.shots_violations rule joins shots_advisories in advisory. story_md_path
    holds text (written by the caller) and is parsed with bin/ltx-story-manifest's
    _parse_prompts_md."""
    lib = _character_lib(ctx.ws)
    undeclared = undeclared_characters(ctx)
    hard, advisory = [], []
    writers_by_panel = []
    dialogues = []
    for k in range(1, len(parts) + 1):
        fields = panel_fields(ctx, plan, parts, k)
        dialogues.append(dict(fields).get("Dialogue", ""))
        writers = {LABELS[key]: parts[k - 1].get(key, "") for key in panel_keys(ctx, plan, k)
                   if key != "title"}
        writers_by_panel.append(writers)
        h, a = _field_checks(ctx, lib, plan, k, parts[k - 1]["title"], fields, writers,
                             GENERATION_CHECKS, undeclared)
        hard += h
        advisory += a
    advisory = plan_copied_examples(plan) + _order_by_panel(
        advisory + repeat_advisories(ctx, lib, plan, writers_by_panel))
    if "Q1" in GENERATION_CHECKS:
        hard += spoken_line_problems(ctx, lib, cast_phrases(ctx, plan), dialogues)
    if ctx.mode == "shots":
        panels = _story_manifest(ctx.ws)._parse_prompts_md(story_md_path)[1]
        shots_hard, shots_other = split_shots(lib.shots_violations(
            text, panels, ctx.panels, ctx.members, ctx.narration is True, ignore_facing=True))
        hard += shots_hard
        advisory += shots_other + lib.shots_advisories(panels, ctx.members)
    return hard, advisory


def _order_by_panel(lines):
    """Panel advisories sorted by panel, then N12, N13, N14, N16, N17 (stable)."""
    order = {"N12": 0, "N13": 1, "N14": 2, "N16": 3, "N17": 4}
    return sorted(lines, key=lambda l: (int(l.split(":", 1)[0].split()[1]),
                                        order.get(l.split()[2], 3)))


SHOTS_HARD_RULES = ("S1", "S3")


def split_shots(violations):
    """(the S1/S3 violations, the other S rules) of a character_lib.shots_violations list: in the
    robust engine only S1 and S3 are hard (dialogue spec 6.3)."""
    return ([v for v in violations if parse_violation(v)["id"] in SHOTS_HARD_RULES],
            [v for v in violations if parse_violation(v)["id"] not in SHOTS_HARD_RULES])


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
    speaks = panel_speaks(ctx, plan, k)
    phrase = speaker_phrase(plan, k) if speaks else None
    words = str(_character_lib(ctx.ws).dialogue_word_cap(engine_seconds(ctx), 1)) if speaks else ""
    assigned = assigned_dialogue(plan, k)
    key_lines = []
    for key in panel_keys(ctx, plan, k):
        if key == "title":
            line = KEY_LINE_TEMPLATES["title"]
        elif key == "narration":
            line = KEY_LINE_TEMPLATES["narration_with_dialogue" if speaks else "narration"]
        elif key == "dialogue":
            line = KEY_LINE_TEMPLATES["dialogue_fixed" if assigned else "dialogue"]
        elif ctx.mode == "chained":
            line = KEY_LINE_TEMPLATES["chained_image" if key == "image" else
                                      "chained_motion1" if k == 1 else "chained_motion"]
        elif key == "prompt" and speaks:
            line = KEY_LINE_TEMPLATES["no_stills_prompt_speaking"]
        else:
            line = KEY_LINE_TEMPLATES["%s_%s" % (ctx.mode, key)]
        if key in ("image", "motion", "prompt") and ctx.narration == "speech":
            line += SPEECH_FRAMING_SENTENCE
        if speaks:
            line += SPEAKING_SENTENCES.get(key, "")
        if key in targets:
            line = line.replace("W1", str(targets[key][0]), 1).replace("W2", str(targets[key][1]), 1)
        if speaks:
            line = (line.replace("@@SPEAKER@@", '"%s"' % phrase).replace("@@DWORDS@@", words)
                    .replace("@@LINE@@", '"%s"' % assigned))
        key_lines.append(line)
    fix_block = ""
    if fix is not None:
        keys = panel_keys(ctx, plan, k)
        current = parts[k - 1] if k <= len(parts) and parts[k - 1] else {}
        fix_block = ("Your previous version of this panel was rejected. Problems:\n"
                     + "\n".join("- " + m for m in fix[:MAX_LISTED])
                     + FIX_INSTRUCTION
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


def unparseable_panel_problem(mode, k, narration=True, speaks=False):
    return ("the reply is not one JSON object with the keys %s"
            % ", ".join(writer_keys(mode, k, narration, speaks)))


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
    "Problems the pipeline's own checks found in this draft. Only the [hard] ones are fixed by "
    "patches; the [advisory] ones are reported to the user and must never be patched:\n"
    "@@VIOLATIONS@@\n"
    "\n"
    "Score the draft from 1 (worst) to 10 (best) on each of:\n"
    "- continuity: characters, places, objects and positions stay consistent from panel to "
    "panel.\n"
    "- story: the panels tell the narrative@@GOAL_CLAUSE@@, with a clear introduction, climax "
    "and resolution, and every panel moves the action forward.\n"
    "- renderability: every panel shows physical action that a video model can render in "
    "@@SECONDS@@ seconds -- neither more actions than fit nor none -- every spoken line fits its "
    "clip, and there is no on-screen text and nothing outside the frame. Camera directions and "
    "dialogue are part of a good panel, never a fault.\n"
    "\n"
    "Then propose at most 8 patches, most important first, only for the [hard] problems: a "
    "spoken line that does not fit its clip, or a panel with more or fewer actions than its clip "
    "can hold. Each patch is an object with exactly the keys target, index, field, reason and "
    "replacement. The allowed patches are:\n"
    "@@FIELD_LINES@@\n"
    "Preserve every camera direction, every descriptive sentence and every dialogue line word for "
    "word, except a spoken line that a [hard] T1 or N18 problem names: change only the sentence or sentences that cause the problem, and copy every other "
    "sentence of the field unchanged. A patch that changes anything else is rejected. A panel "
    "replacement holds only the text the writer writes: never include a character's description, "
    "a setting sentence or the shot type, because the pipeline adds those itself. The number of "
    "panels, the characters' referring phrases and their descriptions never change.\n"
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


def listed(lines):
    """At most MAX_LISTED lines, then "- ... and N more"."""
    if len(lines) <= MAX_LISTED:
        return list(lines)
    return list(lines[:MAX_LISTED]) + ["- ... and %d more" % (len(lines) - MAX_LISTED)]


def critic_field_lines(mode, catalog_lines, narration=True):
    """The allowed-patch lines of the critic prompt (dialogue spec 8.3): the lora line when
    catalog_lines is set, the Motion: (Prompt: in no_stills) line for a T2/T3 panel, and the
    dialogue line for a T1 panel unless the movie has no spoken lines."""
    lines = []
    if catalog_lines:
        lines.append('- target "plan", field "lora", index 0 for the global picks or a beat '
                     "number for that beat's own picks: replacement is the complete new list of "
                     "picks, each an object with the keys id and strength, from this catalog:"
                     + "\n" + "\n".join(catalog_lines))
    label = "Prompt" if mode == "no_stills" else "Motion"
    lines.append('- target "panel", field "%s", index = the panel number, only for a panel with a '
                 "[hard] T2 or T3 problem: replacement is the panel's whole new %s: writer text, "
                 "identical to the current text except for the sentence or sentences that hold "
                 "the extra or missing action." % (label.lower(), label))
    if narration is not False:
        lines.append('- target "panel", field "dialogue", index = the panel number, only for a '
                     "panel with a [hard] T1 or N18 problem: replacement is the shortened spoken line, "
                     "without the speaker's phrase and without quotation marks, within the limit "
                     "the T1 problem states.")
    return "\n".join(lines)


def build_critic_prompt(plan, story_md_text, violations, catalog_lines=None, for_judge=False,
                        narration=True):
    """The exact critic prompt of RS17. violations is (hard, advisory) of the judged state;
    mode, panels, seconds, narrative, goal and story_id come from the plan; narration False
    leaves out the narration patch target."""
    hard, advisory = violations
    lines = listed(["- [hard] " + m for m in hard] + ["- [advisory] " + m for m in advisory])
    plan_json = json.dumps({k: plan[k] for k in ("title", "logline", "cast", "locations", "props",
                                                 "beats", "loras")}, indent=1, ensure_ascii=False)
    fragments = [
        ("@@GOAL_PARAGRAPH@@", _goal_paragraph(plan["goal"])),
        ("@@MODE_PARAGRAPH@@", MODE_PARAGRAPHS[plan["mode"]]),
        ("@@VIOLATIONS@@", "\n".join(lines) if lines else "- none"),
        ("@@GOAL_CLAUSE@@", " and serve the target output goal" if plan["goal"] else ""),
        ("@@FIELD_LINES@@", critic_field_lines(plan["mode"], catalog_lines, narration)),
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


NOT_REPAIRED = "advisory"
NOT_REPAIRED_REASON = ("not repaired automatically: only spoken timing and the amount of action "
                       "are patched")


def patch_ranges(ctx, plan, lora_allowed):
    """{(target, field): (lo, hi) | None | NOT_REPAIRED} (dialogue spec PG1) -- None means "field
    not allowed in this mode"; NOT_REPAIRED marks a field that is never patched (it only ever
    holds advisory findings)."""
    n, mode = ctx.panels, ctx.mode
    return {("plan", "beat.action"): NOT_REPAIRED,
            ("plan", "beat.shot"): NOT_REPAIRED,
            ("plan", "beat.camera"): NOT_REPAIRED,
            ("plan", "location.setting"): NOT_REPAIRED,
            ("plan", "lora"): (0, n) if lora_allowed else None,
            ("panel", "image"): NOT_REPAIRED,
            ("panel", "motion"): (1, n) if mode != "no_stills" else None,
            ("panel", "prompt"): (1, n) if mode == "no_stills" else None,
            ("panel", "dialogue"): (1, n) if ctx.narration is not False else None,
            ("panel", "narration"): NOT_REPAIRED}


def _patch_problem(ranges, patch):
    if not isinstance(patch, dict) or not all(k in patch for k in PATCH_KEYS):
        return "not an object with the keys target, index, field, reason and replacement"
    key = (patch["target"], patch["field"])
    if not all(isinstance(v, str) for v in key) or key not in ranges:
        return "unknown target or field"
    span = ranges[key]
    if span == NOT_REPAIRED:
        return NOT_REPAIRED_REASON
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


def apply_patches(ctx, state, patches, lora_allowed=None, repairable=None):
    """(new_state, applied, rejected) for a state {"plan", "parts"} and a patch list (RS20;
    dialogue spec PG1-PG4). Works on a deep copy; rejected items are {"patch", "reason"}.
    repairable is {panel: set of hard ids} of the judged state, or None for no restriction: a
    motion or prompt patch needs a T2 or T3 on its panel, a dialogue patch a T1. A motion or
    prompt replacement must pass the PG3 sentence guard; a dialogue replacement must fit the
    clip (PG4)."""
    new = copy.deepcopy(state)
    plan, parts = new["plan"], new["parts"]
    lib = _character_lib(ctx.ws)
    if lora_allowed is None:
        lora_allowed = lora_patches_allowed(ctx)
    ranges = patch_ranges(ctx, plan, lora_allowed)
    applied, rejected = [], []
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
        index = patch["index"]
        before = sum(lora_checks(ctx, plan, compatible_by_id, catalog_by_id), [])
        saved = copy.deepcopy(plan["loras"])
        if index == 0:
            plan["loras"]["global"] = patch["replacement"]
        elif patch["replacement"]:
            plan["loras"]["per_beat"][str(index)] = patch["replacement"]
        else:
            plan["loras"]["per_beat"].pop(str(index), None)
        broken = [h for h in sum(lora_checks(ctx, plan, compatible_by_id, catalog_by_id), [])
                  if h not in before]
        if broken:
            plan["loras"] = saved
            rejected.append({"patch": patch, "reason": "would break " + broken[0]})
            continue
        applied.append(patch)
    for patch in accepted:
        if patch["target"] != "panel":
            continue
        k, field = patch["index"], patch["field"]
        need = {"T1", "N18"} if field == "dialogue" else {"T2", "T3"}
        if repairable is not None and not (repairable.get(k, set()) & need):
            rejected.append({"patch": patch, "reason": "panel %d has no hard timing or "
                                                       "amount-of-action problem; advisory "
                                                       "findings are never patched" % k})
            continue
        if field == "dialogue":
            text = _sentence(_clean_dialogue(lib, clean_writer(lib, patch["replacement"]),
                                             speaker_phrase(plan, k)))
            problem = line_problem(ctx, lib, text) if text else "empty after cleanup"
        else:
            text = clean_writer(lib, patch["replacement"],
                                pasted_pieces(ctx, plan, k).get(field, ()))
            problem = (guard_problem(ctx, plan, parts[k - 1].get(field, ""), text) if text
                       else "empty after cleanup")
        if problem:
            rejected.append({"patch": patch, "reason": problem})
            continue
        parts[k - 1][field] = text
        applied.append(patch)
    return new, applied, rejected


def repairable_ids(hard):
    """{panel number: set of its hard violation ids} (dialogue spec PG2)."""
    out = {}
    for message in hard:
        violation = parse_violation(message)
        if violation["scope"] == "panel" and violation["index"]:
            out.setdefault(violation["index"], set()).add(violation["id"])
    return out


# ---------------------------------------------------------------------------
# The run: plan calls (RS8), panel calls (RS13), the round controller (RS21), ranking (RS22),
# budgets and the wall clock (RS23), outputs (RS25-RS27)
# ---------------------------------------------------------------------------

# Dialogue spec 6.1: T2 and T3 trigger repair but never block; every other hard violation blocks.
NON_BLOCKING_IDS = ("T2", "T3")
# The hard ids a code-only round sends back to the panel writer (PG5).
REPAIR_IDS = ("N11", "T1", "T2", "T3")


def blocking(messages):
    """The hard violations among messages that block the story (dialogue spec 6.1)."""
    return [m for m in messages if parse_violation(m)["id"] not in NON_BLOCKING_IDS]


def unresolved(messages):
    """The hard violations among messages that never block: T2 and T3 (dialogue spec 6.1)."""
    return [m for m in messages if parse_violation(m)["id"] in NON_BLOCKING_IDS]


def n_blocking(state):
    return len(blocking(state["hard"]))


def guard_problem(ctx, plan, old, new):
    """Why replacing the writer action text old with new (already cleaned) is rejected, or None
    (dialogue spec PG3): only one contiguous run of at most max(1, units - max_actions) sentences
    of old may change, every other sentence is kept word for word, and a camera sentence of that
    run must survive into the new run."""
    lib = _character_lib(ctx.ws)
    phrases = cast_phrases(ctx, plan)
    a, b = _sentences(old), _sentences(new)
    p = 0
    while p < min(len(a), len(b)) and a[p] == b[p]:
        p += 1
    s = 0
    while s < min(len(a), len(b)) - p and a[len(a) - 1 - s] == b[len(b) - 1 - s]:
        s += 1
    old_span, new_span = a[p:len(a) - s], b[p:len(b) - s]
    _actions, units, most = action_units(ctx, lib, old, phrases)
    limit = max(1, units - most)
    if len(old_span) > limit:
        return ("the patch changes %d sentences; it may change at most %d contiguous sentence(s) "
                "and must keep every other sentence word for word" % (len(old_span), limit))
    for sentence in old_span:
        if lib._is_camera_sentence(sentence, phrases) and sentence not in new_span:
            return "the patch drops the camera direction %s" % _q(sentence)
    return None


def line_problem(ctx, lib, line):
    """The PG4 reason a new spoken line does not fit this clip, else None."""
    n = len(lib.split_fragments(line))
    words = len(line.split())
    cap = lib.dialogue_word_cap(engine_seconds(ctx), n)
    if words > cap or n > lib.DIALOGUE_MAX_FRAGMENTS:
        return ("the new line is %d words in %d sentences; at most %d words in %d sentences fit "
                "this clip" % (words, n, cap, n))
    return None


def merge_repair(ctx, plan, k, old, new, ids):
    """Panel k's writer parts after a code-only round (dialogue spec PG5): new's motion or prompt
    when ids has T2 or T3 and the PG3 guard accepts it, new's dialogue when ids has T1 and the
    line fits, new's narration when ids has N11; every other part keeps old's text."""
    merged = dict(old)
    action = "prompt" if ctx.mode == "no_stills" else "motion"
    if (ids & {"T2", "T3"} and new.get(action)
            and guard_problem(ctx, plan, old.get(action, ""), new[action]) is None):
        merged[action] = new[action]
    if ("T1" in ids and new.get("dialogue")
            and line_problem(ctx, _character_lib(ctx.ws), _sentence(new["dialogue"])) is None):
        merged["dialogue"] = new["dialogue"]
    if "N11" in ids and "narration" in new:
        merged["narration"] = new["narration"]
    return merged


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
    return (n_blocking(states[i]), len(states[i]["hard"]), -low, -total)


def better(states, a, b):
    """True when states[a] is strictly better than states[b] (RS21)."""
    return _key(states, a) < _key(states, b)


def _new_rs37(states, i):
    """1 when states[i] has a P13 or N15 violation (hard or advisory) that round 0 does not have
    (a patch or a rewrite introduced an undeclared library character), else 0."""
    base = set(states[0]["hard"] + states[0]["advisory"])
    return int(any(parse_violation(m)["id"] in ("P13", "N15") and m not in base
                   for m in states[i]["hard"] + states[i]["advisory"]))


def best_round(states):
    """The index of the state with the smallest (blocking, hard, new P13/N15, -min, -total,
    -round) (RS22; dialogue spec 6.4: blocking first, so a T1 state never beats T2-only ones)."""
    return min(range(len(states)),
               key=lambda i: (n_blocking(states[i]), len(states[i]["hard"]), _new_rs37(states, i))
               + _key(states, i)[2:] + (-i,))


def final_outcome(states):
    """(best round, its blocking violations, its unresolved T2/T3 violations) (dialogue spec 6.5)."""
    best = best_round(states)
    return best, blocking(states[best]["hard"]), unresolved(states[best]["hard"])


def _checks_doc(ctx, state, source="robust"):
    return {"schema": CHECKS_SCHEMA, "story_id": ctx.story_id, "mode": ctx.mode,
            "panels": ctx.panels, "checked_at": _utc(), "source": source,
            "round": state["round"] if source == "robust" else None,
            "hard": [parse_violation(m) for m in state["hard"]], "unresolved": [],
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
        self.critic_rounds_run = 0
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
                problems = hard + line_assignment_problems(plan)
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
            dict([("index", k)] + [(key, p.get(key, "")) for key in panel_keys(ctx, plan, k)])
            for k, p in enumerate(parts, start=1)]})
        _write_json(os.path.join(rdir, "story_checks.json"), _checks_doc(ctx, state))
        print("round %d: %d hard, %d advisory" % (rnd, len(state["hard"]), len(state["advisory"])))
        self.states.append(state)
        return state

    # -- critic rounds ---------------------------------------------------------------------

    def critic_round(self, k, judged):
        """One round on states[judged] (RS21; dialogue spec 6.5, PG5, PG6). Returns "plateau",
        "time_cap" or None (a new state was appended)."""
        ctx = self.ctx
        prev = self.states[judged]
        rdir = os.path.join(self.rounds_dir, "round_%d" % k)
        lora_allowed = bool(self.catalog_lines) and any(
            parse_violation(m)["id"] in ("L1", "L5", "L6", "L7") for m in prev["hard"])
        base = build_critic_prompt(prev["plan"], prev["text"], (prev["hard"], prev["advisory"]),
                                   self.catalog_lines if lora_allowed else None,
                                   narration=self.ctx.narration)
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

            if judged >= 1 and not better(self.states, judged, judged - 1):
                _write_json(critic_path, critic)
                line(0, 0)
                return "plateau"
            new, applied, rejected = apply_patches(
                ctx, {"plan": prev["plan"], "parts": prev["parts"]}, reply["patches"],
                lora_allowed=lora_allowed, repairable=repairable_ids(prev["hard"]))
            critic["applied"], critic["rejected"] = applied, rejected
            _write_json(critic_path, critic)
            line(len(applied), len(rejected))
            self.make_state(k, new["plan"], new["parts"])
            return None
        print("critic round %d: no valid reply after %d call(s); code-only round" % (k, calls))
        _write_json(critic_path, critic)
        if judged >= 1 and ((n_blocking(prev), len(prev["hard"]))
                            >= (n_blocking(self.states[judged - 1]),
                                len(self.states[judged - 1]["hard"]))):
            return "plateau"
        parts = copy.deepcopy(prev["parts"])
        plan = copy.deepcopy(prev["plan"])
        for kk in range(1, ctx.panels + 1):
            mine = [m for m in prev["hard"] if parse_violation(m)["scope"] == "panel"
                    and parse_violation(m)["index"] == kk]
            ids = set(parse_violation(m)["id"] for m in mine)
            if not ids & set(REPAIR_IDS) or self.panel_calls[kk] >= PANEL_MAX_CALLS:
                continue
            if self.expired():
                self.time_up = True
                break
            new = self.panel_call(plan, parts, kk, k, mine)
            if new is not None:
                parts[kk - 1] = merge_repair(ctx, plan, kk, parts[kk - 1], new, ids)
        self.make_state(k, plan, parts)
        return None

    # -- judge -----------------------------------------------------------------------------

    def judge_gate(self):
        """bin/judge-story --patches on the best round, as a final report only (dialogue spec 6.8):
        skipped when the best round has a blocking violation; its patches stay in the
        judgment.patches.json it writes into that round's directory and are never applied."""
        ctx = self.ctx
        best = self.states[best_round(self.states)]
        if blocking(best["hard"]):
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
        if low < JUDGE_MIN_SCORE:
            print("Warning: judge-story minimum score %d is below %d; its patches are saved in %s "
                  "and were not applied (only spoken timing and the amount of action are repaired "
                  "automatically)" % (low, JUDGE_MIN_SCORE,
                                      os.path.join(best["dir"], "judgment.patches.json")))
        return {"status": "ok", "detail": "min score %d" % low, "scores": reply["scores"],
                "min_score": low, "applied": False}

    # -- the whole run ---------------------------------------------------------------------

    def critic_loop(self):
        """The critic rounds after round 0 (dialogue spec 6.5); returns the stop reason. A state
        with no hard violation stops at once, without a critic call; at most CRITIC_MAX_ROUNDS
        rounds run."""
        if not self.states[-1]["hard"]:
            return "passed"
        for k in range(1, CRITIC_MAX_ROUNDS + 1):
            if self.expired():
                return "time_cap"
            stop = self.critic_round(k, k - 1)
            if stop != "time_cap":
                self.critic_rounds_run += 1
            if stop:
                return stop
            if not self.states[-1]["hard"]:
                return "passed"
            if self.time_up:
                return "time_cap"
        return "max_rounds"

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
        problem = spoken_lines_problem(ctx)
        if problem:
            print("Error: %s" % problem, file=sys.stderr)
            return self.finish(2)
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
        parts = [empty_parts(ctx.mode, k, plan, ctx) for k in range(1, ctx.panels + 1)]
        valid = 0
        for k in range(1, ctx.panels + 1):
            if self.expired():
                return self.round0_timeout()
            new = self.panel_call(plan, parts, k, 0, None)
            if new is None and self.panel_calls[k] < PANEL_MAX_CALLS:
                if self.expired():
                    return self.round0_timeout()
                new = self.panel_call(plan, parts, k, 0, [unparseable_panel_problem(
                    ctx.mode, k, ctx.narration, bool(plan["beats"][k - 1]["speaker"]))])
            if new is not None:
                parts[k - 1] = new
                valid += 1
        if not valid:
            print("Error: the story model returned no valid panel in round 0; see %s"
                  % self.round_dir(0), file=sys.stderr)
            return self.finish(1)
        self.make_state(0, plan, parts)
        stop = self.critic_loop()
        judge = self.judge_gate() if ctx.judge else None
        best, blocking_list, unresolved_list = final_outcome(self.states)
        state = self.states[best]
        print("stop: %s; best round %d (%d hard)" % (stop, best, len(state["hard"])))
        doc = _checks_doc(ctx, state)
        doc.update({"hard": [parse_violation(m) for m in blocking_list],
                    "unresolved": [parse_violation(m) for m in unresolved_list],
                    "stop_reason": stop, "best_round": best, "judge": judge,
                    "rounds": [{"round": s["round"], "hard": len(s["hard"]),
                                "advisory": len(s["advisory"]), "scores": s["scores"],
                                "verdict": s["verdict"]} for s in self.states]})
        _write_json(os.path.join(ctx.story_dir, "plan.json"), state["plan"])
        _write_json(os.path.join(ctx.story_dir, "story_checks.json"), doc)
        _write_text(os.path.join(ctx.story_dir, "story.md"), state["text"])
        self.doc["stop_reason"], self.doc["best_round"] = stop, best
        self.advisories = state["advisory"]
        if not blocking_list:
            for message in unresolved_list:
                print("Warning: unresolved after %d critic round(s): %s"
                      % (self.critic_rounds_run, message))
            return self.finish(0)
        print("Error: story.md has %d hard violation(s) after the critic rounds (best round %d of "
              "%d):" % (len(blocking_list), best, len(self.states) - 1), file=sys.stderr)
        for message in blocking_list:
            print("  - %s" % message, file=sys.stderr)
        if unresolved_list:
            print("Also unresolved (not blocking):", file=sys.stderr)
            for message in unresolved_list:
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


# ---------------------------------------------------------------------------
# Re-check of an existing story.md (RS28) and the plan-free yardstick (RS28, 7.2)
# ---------------------------------------------------------------------------

RECHECK_IDS = ("N1", "N2", "N3", "N4", "N7", "N8", "N9", "N10", "N11", "N12", "N14", "N15",
               "N16", "N17", "N18", "T1", "T2", "T3", "Q1", "N19")
PLAN_FREE_IDS = ("N1", "N7", "N8", "N9", "N10", "N11", "N15")
_PLAN_KEYS = ("title", "logline", "cast", "locations", "props", "beats", "loras")


def load_plan(ctx):
    """<story_dir>/plan.json when it is a valid plan for ctx's mode and panel count, else None."""
    try:
        with open(os.path.join(ctx.story_dir, "plan.json"), encoding="utf-8") as f:
            plan = json.load(f)
    except (OSError, ValueError):
        return None
    if (not isinstance(plan, dict) or plan.get("schema") != PLAN_SCHEMA
            or plan.get("mode") != ctx.mode or plan.get("panels") != ctx.panels
            or not all(k in plan for k in _PLAN_KEYS)):
        return None
    for beat in plan["beats"] if isinstance(plan["beats"], list) else []:
        if isinstance(beat, dict):
            beat.setdefault("speaker", "")
            beat.setdefault("lines", [])
    plan.setdefault("spoken_lines", [])
    plan.setdefault("cast_notes", [])
    plan.setdefault("speech_notes", [])
    return plan


def story_fields(mode, k, panel, narration=True):
    """[(Label, text)] of a parsed story.md panel: the fields RS3 assembles for mode/panel k, a
    Dialogue: whenever the panel has one (every mode, every narration value; dialogue spec SP4),
    and no Narration when narration is False."""
    if mode == "no_stills":
        labels = ["Prompt"]
    elif mode == "chained" and k >= 2:
        labels = ["Motion"]
    else:
        labels = ["Image", "Motion"]
    if panel.get("dialogue", "").strip():
        labels.append("Dialogue")
    if narration:
        labels.append("Narration")
    return [(label, panel[label.lower()]) for label in labels]


def _recheck_writers(ctx, lib, plan, k, fields):
    """{Label: text} for a re-check: each field's text with the plan's pasted sentences for panel
    k removed by the RS13 cleanup, so N4, N7-N10, N12 and N13 judge the writer text they judged
    when the story was generated. A panel past the plan's beats keeps its whole field text."""
    if k > len(plan["beats"]):
        return dict(fields)
    pasted = pasted_pieces(ctx, plan, k)
    return dict((label, clean_writer(lib, text, pasted.get(label.lower(), ())))
                for label, text in fields)


def _read_story(ctx, story_md):
    with open(story_md, encoding="utf-8") as f:
        text = f.read()
    return text, _story_manifest(ctx.ws)._parse_prompts_md(story_md)[1]


def plan_free_report(story_md, mode, panels, members, legacy_validate, ws=None):
    """(hard, advisory) of a re-check without a plan (RS28; the 7.2 yardstick for both engines;
    dialogue spec 6.4): hard is legacy_validate (not shots), the hard part of _field_checks and
    S1/S3 (shots); advisory is the rest, N15 included. ws (default: this file's directory)
    locates the character library and the manifest parser. Prints nothing, writes nothing."""
    ws = ws or os.path.dirname(os.path.realpath(__file__))
    ctx = StoryContext(ws=ws, story_id="", story_dir=os.path.dirname(story_md), mode=mode,
                       panels=panels, seconds="6", narrative="", goal=None, members=members,
                       seed_image=None, seed_agent_image=None, story_model=None,
                       context_window=None, video_model="", auto_lora=False,
                       catalog={"schema_version": 1, "entries": []}, pinned=[], stills_pinned=[],
                       judge=False)
    lib = _character_lib(ws)
    hard = [] if mode == "shots" else list(legacy_validate(story_md, panels, mode == "no_stills"))
    advisory = []
    text, parsed = _read_story(ctx, story_md)
    undeclared = undeclared_characters(ctx)
    for k, panel in enumerate(parsed, start=1):
        fields = story_fields(mode, k, panel)
        h, a = _field_checks(ctx, lib, None, k, panel["title"], fields, dict(fields),
                             PLAN_FREE_IDS, undeclared)
        hard += h
        advisory += a
    if mode == "shots":
        shots_hard, shots_other = split_shots(lib.shots_violations(text, parsed, panels, members,
                                                                    ignore_facing=True))
        hard += shots_hard
        advisory += shots_other
    return hard, advisory


def _undeclared_gate(ctx, story_md, legacy_validate, passed):
    """passed, after a Warning line for every N15 of plan_free_report (a library character
    story.md names but --character did not declare; advisory, RS37 and dialogue spec Q1)."""
    for v in plan_free_report(story_md, ctx.mode, ctx.panels, ctx.members, legacy_validate,
                              ws=ctx.ws)[1]:
        if " N15 " in v:
            print("Warning: %s" % v)
    return passed


def recheck(ctx, legacy_validate):
    """Re-check an existing story.md instead of regenerating it (RS28; dialogue spec 6.7).
    Returns (exit code, advisories): 2 only when a blocking violation remains (unresolved T2/T3
    only warn). legacy_validate is bin/ltx-movie's _validate_story_md."""
    story_md = os.path.join(ctx.story_dir, "story.md")
    for warning in catalog_warnings(ctx):
        print(warning)
    lib = _character_lib(ctx.ws)
    plan = load_plan(ctx)
    if plan is not None:
        try:
            hard = ([] if ctx.mode == "shots"
                    else list(legacy_validate(story_md, ctx.panels, ctx.mode == "no_stills")))
            advisory = []
            text, parsed = _read_story(ctx, story_md)
            undeclared = undeclared_characters(ctx)
            writers_by_panel = []
            for k, panel in enumerate(parsed, start=1):
                fields = story_fields(ctx.mode, k, panel, ctx.narration)
                writers = _recheck_writers(ctx, lib, plan, k, fields)
                writers_by_panel.append(writers)
                h, a = _field_checks(ctx, lib, plan, k, panel["title"], fields, writers,
                                     RECHECK_IDS, undeclared)
                hard += h
                advisory += a
            hard += spoken_line_problems(ctx, lib, cast_phrases(ctx, plan),
                                         [p.get("dialogue", "") for p in parsed])
            advisory = _order_by_panel(advisory + repeat_advisories(ctx, lib, plan, writers_by_panel))
            if ctx.mode == "shots":
                shots_hard, shots_other = split_shots(lib.shots_violations(
                    text, parsed, ctx.panels, ctx.members, ctx.narration is True,
                    ignore_facing=True))
                hard += shots_hard
                advisory += shots_other + lib.shots_advisories(parsed, ctx.members)
            if ctx.auto_lora:
                compatible = dict((e["id"], e) for e in compatible_entries(ctx))
                catalog = dict((e["id"], e) for e in ctx.catalog.get("entries", []))
                lh, la = lora_checks(ctx, plan, compatible, catalog)
                hard += lh
                advisory += la
            blocking_list, unresolved_list = blocking(hard), unresolved(hard)
            doc = _checks_doc(ctx, {"hard": blocking_list, "advisory": advisory},
                              source="recheck")
            doc["unresolved"] = [parse_violation(m) for m in unresolved_list]
            _write_json(os.path.join(ctx.story_dir, "story_checks.json"), doc)
            if blocking_list:
                print("Error: story.md fails the story checks:", file=sys.stderr)
                for message in blocking_list:
                    print("  - %s" % message, file=sys.stderr)
                print("Hand-edit %s to fix the violations above and rerun, or pass --force-story to "
                      "regenerate it." % story_md, file=sys.stderr)
                if any(parse_violation(m)["id"].startswith("L") for m in blocking_list):
                    print("The L violations come from plan.json's catalog LoRA picks, not from "
                          "story.md: restore or re-add the LoRA files (bin/lora-catalog verify), "
                          "rerun with --no-auto-lora, or pass --force-story to regenerate.",
                          file=sys.stderr)
                return 2, advisory
            for message in unresolved_list:
                print("Warning: unresolved: %s" % message)
            return 0, advisory
        except (KeyError, TypeError, AttributeError, ValueError, IndexError):
            print("note: %s is malformed; re-checking story.md without it"
                  % os.path.join(ctx.story_dir, "plan.json"))
    if ctx.mode != "shots":
        violations = legacy_validate(story_md, ctx.panels, ctx.mode == "no_stills")
        if violations:
            print("Error: story.md failed validation:", file=sys.stderr)
            for v in violations:
                print("  - %s" % v, file=sys.stderr)
            print("Hand-edit %s to fix the violations above and rerun; story.md already exists "
                  "so Phase 1 will be skipped next time (pass --force-story to regenerate it "
                  "instead)." % story_md, file=sys.stderr)
            return 1, []
        return _undeclared_gate(ctx, story_md, legacy_validate, (0, []))
    try:
        text, parsed = _read_story(ctx, story_md)
        violations, others = split_shots(lib.shots_violations(text, parsed, ctx.panels,
                                                              ctx.members, ctx.narration is True,
                                                              ignore_facing=True))
        advisories = others + lib.shots_advisories(parsed, ctx.members)
    except OSError as e:
        violations, advisories = ["story: cannot read story.md: %s" % e], []
    if violations:
        print("Error: story.md breaks the shot rules:", file=sys.stderr)
        for v in violations:
            print("  - %s" % v, file=sys.stderr)
        print("Hand-edit %s to fix the violations above and rerun, or pass --force-story to "
              "have the story model write a new one." % story_md, file=sys.stderr)
        return 2, []
    return _undeclared_gate(ctx, story_md, legacy_validate, (0, advisories))
