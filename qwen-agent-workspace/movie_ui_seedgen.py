"""movie_ui_seedgen -- the seed generator's pure core: the Seeds tab's request rules, the seed
folder rule, the run ID, Keep's file names and the seed_edit capability shape
(docs/superpowers/specs/2026-11-02-seed-generator-design.md, deliverable G4, Section 5.1).

Standard library plus movie_ui_lib only (SG1). Valid on Python 3.9 and 3.13. This module never
writes and never starts a process. Every function is pure except new_run_id, which reads the
clock and draws random digits.
"""

import re
import secrets
import time

import movie_ui_lib as lib

PROMPT_MAX = 2000
CANDIDATES_MAX = 4
CANDIDATES_DEFAULT = 4
STRENGTH_MIN, STRENGTH_MAX, STRENGTH_DEFAULT = 0.10, 0.90, 0.45
SEED_MAX = 2147483647
MIN_FREE_GIB = 2.0
RUNS_MAX = 200
MODELS = {"zimage": "Z-Image", "qwen": "Qwen-Image-Edit"}
RUN_ID_RE = re.compile(r"^se-[0-9]{8}-[0-9]{6}-[0-9a-f]{4}$")
FOLDER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
STILL_RE = re.compile(r"^char_[0-9]{2}\.png$")          # movie_ui_server.STILL_FILE_RE
IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".webp")
SOURCE_NAMES = ("source.png", "source.jpg", "source.webp")
FOLDER_MSG = ("folder must be 1 to 64 letters, digits, '.', '_' or '-', start with a letter or digit, "
              "contain no '..' and not be 'runs'")
SOURCE_MSG = "source must be {upload_id}, {run, n} or {character, still}"


def _absent(body, key):
    return body.get(key) is None


def _source(value):
    """SG33 rows 10-14: (clean source, None) or (None, error)."""
    keys = set(value) if isinstance(value, dict) else None
    if keys == {"upload_id"} and isinstance(value["upload_id"], str):
        upload_id = value["upload_id"]
        if not lib.UPLOAD_ID_RE.fullmatch(upload_id):
            return None, "source upload %s not found" % upload_id
        return {"kind": "upload", "upload_id": upload_id}, None
    if keys == {"run", "n"} and isinstance(value["run"], str) and lib._is_int(value["n"]):
        run, n = value["run"], value["n"]
        if not RUN_ID_RE.fullmatch(run):
            return None, "unknown source run %s" % run
        if not 1 <= n <= CANDIDATES_MAX:
            return None, "source run %s has no ok candidate %s" % (run, n)
        return {"kind": "run", "run": run, "n": n}, None
    if keys == {"character", "still"} and isinstance(value["character"], str) and isinstance(value["still"], str):
        character, still = value["character"], value["still"]
        if not (lib.CHARACTER_NAME_RE.fullmatch(character) and STILL_RE.fullmatch(still)):
            return None, "unknown character still %s/%s" % (character, still)
        return {"kind": "character", "character": character, "still": still}, None
    return None, SOURCE_MSG


def validate_run_request(body):
    """SG33: (clean, None) or (None, error) for a POST /api/seeds/runs body (a dict); the first
    failing rule only, in the spec's order. Extra keys are ignored."""
    prompt = body.get("prompt")
    if not isinstance(prompt, str) or not prompt.strip():
        return None, "prompt is required"
    if len(prompt) > PROMPT_MAX:
        return None, "prompt is longer than 2000 characters"
    if not lib._argv_safe(prompt):
        return None, "prompt contains invalid characters"
    if prompt.strip().startswith("-"):
        return None, "prompt must not start with '-'"
    model = body.get("model")
    if model not in MODELS:
        return None, "model must be zimage or qwen"
    strength = body.get("strength")
    if model == "qwen" and not _absent(body, "strength"):
        return None, "strength is only for zimage"
    if model == "zimage" and not _absent(body, "strength") and not (
            lib._is_number(strength) and STRENGTH_MIN <= strength <= STRENGTH_MAX):
        return None, "strength must be a number from 0.10 to 0.90"
    candidates = body.get("candidates")
    if not _absent(body, "candidates") and not (lib._is_int(candidates) and 1 <= candidates <= CANDIDATES_MAX):
        return None, "candidates must be an integer from 1 to 4"
    seed = body.get("seed")
    if not _absent(body, "seed") and not (lib._is_int(seed) and 0 <= seed <= SEED_MAX):
        return None, "seed must be an integer from 0 to 2147483647"
    source, error = _source(body.get("source"))
    if error is not None:
        return None, error
    if model == "zimage":
        strength = STRENGTH_DEFAULT if strength is None else float(strength)
    else:
        strength = None
    return {"prompt": prompt, "model": model, "strength": strength,
            "candidates": CANDIDATES_DEFAULT if candidates is None else candidates,
            "seed": seed, "source": source}, None


def valid_folder(name):
    """SG34: a seed folder name: FOLDER_RE, no "..", and not "runs" in any case."""
    return (isinstance(name, str) and FOLDER_RE.fullmatch(name) is not None and ".." not in name
            and name.lower() != "runs")


def new_run_id():
    """SG35: "se-" + UTC %Y%m%d-%H%M%S + "-" + 4 hex digits (matches RUN_ID_RE)."""
    return "se-" + time.strftime("%Y%m%d-%H%M%S", time.gmtime()) + "-" + secrets.token_hex(2)


def keep_name(run, n, k):
    """SG35, SG51: the k-th candidate file name Keep tries for candidate n of run."""
    return "%s-%02d.png" % (run, n) if k == 1 else "%s-%02d-%d.png" % (run, n, k)


def capability(models, detail, checked):
    """SG36: the seed_edit capability from lib.seed_edit_check's (models, detail)."""
    if models is None:
        return {"ok": False, "reason": detail, "checked": checked, "models": None}
    ok = any(m["ok"] for m in models.values())
    reason = None if ok else "; ".join("%s: %s" % (MODELS[k], models[k]["reason"]) for k in ("zimage", "qwen"))
    return {"ok": ok, "reason": reason, "checked": checked, "models": models}


def availability_error(models, detail, model):
    """SG37: the 409 error for model, or None when it can run."""
    if models is None:
        return "cannot check the seed models: %s" % detail
    if not models[model]["ok"]:
        return "%s is unavailable: %s" % (MODELS[model], models[model]["reason"])
    return None
