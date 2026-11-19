"""seed_lora_registry -- the custom (user-added) Qwen edit LoRAs of the registry file
(docs/superpowers/specs/2026-11-17-custom-edit-loras-design.md, Sections 2.2 and 3): the request rules, the
Hugging Face model API call and its answer rules, the local file checks, the strict load and the locked,
atomic save, add and remove, and the run-time checks that qwen_edit.lora_problem and bin/seed-edit-setup use.

This module is the only writer of the registry file (movie_ui_seedgen only reads it) and the only Hugging
Face API caller in the workspace: fetch_model_info makes one unauthenticated GET and no token is read or
sent. Weights are never downloaded here; bin/seed-edit-setup --lora ID stays the only downloader.
bin/seed-edit-lora and the movie-ui server's POST and DELETE /api/seed-loras share it.

Standard library plus lora_catalog, movie_ui_lib and movie_ui_seedgen at the top level; qwen_edit is
imported inside remove only, so neither module imports the other at load time. Valid on Python 3.9 and
3.13; %-formatting only.
"""

import http.client
import json
import os
import re
import ssl

import lora_catalog
import movie_ui_lib as lib
import movie_ui_seedgen as seedgen

FIELDS = ("repo", "file", "path", "family", "id", "label", "trigger", "scale", "steps")
BASE_MODEL_FAMILIES = {"Qwen/Qwen-Image-Edit-2511": "qwen2511", "Qwen/Qwen-Image-2.1": "qwen21"}
HF_HOST = "huggingface.co"
HF_TIMEOUT_S = 30
HF_MAX_BYTES = 32 * 2 ** 20
USER_AGENT = "qwen-agent-seed-edit-lora/1"
HF_URL_RE = re.compile(r"^https://huggingface\.co/([A-Za-z0-9][A-Za-z0-9_.-]{0,95}/[A-Za-z0-9][A-Za-z0-9_.-]{0,95})/?$")
SHA_RE = re.compile(r"^[0-9a-f]{40}$")
PICKLE_EXTS = (".bin", ".pt", ".pth", ".ckpt", ".pkl")
LOCAL_LICENSE = "not stated (local file)"
NO_LICENSE = "not stated in the model card"
LIST_MAX = 10
PAIR_SUBSTITUTIONS = ((".lora_A.", ".lora_B."), (".lora_down.", ".lora_up."), (".lora.down.", ".lora.up."))
# Section 3.2: the request rules R1-R12 (status 400).
M_FIELD = "unknown field %s; allowed: repo, file, path, family, id, label, trigger, scale, steps"
M_STRING = "%s must be a string"
M_ONE_SOURCE = "give exactly one of repo and path"
M_FILE_ONLY_REPO = "file is only for repo"
M_REPO = ("repo must be OWNER/NAME (letters, digits, '.', '_' or '-') or https://huggingface.co/OWNER/NAME "
          "(got %s)")
M_FILE = "file must be a relative path of letters, digits, spaces and . _ - + ( ), with no '..' (got %s)"
M_FAMILY = "family must be qwen21 or qwen2511 (got %s)"
M_FAMILY_LOCAL = "family is required for a local file (qwen21 or qwen2511)"
M_ID = "id must be user- followed by 1 to 24 lowercase letters, digits or '-' (got %s)"
M_LABEL = "label must be 1 to 80 characters with no control characters"
M_TRIGGER = ("trigger must be 1 to 200 characters: letters, digits, spaces and , . ; : ' ! ? ( ) & / -, starting "
             "with a letter or digit, with no double or trailing space")
M_SCALE = "scale must be a number above 0 and at most 2"
M_STEPS = "steps must be an integer from 1 to 100"
# Section 3.3: the Hugging Face API, its answer (H1-H9) and the files.
M_HF_UNREACHABLE = "cannot reach the Hugging Face API (huggingface.co): %s: %s"
M_HF_NO_CERTS = "; this Python has no CA certificates (run its Install Certificates.command)"
M_HF_NOTFOUND = ("repo %s is not on the Hugging Face Hub, or it is private (only public repos can be added; no "
                 "token is sent)")
