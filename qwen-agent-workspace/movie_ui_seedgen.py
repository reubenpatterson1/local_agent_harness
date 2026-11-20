"""movie_ui_seedgen -- the seed generator's pure core: the Seeds tab's request rules, the seed
folder rule, the run ID, Keep's file names and the seed_edit capability shape
(docs/superpowers/specs/2026-11-02-seed-generator-design.md, deliverable G4, Section 5.1), and the
Qwen model and LoRA registry with its selection rules
(docs/superpowers/specs/2026-11-02-seed-models-design.md, Sections 2 and 5.1). The registry is the
fixed models, the built-in LoRAs and the custom LoRAs read from user_loras_path()
(docs/superpowers/specs/2026-11-17-custom-edit-loras-design.md); bin/seed-edit and
bin/seed-edit-setup import it from here; the page gets it through the capability.

Standard library plus movie_ui_lib only (SG1). Valid on Python 3.9 and 3.13. This module never
writes and never starts a process. Every function is pure except new_run_id, which reads the
clock and draws random digits, and the registry lookups, which read the custom LoRA file through
user_loras (cached by its stat; an unusable file is warned about once on stderr).
"""

import json
import os
import re
import secrets
import sys
import threading
import time

import movie_ui_lib as lib

PROMPT_MAX = 2000
CANDIDATES_MAX = 4
CANDIDATES_DEFAULT = 4
STRENGTH_MIN, STRENGTH_MAX, STRENGTH_DEFAULT = 0.10, 0.90, 0.45
SEED_MAX = 2147483647
MIN_FREE_GIB = 2.0
RUNS_MAX = 200
MODELS = {"zimage": "Z-Image", "qwen": "Qwen-Image"}
RUN_ID_RE = re.compile(r"^se-[0-9]{8}-[0-9]{6}-[0-9a-f]{4}$")
FOLDER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
STILL_RE = re.compile(r"^char_[0-9]{2}\.png$")          # movie_ui_server.STILL_FILE_RE
IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".webp")
SOURCE_NAMES = ("source.png", "source.jpg", "source.webp")
FOLDER_MSG = ("folder must be 1 to 64 letters, digits, '.', '_' or '-', start with a letter or digit, "
              "contain no '..' and not be 'runs'")
SOURCE_MSG = "source must be {upload_id}, {run, n} or {character, still}"
QWEN_FAMILIES = {"qwen21": "Qwen-Image-2.1", "qwen2511": "Qwen-Image-Edit-2511"}
QWEN21_PATTERNS = ["model_index.json", "scheduler/*.json", "processor/**", "vae/*.json", "vae/*.safetensors",
                   "transformer/*.json", "transformer/*.safetensors", "text_encoder/*.json",
                   "text_encoder/*.safetensors"]          # mflux 0.24.0 QwenImage21WeightDefinition patterns
QWEN21_REQUIRED = ("vae/config.json", "transformer/config.json", "text_encoder/config.json")
QWEN_RESEARCH = "Qwen Research License (non-commercial)"
LIGHTNING = {"repo": "lightx2v/Qwen-Image-Edit-2511-Lightning",
             "revision": "107d238d68b8387e32843d0b4a2e24ceb0d3ad86",
             "file": "Qwen-Image-Edit-2511-Lightning-8steps-V1.0-bf16.safetensors",
             "bytes": 849608296, "scale": 1.0}
