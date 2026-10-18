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