M_HF_MOVED = "repo %s has moved (%s); add it by its new name"
M_HF_STATUS = "the Hugging Face API answered HTTP %d for %s"
M_HF_BIG = "the Hugging Face API answer for %s is larger than 32 MiB"
M_HF_JSON = "the Hugging Face API answered %s with invalid JSON"
M_HF_NO_MODEL = "the Hugging Face API returned no model, commit sha or file list for %s"
M_HF_DISABLED = "repo %s is disabled on the Hugging Face Hub"
M_HF_GATED = "repo %s is gated (%s); seed-edit downloads are unauthenticated, so it cannot be installed"
M_HF_FILE_MISSING = "file %s is not in %s@%s; its .safetensors files: %s"
M_HF_NO_ROOT = "repo %s@%s has no .safetensors file at its top level"
M_HF_NO_ROOT_FOLDERS = "; its .safetensors files in folders: %s; pass file"
M_HF_NO_ROOT_PICKLE = "; it has %s, which are refused: pickle formats can run code when loaded"
M_HF_SEVERAL = "repo %s@%s has %d .safetensors files at its top level (%s); pass file to choose one"
M_HF_BAD_NAME = "the repo's file %s has characters this tool does not accept, so it cannot be added"
M_HF_NO_SIZE = "the Hugging Face API reported no size for %s"
M_HF_BASE_UNKNOWN = ("the model card's base_model (%s) is not Qwen/Qwen-Image-Edit-2511 or Qwen/Qwen-Image-2.1; "
                     "pass family (qwen21 or qwen2511)")
M_HF_BASE_BOTH = "the model card's base_model lists both families; pass family"
M_NOT_SAFETENSORS = ("%s is not a .safetensors file; other formats are refused (the pickle formats .bin, .pt, .pth "
                     "and .ckpt can run code when loaded)")
M_PATH_ABS = "path must be an absolute path or start with ~ (got %s)"
M_PATH_CONTROL = "path must not contain control characters"                  # plan SC6
M_NOT_EXIST = "%s does not exist"
M_NOT_REGULAR = "%s is not a regular file"
M_TOO_BIG = "%s is %.1f GiB; custom LoRAs are limited to 8 GiB"
M_NOT_ST_HEADER = "%s is not a safetensors file (its header does not parse)"
M_NO_PAIRS = ("%s has no LoRA weight pairs (lora_A/lora_B, lora_down/lora_up or lora.down/lora.up) in its "
              "safetensors header, so mflux would apply nothing")
M_READ = "cannot read %s: %s"
M_ID_TAKEN = "LoRA id %s already exists; choose another id or remove it first"
M_DUPLICATE = "%s is already in the registry as %s"
M_UNREADABLE = "the custom LoRA registry %s is unreadable: %s; fix or delete it, then retry"
M_UNWRITABLE = "cannot write the custom LoRA registry %s: %s"                # plan SC12
M_BUILTIN = "%s is a built-in LoRA and cannot be removed"
M_UNKNOWN = "unknown custom LoRA %s (custom LoRAs: %s)"
M_LOCAL_MISSING = ("%s is missing or not a regular file (restore it, or re-run bin/seed-edit-lora add after "
                   "bin/seed-edit-lora remove %s)")
M_LOCAL_CHANGED = ("%s is %d bytes; the registry recorded %d (the file changed since it was added: re-run "
                   "bin/seed-edit-lora add after bin/seed-edit-lora remove %s)")
M_HF_SIZE = "%s is %d bytes; the registry recorded %d (delete it and run bin/seed-edit-setup --lora %s again)"
M_HF_NOT_ST = "%s is not a safetensors file (bin/seed-edit-lora remove %s)"
M_HF_NO_PAIRS = ("%s has no LoRA weight pairs in its safetensors header, so mflux would apply nothing "
                 "(bin/seed-edit-lora remove %s)")