QWEN21_CLASS = "mflux.models.qwen21.variants.edit.qwen_image_21_edit.QwenImage21Edit"
QWEN2511_CLASS = "mflux.models.qwen.variants.edit.qwen_image_edit.QwenImageEdit"
QWEN_MODELS = (
    {"id": "qwen21-q4", "label": "Qwen-Image-2.1 q4", "family": "qwen21", "backend": "mflux",
     "repo": "mflux-community/qwen-image-2-1-mflux-q4", "revision": "b6c0fc76350650482d13aea89b316c28cd487f7f",
     "allow_patterns": None, "bytes": 10638928735, "quant": "q4",
     "mflux_class": QWEN21_CLASS, "mflux_config": "qwen_image_21",
     "steps": 40, "guidance": 1.0, "scheduler": "linear", "multiple": 32, "builtin_lora": None,
     "memory_gib": 20.0, "max_references": 10, "reference_gib": 2.0, "license": QWEN_RESEARCH, "setup": True},
    {"id": "qwen21-q8", "label": "Qwen-Image-2.1 q8", "family": "qwen21", "backend": "mflux",
     "repo": "mflux-community/qwen-image-2-1-mflux-q8", "revision": "f5c8cc79a6741026a6057546012fba3b0a4b5b25",
     "allow_patterns": None, "bytes": 18460986297, "quant": "q8",
     "mflux_class": QWEN21_CLASS, "mflux_config": "qwen_image_21",
     "steps": 40, "guidance": 1.0, "scheduler": "linear", "multiple": 32, "builtin_lora": None,
     "memory_gib": 32.0, "max_references": 10, "reference_gib": 2.0, "license": QWEN_RESEARCH, "setup": True},
    {"id": "qwen21-bf16", "label": "Qwen-Image-2.1 bf16", "family": "qwen21", "backend": "mflux",
     "repo": "Qwen/Qwen-Image-2.1", "revision": "d26bb61231c349cf6b7896fa83353113880e1ba3",
     "allow_patterns": QWEN21_PATTERNS, "bytes": 33131601593, "quant": "bf16",
     "mflux_class": QWEN21_CLASS, "mflux_config": "qwen_image_21",
     "steps": 40, "guidance": 1.0, "scheduler": "linear", "multiple": 32, "builtin_lora": None,
     "memory_gib": 56.0, "max_references": 10, "reference_gib": 2.0, "license": QWEN_RESEARCH, "setup": True},
    {"id": "qwen2511-q4", "label": "Qwen-Image-Edit-2511 q4 (Lightning)", "family": "qwen2511", "backend": "mflux",
     "repo": "mflux-community/qwen-image-edit-2511-mflux-q4", "revision": "3c74aab7dd79e6a8148c329cbca78c00c049ec3b",
     "allow_patterns": None, "bytes": 28958989673, "quant": "q4",
     "mflux_class": QWEN2511_CLASS, "mflux_config": "qwen_image_edit_2511",
     "steps": 8, "guidance": 1.0, "scheduler": None, "multiple": 16, "builtin_lora": LIGHTNING,
     "memory_gib": 32.0, "max_references": 1, "reference_gib": 3.0, "license": "Apache-2.0", "setup": True},
    {"id": "qwen2511-bf16", "label": "Qwen-Image-Edit-2511 bf16 (Lightning, diffusers)", "family": "qwen2511",
     "backend": "diffusers", "repo": "Qwen/Qwen-Image-Edit-2511", "revision": None,
     "allow_patterns": None, "bytes": None, "quant": "bf16", "mflux_class": None, "mflux_config": None,
     "steps": 8, "guidance": 1.0, "scheduler": None, "multiple": 16, "builtin_lora": dict(LIGHTNING, revision=None),
     "memory_gib": 64.0, "max_references": 3, "reference_gib": 3.0, "license": "Apache-2.0", "setup": False},
)
BUILTIN_QWEN_LORAS = (
    {"id": "uncensored", "label": "Uncensored (abenzerps)", "family": "qwen21",
     "repo": "abenzerps/Qwen-Image-2.1-Uncensored-Quantized", "revision": "7959e658915f52274897fb573ffeda49de8dc16b",
     "file": "qwen-image-2.1-uncensored-lora.safetensors", "bytes": 33586704,
     "default_on": True, "default_scale": 1.0, "steps": None, "scheduler": None, "license": QWEN_RESEARCH},
    {"id": "viggle-turbo", "label": "Viggle turbo 6-step", "family": "qwen21",
     "repo": "Viggle/Qwen-Image-2.1-viggle-turbo", "revision": "009a44a895ef85f7e643c80fdca9543795248867",
     "file": "Qwen-Image-2.1-viggle-turbo-v0.3-6step-lora-r128.safetensors", "bytes": 679604800,
     "default_on": False, "default_scale": 1.0, "steps": 6, "scheduler": "viggle_turbo", "license": QWEN_RESEARCH},
)
QWEN_MODEL_IDS = tuple(m["id"] for m in QWEN_MODELS)
BUILTIN_QWEN_LORA_IDS = tuple(l["id"] for l in BUILTIN_QWEN_LORAS)
DEFAULT_QWEN_MODEL = "qwen21-q4"
LEGACY_QWEN_MODEL = "qwen2511-q4"
SCALE_MAX = 2.0
LORAS_MSG = "loras must be a list of {id, scale}"
HF_TOKEN_VARS = ("HF_TOKEN", "HUGGING_FACE_HUB_TOKEN")
# Custom edit LoRAs spec CL1: the registry file of the custom (user-added) Qwen edit LoRAs.
USER_LORAS_ENV = "SEED_EDIT_USER_LORAS"
USER_LORAS_SCHEMA = "seed-edit.user-loras.v1"
USER_ID_RE = re.compile(r"^user-[a-z0-9-]{1,24}$")
USER_LORA_MAX_BYTES = 8 * 2 ** 30
LABEL_MAX = 80
LICENSE_MAX = 200
STEPS_MAX = 100
TRIGGER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ,.;:'!?()&/-]{0,199}$")
HF_REPO_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,95}/[A-Za-z0-9][A-Za-z0-9_.-]{0,95}$")
HF_FILE_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_. +()-]{0,199}(/[A-Za-z0-9_][A-Za-z0-9_. +()-]{0,199})*$")
HF_KEYS = ("id", "label", "family", "source", "repo", "revision", "file", "bytes", "default_on",
           "default_scale", "license", "steps", "scheduler", "trigger", "user")