# Section 3.4: the notes add returns.
N_FAMILY_INFERRED = "family %s (the model card's base_model is %s)"
N_FAMILY_GIVEN = "family %s (given)"
N_FAMILY_CONFLICT = "warning: family %s was given, but the model card's base_model %s means %s"
N_TRIGGER = "the model card's instance_prompt is %r; pass trigger to prepend it to every edit prompt of this LoRA"
N_STEPS = "qwen2511-q4 always loads the Lightning 8-step LoRA; %d steps with Lightning are untested"
N_DOWNLOAD = "download it with: bin/seed-edit-setup --lora %s"
N_IN_PLACE = "the file is used in place: moving, replacing or resizing it makes this LoRA unavailable"


class RegistryError(Exception):
    """A refused request (custom edit LoRAs spec CL16, D14): status is 400, 404, 409 or 502; the message is the
    text the CLI prints and the server answers."""

    def __init__(self, status, message):
        Exception.__init__(self, message)
        self.status = status


# ---------------------------------------------------------------------------
# The Hugging Face model API (CL17)
# ---------------------------------------------------------------------------

def fetch_model_info(repo):
    """Custom edit LoRAs spec CL17: the parsed GET /api/models/<repo>?blobs=true answer of huggingface.co, sent
    with only the User-Agent and Accept headers and no token read; RegistryError (400 or 502) for anything else.
    repo is already HF_REPO_RE-valid."""
    conn = http.client.HTTPSConnection(HF_HOST, timeout=HF_TIMEOUT_S, context=ssl.create_default_context())
    try:
        conn.request("GET", "/api/models/%s?blobs=true" % repo,
                     headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
        resp = conn.getresponse()
        status = resp.status
        location = resp.getheader("Location")
        body = resp.read(HF_MAX_BYTES + 1)
    except (OSError, ssl.SSLError, http.client.HTTPException) as e:
        text = M_HF_UNREACHABLE % (type(e).__name__, e)
        if isinstance(e, ssl.SSLCertVerificationError):
            text += M_HF_NO_CERTS
        raise RegistryError(502, text)
    finally:
        conn.close()
    if status == 200:
        if len(body) > HF_MAX_BYTES:
            raise RegistryError(502, M_HF_BIG % repo)
        try:
            return json.loads(body.decode("utf-8"))
        except (ValueError, RecursionError):
            raise RegistryError(502, M_HF_JSON % repo)
    if status in (301, 302, 307, 308):
        raise RegistryError(400, M_HF_MOVED % (repo, location or "-"))
    if status in (401, 404):
        raise RegistryError(400, M_HF_NOTFOUND % repo)
    raise RegistryError(502, M_HF_STATUS % (status, repo))


# ---------------------------------------------------------------------------
# The request rules (Section 3.2) and the answer rules (Section 3.3)
# ---------------------------------------------------------------------------

def _names(names):
    """Section 3.3's file list (plan R2): at most LIST_MAX names joined ', ', then ' and N more'; 'none'."""
    if not names:
        return "none"
    text = ", ".join(names[:LIST_MAX])
    if len(names) > LIST_MAX:
        text += " and %d more" % (len(names) - LIST_MAX)
    return text


def _file_problem(name):
    """R6, and H7's check of a chosen repo file: the refusal text of a repo file name, or None."""
    if not name.lower().endswith(".safetensors"):
        return M_NOT_SAFETENSORS % name
    if not seedgen.HF_FILE_RE.fullmatch(name) or ".." in name.split("/"):
        return M_FILE % name
    return None


def check_request(request):
    """Custom edit LoRAs spec Section 3.2, R1-R12 in order (pure): the given values (a None value counts as
    absent; repo normalized to OWNER/NAME), or RegistryError(400)."""
    unknown = sorted(key for key in request if key not in FIELDS)
    if unknown:
        raise RegistryError(400, M_FIELD % unknown[0])
    given = dict((key, value) for key, value in request.items() if value is not None)
    for key in ("repo", "file", "path", "family", "id", "label", "trigger"):
        if key in given and not isinstance(given[key], str):
            raise RegistryError(400, M_STRING % key)
    if ("repo" in given) == ("path" in given):
        raise RegistryError(400, M_ONE_SOURCE)
    if "file" in given and "repo" not in given:
        raise RegistryError(400, M_FILE_ONLY_REPO)
    if "repo" in given:
        text = given["repo"]
        found = HF_URL_RE.fullmatch(text)
        repo = found.group(1) if found else text
        if not (seedgen.HF_REPO_RE.fullmatch(repo) and ".." not in repo and "--" not in repo):
            raise RegistryError(400, M_REPO % text)
        given["repo"] = repo
    if "file" in given:
        problem = _file_problem(given["file"])
        if problem is not None:
            raise RegistryError(400, problem)
    if "family" in given and given["family"] not in seedgen.QWEN_FAMILIES:
        raise RegistryError(400, M_FAMILY % given["family"])
    if "path" in given and "family" not in given:
        raise RegistryError(400, M_FAMILY_LOCAL)
    if "id" in given and not seedgen.USER_ID_RE.fullmatch(given["id"]):
        raise RegistryError(400, M_ID % given["id"])
    if "label" in given and not seedgen._plain_text(given["label"], seedgen.LABEL_MAX):
        raise RegistryError(400, M_LABEL)
    if "trigger" in given and not seedgen.valid_trigger(given["trigger"]):
        raise RegistryError(400, M_TRIGGER)
    if "scale" in given and not (lib._is_number(given["scale"]) and 0 < given["scale"] <= seedgen.SCALE_MAX):
        raise RegistryError(400, M_SCALE)
    if "steps" in given and not (lib._is_int(given["steps"]) and 1 <= given["steps"] <= seedgen.STEPS_MAX):
        raise RegistryError(400, M_STEPS)
    return given


def _card(info):
    """The cardData dict of an API answer, else {}."""
    card = info.get("cardData") if isinstance(info, dict) else None
    return card if isinstance(card, dict) else {}


def _hf_family(given, card):
    """H9's family: (family, the N-FAMILY notes), or RegistryError(400) (plan R4)."""
    base = card.get("base_model")
    if isinstance(base, str):
        bases = [base]
    elif isinstance(base, list):
        bases = [b for b in base if isinstance(b, str)]
    else:
        bases = []
    base_text = ", ".join(bases) or "none"
    families = sorted(set(BASE_MODEL_FAMILIES[b] for b in bases if b in BASE_MODEL_FAMILIES))
    if "family" in given:
        family = given["family"]
        notes = [N_FAMILY_GIVEN % family]
        if len(families) == 1 and families[0] != family:
            notes.append(N_FAMILY_CONFLICT % (family, base_text, families[0]))
        return family, notes
    if not families:
        raise RegistryError(400, M_HF_BASE_UNKNOWN % base_text)
    if len(families) > 1:
        raise RegistryError(400, M_HF_BASE_BOTH)
    return families[0], [N_FAMILY_INFERRED % (families[0], base_text)]


def _licence(card):
    """H9's licence: the card's license text, a list joined ', ', 'other (<license_name>)', else NO_LICENSE; cut to
    LICENSE_MAX characters (plan R4)."""
    value, name = card.get("license"), card.get("license_name")
    if value == "other" and isinstance(name, str) and name.strip():
        text = "other (%s)" % name.strip()
    elif isinstance(value, str):
        text = value
    elif isinstance(value, list) and value and all(isinstance(v, str) for v in value):
        text = ", ".join(value)
    else:
        text = ""
    return text.strip()[:seedgen.LICENSE_MAX] or NO_LICENSE


def _hf_fields(repo, given, info):
    """Custom edit LoRAs spec Section 3.3, H1-H9 on repo's API answer: (revision, file, bytes, family, licence,
    the family notes), or RegistryError."""
    sha = info.get("sha") if isinstance(info, dict) else None
    siblings = info.get("siblings") if isinstance(info, dict) else None
    if not (isinstance(sha, str) and SHA_RE.fullmatch(sha) and isinstance(siblings, list)):
        raise RegistryError(502, M_HF_NO_MODEL % repo)
    if info.get("disabled") is True:
        raise RegistryError(400, M_HF_DISABLED % repo)
    if info.get("gated") not in (False, None):
        raise RegistryError(400, M_HF_GATED % (repo, info.get("gated")))
    sizes = {}
    for item in siblings:
        if isinstance(item, dict) and isinstance(item.get("rfilename"), str):
            sizes[item["rfilename"]] = item.get("size")
    names = list(sizes)
    tensors = [n for n in names if n.lower().endswith(".safetensors")]
    if "file" in given:
        name = given["file"]
        if name not in sizes:
            raise RegistryError(400, M_HF_FILE_MISSING % (name, repo, sha[:12], _names(tensors)))
    else:
        roots = [n for n in tensors if "/" not in n]
        if not roots:
            text = M_HF_NO_ROOT % (repo, sha[:12])
            folders = [n for n in tensors if "/" in n]
            if folders:
                text += M_HF_NO_ROOT_FOLDERS % _names(folders)
            pickles = [n for n in names if n.lower().endswith(PICKLE_EXTS)]
            if pickles:
                text += M_HF_NO_ROOT_PICKLE % _names(pickles)
            raise RegistryError(400, text)
        if len(roots) > 1:
            raise RegistryError(400, M_HF_SEVERAL % (repo, sha[:12], len(roots), _names(roots)))
        name = roots[0]
    if _file_problem(name) is not None:
        raise RegistryError(400, M_HF_BAD_NAME % name)
    size = sizes[name]
    if not (lib._is_int(size) and size >= 1):
        raise RegistryError(502, M_HF_NO_SIZE % name)
    if size > seedgen.USER_LORA_MAX_BYTES:
        raise RegistryError(400, M_TOO_BIG % (name, size / 2 ** 30))
    card = _card(info)
    family, notes = _hf_family(given, card)
    return sha, name, size, family, _licence(card), notes


# ---------------------------------------------------------------------------
# The files (CL18, CL19, CL22b)
# ---------------------------------------------------------------------------

def check_local_file(path_text, base_dir):
    """Custom edit LoRAs spec CL18 (D7, SC6): (path, real, size) of a local LoRA file, first failure wins, else
    RegistryError(400). path keeps symlinks (os.path.abspath); the regular-file and size checks use real."""
    expanded = os.path.expanduser(path_text)
    if not os.path.isabs(expanded):
        if base_dir is None:
            raise RegistryError(400, M_PATH_ABS % path_text)
        expanded = os.path.join(base_dir, expanded)
    path = os.path.abspath(expanded)
    if any(c < "\x20" or c == "\x7f" for c in path):
        raise RegistryError(400, M_PATH_CONTROL)
    if not path.lower().endswith(".safetensors"):
        raise RegistryError(400, M_NOT_SAFETENSORS % path)
    if not os.path.exists(path):
        raise RegistryError(400, M_NOT_EXIST % path)
    real = os.path.realpath(path)
    if not os.path.isfile(real):
        raise RegistryError(400, M_NOT_REGULAR % path)
    size = os.path.getsize(real)
    if size > seedgen.USER_LORA_MAX_BYTES:
        raise RegistryError(400, M_TOO_BIG % (path, size / 2 ** 30))
    try:
        header = lora_catalog.read_safetensors_header(real)
    except lora_catalog.CatalogError:
        raise RegistryError(400, M_NOT_ST_HEADER % path)
    if lora_pair_count(header) == 0:
        raise RegistryError(400, M_NO_PAIRS % path)
    return path, real, size


def lora_pair_count(header):
    """Custom edit LoRAs spec CL19 (D6): the number of header keys K for which one PAIR_SUBSTITUTIONS swap on
    K + "." (first occurrence) names another key of the header."""
    count = 0
    for key in header:
        probe = key + "."
        for a, b in PAIR_SUBSTITUTIONS:
            if a in probe and probe.replace(a, b, 1)[:-1] in header:
                count += 1
                break
    return count


def local_problem(lora):
    """Custom edit LoRAs spec CL22b: None when a local custom LoRA's file is still a regular file of its recorded
    size (no hash, no header read), else the refusal text."""
    real = os.path.realpath(lora["path"])
    if not os.path.isfile(real):
        return M_LOCAL_MISSING % (lora["path"], lora["id"])
    size = os.path.getsize(real)
    if size != lora["bytes"]:
        return M_LOCAL_CHANGED % (lora["path"], size, lora["bytes"], lora["id"])
    return None


def downloaded_problem(lora, path):
    """Custom edit LoRAs spec CL22b: None when the downloaded file at path of a Hugging Face custom LoRA has its
    recorded size and a safetensors header with LoRA pairs, else the refusal text."""
    real = os.path.realpath(path)
    size = os.path.getsize(real)
    if size != lora["bytes"]:
        return M_HF_SIZE % (path, size, lora["bytes"], lora["id"])
    try:
        header = lora_catalog.read_safetensors_header(real)
    except lora_catalog.CatalogError:
        return M_HF_NOT_ST % (path, lora["id"])
    if lora_pair_count(header) == 0:
        return M_HF_NO_PAIRS % (path, lora["id"])
    return None


# ---------------------------------------------------------------------------
# The registry file (CL20) and the ids (CL22)
# ---------------------------------------------------------------------------

def load_entries():
    """Custom edit LoRAs spec CL20: the user entries of the registry file (a list, file order); [] when it is
    missing; RegistryError(409, M_UNREADABLE) when it cannot be read, is not JSON or fails
    movie_ui_seedgen.user_loras_problem."""
    path = seedgen.user_loras_path()
    try:
        with open(path, "rb") as f:
            raw = f.read()
    except FileNotFoundError:
        return []
    except OSError as e:
        raise RegistryError(409, M_UNREADABLE % (path, "cannot read: %s" % e))
    try:
        data = json.loads(raw.decode("utf-8"))
    except (ValueError, RecursionError):
        raise RegistryError(409, M_UNREADABLE % (path, "not valid JSON"))
    problem = seedgen.user_loras_problem(data)
    if problem is not None:
        raise RegistryError(409, M_UNREADABLE % (path, problem))
    return list(data["loras"])


def save_entries(entries):
    """Custom edit LoRAs spec CL20: write {schema, loras: entries} to the registry file with
    movie_ui_lib.write_json_atomic (an atomic replace, mode 0600, indent 2). The caller holds the lock."""
    lib.write_json_atomic(seedgen.user_loras_path(), {"schema": seedgen.USER_LORAS_SCHEMA, "loras": entries})


def slug(text):
    """Custom edit LoRAs spec CL22: lower-case, runs of other characters as '-', cut to 24; 'lora' when empty."""
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:24].rstrip("-") or "lora"


def default_id(base, ids):
    """Custom edit LoRAs spec CL22: "user-" + base when free, else the first free "user-<base cut>-<n>", n >= 2."""
    if "user-" + base not in ids:
        return "user-" + base
    n = 2
    while True:
        suffix = "-%d" % n
        candidate = "user-" + base[:24 - len(suffix)].rstrip("-") + suffix
        if candidate not in ids:
            return candidate
        n += 1


# ---------------------------------------------------------------------------
# add and remove (CL21, CL22a)
# ---------------------------------------------------------------------------

def add(request, base_dir):
    """Custom edit LoRAs spec CL21: register one custom LoRA. request holds FIELDS values (a None value counts as
    absent); base_dir resolves a relative path (None refuses one). Returns (entry, notes); raises RegistryError."""
    given = check_request(request)
    if "repo" in given:
        repo = given["repo"]
        info = fetch_model_info(repo)
        revision, name, size, family, licence, notes = _hf_fields(repo, given, info)
        instance = _card(info).get("instance_prompt")
        if "trigger" not in given and isinstance(instance, str):
            notes.append(N_TRIGGER % instance)
        source_name = repo.split("/", 1)[1]
    else:
        local, real, size = check_local_file(given["path"], base_dir)
        try:
            sha256 = lora_catalog.file_sha256(real)
        except OSError as e:
            raise RegistryError(400, M_READ % (local, e))
        family, notes = given["family"], []
        name = os.path.basename(local)
        source_name = name[:-len(".safetensors")]
    if "steps" in given and family == "qwen2511":
        notes.append(N_STEPS % given["steps"])
    path = seedgen.user_loras_path()
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with lora_catalog.catalog_lock(path):
            entries = load_entries()
            ids = seedgen.BUILTIN_QWEN_LORA_IDS + tuple(e["id"] for e in entries)
            if "id" in given and given["id"] in ids:
                raise RegistryError(409, M_ID_TAKEN % given["id"])
            if "repo" in given:
                same = [l for l in seedgen.BUILTIN_QWEN_LORAS + tuple(entries)
                        if l.get("repo") == repo and l.get("file") == name]
                what = "%s:%s" % (repo, name)
            else:
                same = [e for e in entries if e["source"] == "local" and (e["path"] == local or e["sha256"] == sha256)]
                what = local
            if same:
                raise RegistryError(409, M_DUPLICATE % (what, same[0]["id"]))
            lora_id = given["id"] if "id" in given else default_id(slug(source_name), ids)
            scale = float(given.get("scale") or 1.0)
            if "repo" in given:
                entry = {"id": lora_id, "label": given.get("label") or repo[:seedgen.LABEL_MAX], "family": family,
                         "source": "hf", "repo": repo, "revision": revision, "file": name, "bytes": size,
                         "default_on": False, "default_scale": scale, "license": licence, "steps": given.get("steps"),
                         "scheduler": None, "trigger": given.get("trigger"), "user": True}
            else:
                entry = {"id": lora_id, "label": given.get("label") or name[:seedgen.LABEL_MAX], "family": family,
                         "source": "local", "path": local, "file": name, "sha256": sha256, "bytes": size,
                         "default_on": False, "default_scale": scale, "license": LOCAL_LICENSE,
                         "steps": given.get("steps"), "scheduler": None, "trigger": given.get("trigger"), "user": True}
            problem = seedgen.user_loras_problem({"schema": seedgen.USER_LORAS_SCHEMA, "loras": [entry]})
            if problem is not None:
                raise AssertionError("seed_lora_registry.add built an invalid entry: %s" % problem)
            save_entries(entries + [entry])
    except OSError as e:
        raise RegistryError(409, M_UNWRITABLE % (path, e))
    notes.append(N_DOWNLOAD % lora_id if "repo" in given else N_IN_PLACE)
    return entry, notes


def remove(lora_id):
    """Custom edit LoRAs spec CL22a: drop custom LoRA lora_id from the registry file; no file is deleted. Returns
    (entry, kept): a local entry's path, else the downloaded snapshot file (None when it was never downloaded)."""
    if lora_id in seedgen.BUILTIN_QWEN_LORA_IDS:
        raise RegistryError(400, M_BUILTIN % lora_id)
    path = seedgen.user_loras_path()
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with lora_catalog.catalog_lock(path):
            entries = load_entries()
            found = [e for e in entries if e["id"] == lora_id]
            if not found:
                raise RegistryError(404, M_UNKNOWN % (lora_id, ", ".join(e["id"] for e in entries) or "none"))
            save_entries([e for e in entries if e["id"] != lora_id])
    except OSError as e:
        raise RegistryError(409, M_UNWRITABLE % (path, e))
    entry = found[0]
    if entry["source"] == "local":
        return entry, entry["path"]
    import qwen_edit
    return entry, qwen_edit.pinned_file(entry["repo"], entry["revision"], entry["file"], qwen_edit.qwen_hubs())