LOCAL_KEYS = ("id", "label", "family", "source", "path", "file", "sha256", "bytes", "default_on",
              "default_scale", "license", "steps", "scheduler", "trigger", "user")
NO_LORAS_MSG = ("%s runs without LoRAs (its diffusers child loads only the built-in Lightning LoRA); "
                "use qwen2511-q4")
REMOVED_MSG = ("it is not in the Qwen edit LoRA registry (removed?); add it again with bin/seed-edit-lora "
               "add, or choose other LoRAs")
USER_LORAS_WARNING = "seed-edit: ignoring %s: %s; only the built-in Qwen edit LoRAs are available"
_REVISION_RE = re.compile(r"^[0-9a-f]{40}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_USER_LOCK = threading.Lock()
_USER_CACHE = {"key": None, "loras": ()}     # CL5: the last file state read and its entries


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


def qwen_selection(model_id, loras, model_key="qwen_model", loras_key="loras"):
    """Seed models SQ30 rows 9b-9i as a shared rule (qwen edit models QE51): (model_id, loras, None)
    cleaned, or (None, None, error). A null model is DEFAULT_QWEN_MODEL, null loras that model's
    default_loras, [] no LoRA; model_key and loras_key name the request fields in the texts."""
    lists = "%s must be a list of {id, scale}" % loras_key
    if model_id is not None and not (isinstance(model_id, str) and model_id in QWEN_MODEL_IDS):
        return None, None, "unknown %s %s" % (model_key, model_id)
    if model_id is None:
        model_id = DEFAULT_QWEN_MODEL
    if loras is None:
        return model_id, default_loras(model_id), None
    if not isinstance(loras, list):
        return None, None, lists
    entry, seen, clean = qwen_model(model_id), set(), []
    for item in loras:
        if not (isinstance(item, dict) and set(item) == {"id", "scale"}):
            return None, None, lists
        lora_id, scale = item["id"], item["scale"]
        if not (isinstance(lora_id, str) and lora_id in qwen_lora_ids()):
            return None, None, "unknown LoRA %s" % (lora_id,)
        if lora_id in seen:
            return None, None, "LoRA %s is listed twice" % lora_id
        seen.add(lora_id)
        lora = qwen_lora(lora_id)
        if lora["family"] != entry["family"]:
            return None, None, "LoRA %s is for %s, not %s" % (lora_id, QWEN_FAMILIES[lora["family"]], entry["label"])
        if entry["backend"] == "diffusers":
            return None, None, "LoRA %s: " % lora_id + NO_LORAS_MSG % entry["id"]
        if not (lib._is_number(scale) and 0 < scale <= SCALE_MAX):
            return None, None, "LoRA %s scale must be a number above 0 and at most 2" % lora_id
        clean.append({"id": lora_id, "scale": float(scale)})
    return model_id, registry_order(clean), None


def _qwen_fields(body, model):
    """Seed models SQ30 rows 9a-9i: (qwen_model, loras, None) cleaned, or (None, None, error)."""
    model_id, loras = body.get("qwen_model"), body.get("loras")
    if model == "zimage":
        if model_id is not None:
            return None, None, "qwen_model is only for qwen"
        if loras is not None:
            return None, None, "loras is only for qwen"
        return None, [], None
    return qwen_selection(model_id, loras)


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
    qwen_model_id, loras, error = _qwen_fields(body, model)
    if error is not None:
        return None, error
    source, error = _source(body.get("source"))
    if error is not None:
        return None, error
    if model == "zimage":
        strength = STRENGTH_DEFAULT if strength is None else float(strength)
    else:
        strength = None
    return {"prompt": prompt, "model": model, "strength": strength,
            "candidates": CANDIDATES_DEFAULT if candidates is None else candidates,
            "seed": seed, "qwen_model": qwen_model_id, "loras": loras, "source": source}, None


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


def qwen_model(model_id):
    """Seed models SQ5: the QWEN_MODELS entry whose id is model_id, else None."""
    for entry in QWEN_MODELS:
        if entry["id"] == model_id:
            return entry
    return None


def user_loras_path():
    """Custom edit LoRAs spec CL2 (D8): $SEED_EDIT_USER_LORAS when set and non-empty, else this workspace's
    generated/seed_loras/user_loras.json."""
    return os.environ.get(USER_LORAS_ENV) or os.path.join(os.path.dirname(os.path.realpath(__file__)), "generated",
                                                          "seed_loras", "user_loras.json")


def valid_trigger(text):
    """Custom edit LoRAs spec CL3 (D1): a str of TRIGGER_RE with no double and no trailing space."""
    return (isinstance(text, str) and TRIGGER_RE.fullmatch(text) is not None and "  " not in text
            and not text.endswith(" "))


def _plain_text(value, most):
    """A str of 1 to most characters with no character below a space and no DEL."""
    return (isinstance(value, str) and 1 <= len(value) <= most
            and not any(c < "\x20" or c == "\x7f" for c in value))


def _entry_problem(i, entry, seen):
    """Custom edit LoRAs spec CL4 rule 4: why entry i (1-based) of a registry file is invalid, or None. seen
    collects the ids of the entries before it."""
    source = entry.get("source") if isinstance(entry, dict) else None
    keys = {"hf": HF_KEYS, "local": LOCAL_KEYS}.get(source) if isinstance(source, str) else None
    if keys is None or set(entry) != set(keys):
        return "entry %d: keys or source are invalid" % i
    bad = "entry %d: %s is invalid"
    lora_id = entry["id"]
    if not (isinstance(lora_id, str) and USER_ID_RE.fullmatch(lora_id) and lora_id not in BUILTIN_QWEN_LORA_IDS):
        return bad % (i, "id")
    if lora_id in seen:
        return "entry %d: id %s is listed twice" % (i, lora_id)
    seen.add(lora_id)
    if not _plain_text(entry["label"], LABEL_MAX):
        return bad % (i, "label")
    if not (isinstance(entry["family"], str) and entry["family"] in QWEN_FAMILIES):
        return bad % (i, "family")
    if source == "hf":
        repo, revision, name = entry["repo"], entry["revision"], entry["file"]
        if not (isinstance(repo, str) and HF_REPO_RE.fullmatch(repo) and ".." not in repo and "--" not in repo):
            return bad % (i, "repo")
        if not (isinstance(revision, str) and _REVISION_RE.fullmatch(revision)):
            return bad % (i, "revision")
        if not (isinstance(name, str) and HF_FILE_RE.fullmatch(name) and ".." not in name.split("/")
                and name.lower().endswith(".safetensors")):
            return bad % (i, "file")
    else:
        path = entry["path"]
        if not (isinstance(path, str) and os.path.isabs(path) and not any(c < "\x20" for c in path)
                and path.lower().endswith(".safetensors")):
            return bad % (i, "path")
        if entry["file"] != os.path.basename(path):
            return bad % (i, "file")
        if not (isinstance(entry["sha256"], str) and _SHA256_RE.fullmatch(entry["sha256"])):
            return bad % (i, "sha256")
    if not (lib._is_int(entry["bytes"]) and 1 <= entry["bytes"] <= USER_LORA_MAX_BYTES):
        return bad % (i, "bytes")
    if entry["default_on"] is not False:
        return bad % (i, "default_on")
    if not (lib._is_number(entry["default_scale"]) and 0 < entry["default_scale"] <= SCALE_MAX):
        return bad % (i, "default_scale")
    if not (isinstance(entry["license"], str) and 1 <= len(entry["license"]) <= LICENSE_MAX):
        return bad % (i, "license")
    steps = entry["steps"]
    if not (steps is None or (lib._is_int(steps) and 1 <= steps <= STEPS_MAX)):
        return bad % (i, "steps")
    if entry["scheduler"] is not None:
        return bad % (i, "scheduler")
    if not (entry["trigger"] is None or valid_trigger(entry["trigger"])):
        return bad % (i, "trigger")
    if entry["user"] is not True:
        return bad % (i, "user")
    return None


def user_loras_problem(data):
    """Custom edit LoRAs spec CL4: None when data is a valid registry file, else the first failing rule's reason."""
    if not (isinstance(data, dict) and set(data) == {"schema", "loras"}):
        return "top level must be {schema, loras}"
    if data["schema"] != USER_LORAS_SCHEMA:
        return "schema must be seed-edit.user-loras.v1"
    if not isinstance(data["loras"], list):
        return "loras must be a list"
    seen = set()
    for i, entry in enumerate(data["loras"], 1):
        problem = _entry_problem(i, entry, seen)
        if problem is not None:
            return problem
    return None


def _ignored(key, path, reason):
    """Custom edit LoRAs spec CL5: warn once for this file state, remember it, and give no custom LoRA."""
    sys.stderr.write(USER_LORAS_WARNING % (path, reason) + "\n")
    sys.stderr.flush()
    _USER_CACHE["key"], _USER_CACHE["loras"] = key, ()
    return ()


def user_loras():
    """Custom edit LoRAs spec CL5: the entries of the registry file as a tuple; () when it is missing (no warning)
    or unusable (one warning per file state). Cached by (path, mtime_ns, size, inode); thread-safe; never raises."""
    path = user_loras_path()
    with _USER_LOCK:
        try:
            info = os.stat(path)
        except (FileNotFoundError, NotADirectoryError):
            return ()
        except OSError as e:
            key = (path, "stat", str(e))
            if _USER_CACHE["key"] == key:
                return ()
            return _ignored(key, path, "cannot read: %s" % e)
        key = (path, info.st_mtime_ns, info.st_size, info.st_ino)
        if _USER_CACHE["key"] == key:
            return _USER_CACHE["loras"]
        try:
            with open(path, "rb") as f:
                raw = f.read()
        except OSError as e:
            return _ignored(key, path, "cannot read: %s" % e)
        try:
            data = json.loads(raw.decode("utf-8"))
        except (ValueError, RecursionError):
            return _ignored(key, path, "not valid JSON")
        reason = user_loras_problem(data)
        if reason is not None:
            return _ignored(key, path, reason)
        _USER_CACHE["key"], _USER_CACHE["loras"] = key, tuple(data["loras"])
        return _USER_CACHE["loras"]


def qwen_loras():
    """Custom edit LoRAs spec CL6: the registry's LoRAs: BUILTIN_QWEN_LORAS, then the custom LoRAs in file order."""
    return BUILTIN_QWEN_LORAS + user_loras()


def qwen_lora_ids():
    """Custom edit LoRAs spec CL6: the ids of qwen_loras(), in order."""
    return tuple(l["id"] for l in qwen_loras())


def qwen_lora(lora_id):
    """Seed models SQ5 (custom edit LoRAs spec CL7): the registry LoRA whose id is lora_id, else None."""
    for entry in qwen_loras():
        if entry["id"] == lora_id:
            return entry
    return None


def registry_order(loras):
    """Seed models SQ5 (custom edit LoRAs spec CL8): a list of {"id", ...} items sorted by each id's place in
    qwen_lora_ids(); an id that is no longer in the registry sorts after every known id."""
    ids = qwen_lora_ids()
    return sorted(loras, key=lambda item: ids.index(item["id"]) if item["id"] in ids else len(ids))


def default_loras(model_id):
    """Seed models SQ6: the default-on LoRAs of model_id's family, [{"id", "scale"}] (a custom LoRA is never
    default-on)."""
    family = qwen_model(model_id)["family"]
    return [{"id": lora["id"], "scale": lora["default_scale"]} for lora in qwen_loras()
            if lora["default_on"] and lora["family"] == family]


def settings_item(lora, scale):
    """Custom edit LoRAs spec CL10 (D4): the recorded item of one selected registry LoRA."""
    if not lora.get("user"):
        return {"id": lora["id"], "repo": lora["repo"], "file": lora["file"], "scale": scale}
    if lora["source"] == "local":
        return {"id": lora["id"], "source": "local", "file": lora["file"], "sha256": lora["sha256"],
                "scale": scale, "trigger": lora["trigger"]}
    return {"id": lora["id"], "repo": lora["repo"], "revision": lora["revision"], "file": lora["file"],
            "scale": scale, "trigger": lora["trigger"]}


def qwen_settings(model_id, loras):
    """Seed models SQ7 (custom edit LoRAs spec CL10): {"qwen_model", "loras", "steps", "scheduler"} of a
    selection (model_id None for Z-Image). Each item is settings_item's; an id no longer in the registry is
    {"id", "scale", "removed": True} (D5). The first LoRA in registry order with its own steps sets steps and
    its scheduler, or keeps the model's scheduler when its own is None (D13)."""
    if model_id is None:
        return {"qwen_model": None, "loras": [], "steps": None, "scheduler": None}
    entry = qwen_model(model_id)
    steps, scheduler, turbo, out = entry["steps"], entry["scheduler"], None, []
    for item in registry_order(loras):
        lora = qwen_lora(item["id"])
        if lora is None:
            out.append({"id": item["id"], "scale": float(item["scale"]), "removed": True})
            continue
        out.append(settings_item(lora, float(item["scale"])))
        if turbo is None and lora["steps"] is not None:
            turbo = lora
    if turbo is not None:
        steps = turbo["steps"]
        scheduler = turbo["scheduler"] if turbo["scheduler"] is not None else entry["scheduler"]
    return {"qwen_model": {"id": entry["id"], "repo": entry["repo"]}, "loras": out, "steps": steps,
            "scheduler": scheduler}


def trigger_prompt(prompt, loras):
    """prompt with the triggers of the selected registry LoRAs in front (custom edit LoRAs spec CL11)."""
    missing = []
    for item in registry_order(loras):
        lora = qwen_lora(item["id"])
        trigger = lora.get("trigger") if lora is not None else None
        if (trigger and trigger.lower() not in prompt.lower()
                and trigger.lower() not in [m.lower() for m in missing]):
            missing.append(trigger)
    if not missing:
        return prompt
    prefix = " ".join(missing)
    return prefix if not prompt.strip() else prefix + " " + prompt


def record_settings(record):
    """Seed models SQ8: the four qwen_settings keys of a run.json dict; a Qwen run made before the
    registry reads as qwen2511-bf16 when its backend was diffusers-bf16, else as qwen2511-q4."""
    if isinstance(record.get("qwen_model"), dict):
        loras = record.get("loras")
        return {"qwen_model": record["qwen_model"], "loras": loras if isinstance(loras, list) else [],
                "steps": record.get("steps"), "scheduler": record.get("scheduler")}
    if record.get("model") == "qwen":
        return qwen_settings("qwen2511-bf16" if record.get("backend") == "diffusers-bf16" else LEGACY_QWEN_MODEL, [])
    return qwen_settings(None, [])


def canvas_multiple(model, model_id):
    """Seed models SQ9: the edit canvas multiple: the registry model's for qwen, else 16."""
    return qwen_model(model_id)["multiple"] if model == "qwen" else 16


def registry_view():
    """Seed models SQ10: the page's copy of the registry (the seed_edit capability's "registry")."""
    models = [{"id": m["id"], "label": m["label"], "family": m["family"], "backend": m["backend"],
               "steps": m["steps"], "scheduler": m["scheduler"], "multiple": m["multiple"],
               "memory_gib": m["memory_gib"], "max_references": m["max_references"], "license": m["license"],
               "setup": "bin/seed-edit-setup --model %s" % m["id"] if m["setup"] else None} for m in QWEN_MODELS]
    loras = [{"id": lora["id"], "label": lora["label"], "family": lora["family"], "default_on": lora["default_on"],
              "default_scale": lora["default_scale"], "steps": lora["steps"], "scheduler": lora["scheduler"],
              "license": lora["license"], "user": bool(lora.get("user")), "source": lora.get("source", "builtin"),
              "trigger": lora.get("trigger"),
              "setup": None if lora.get("source") == "local" else "bin/seed-edit-setup --lora %s" % lora["id"]}
             for lora in qwen_loras()]
    return {"default_model": DEFAULT_QWEN_MODEL, "families": dict(QWEN_FAMILIES), "models": models, "loras": loras}


def capability(models, detail, checked):
    """SG36, seed models SQ32: the seed_edit capability from lib.seed_edit_check's (models, detail),
    with the registry view."""
    if models is None:
        return {"ok": False, "reason": detail, "checked": checked, "models": None, "registry": registry_view()}
    ok = any(m["ok"] for m in models.values())
    reason = None if ok else "; ".join("%s: %s" % (MODELS[k], models[k]["reason"]) for k in ("zimage", "qwen"))
    return {"ok": ok, "reason": reason, "checked": checked, "models": models, "registry": registry_view()}


def availability_error(models, detail, clean):
    """SG37, seed models SQ31: the 409 error for a cleaned request, or None when it can run. For qwen
    the selected model's own probe entry decides, then each selected LoRA's in registry order."""
    if models is None:
        return "cannot check the seed models: %s" % detail
    if clean["model"] == "zimage":
        if not models["zimage"]["ok"]:
            return "%s is unavailable: %s" % (MODELS["zimage"], models["zimage"]["reason"])
        return None
    entry = qwen_model(clean["qwen_model"])
    found = models["qwen"]["models"][entry["id"]]
    if not found["ok"]:
        return "%s is unavailable: %s" % (entry["label"], found["reason"])
    for item in clean["loras"]:
        lora = qwen_lora(item["id"])
        if lora is None:
            return "LoRA %s is unavailable: %s" % (item["id"], REMOVED_MSG)
        found = models["qwen"]["loras"].get(lora["id"])
        if found is None:
            return "LoRA %s is unavailable: %s" % (lora["label"], lib.PROBE_NOT_REPORTED)
        if not found["ok"]:
            return "LoRA %s is unavailable: %s" % (lora["label"], found["reason"])
    return None


def hf_child_env(environ, **extra):
    """Seed models §14a item B: the environment of bin/seed-edit's mflux child and bin/seed-edit-setup's
    download child: a copy of environ with extra set, without the HF_TOKEN_VARS keys and with
    HF_HUB_DISABLE_IMPLICIT_TOKEN "1", so no Hugging Face token reaches either child (every download is
    public; the mflux child is offline). environ itself is not changed."""
    env = dict(environ, **extra)
    for key in HF_TOKEN_VARS:
        env.pop(key, None)
    env["HF_HUB_DISABLE_IMPLICIT_TOKEN"] = "1"
    return env
