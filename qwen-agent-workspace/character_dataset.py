#!/usr/bin/env python3
"""character_dataset -- dataset building, LoRA training, safety gates and the Z-Image
child process behind bin/character.

Spec: docs/superpowers/specs/2026-10-05-character-library-design.md, Section 4.

Top-level imports are stdlib, PIL and psutil, plus character_lib and
ltx2_mlx_video_skill (as SKILL). torch, z_image_skill and content_safety are imported
ONLY inside child_zimage(), which runs in a child process
(python3 character_dataset.py zimage --spec SPEC): z_image_skill allows one LoRA set per
process, and `create` must release Z-Image's memory before it restarts the vision
server.

The prompts, VARIANTS and the VLM helpers below are copied verbatim from the spike tool
generated/charlora/tools/make_dataset_seed.py (spec 4.1). CHARACTER_MFLUX_TRAIN is test
infrastructure only, like LTX2_MLX_BIN.
"""

import argparse
import base64
import contextlib
import glob
import hashlib
import io
import json
import os
import re
import shlex
import signal
import shutil
import struct
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import zipfile

import psutil
from PIL import Image, ImageDraw, ImageOps

WS = os.path.dirname(os.path.realpath(__file__))
sys.path.insert(0, WS)

import character_lib  # noqa: E402
import ltx2_mlx_video_skill as SKILL  # noqa: E402

STORY_SERVER = os.path.join(WS, "bin", "story-server")

VLM_URL      = "http://127.0.0.1:8177/v1/chat/completions"
MODELS_URL   = "http://127.0.0.1:8177/v1/models"
VLM_MODEL    = "qwen38-6bit"
WIDTH, HEIGHT = 1024, 640
STYLE = "photorealistic live-action film still, natural light"
SHOTS = [
    "extreme wide shot",
    "wide shot",
    "medium shot",
    "medium close-up",
    "close-up",
    "extreme close-up",
]

VARIANTS = [
    # (shot, pose, setting)
    ("close-up",        "facing the camera with a neutral expression",        "a studio with a plain grey backdrop"),
    ("close-up",        "in three-quarter view looking to the left",          "a studio with a plain grey backdrop"),
    ("close-up",        "in profile facing right",                            "a softly lit interior room"),
    ("close-up",        "looking slightly upward",                            "an overcast outdoor setting"),
    ("medium close-up", "looking back over one shoulder",                     "a city street"),
    ("medium close-up", "smiling slightly",                                   "a sunlit park"),
    ("medium close-up", "with a serious expression",                          "a dim interior room"),
    ("medium close-up", "in three-quarter view looking to the right",         "a forest"),
    ("medium shot",     "standing with arms relaxed",                         "a studio with a plain grey backdrop"),
    ("medium shot",     "walking toward the camera",                          "a city street"),
    ("medium shot",     "seen from behind, glancing back",                    "a forest trail"),
    ("medium shot",     "sitting on a wooden bench",                          "a park"),
    ("medium shot",     "kneeling on one knee",                               "a forest clearing"),
    ("medium shot",     "gesturing with one hand while speaking",             "an interior room"),
    ("medium shot",     "leaning against a wall",                             "a narrow alley"),
    ("medium shot",     "crouching low",                                      "a rocky hillside"),
    ("medium shot",     "reaching toward something out of frame",             "a wooden interior"),
    ("medium shot",     "turning to look to the side",                        "a stone courtyard"),
    ("wide shot",       "standing still",                                     "an open field"),
    ("wide shot",       "walking away from the camera",                       "a forest trail"),
    ("wide shot",       "running",                                            "a beach"),
    ("wide shot",       "standing on stone steps",                            "a stone courtyard"),
    ("wide shot",       "sitting on the ground",                              "a grassy hillside"),
    ("wide shot",       "walking from left to right",                         "a city street"),
]

DESCRIBE_PROMPT = (
    'Describe the main character in this image for an image generator that must redraw the same '
    'person in many different poses and places. Reply with only a JSON object with two keys. '
    '"class_noun": one lowercase word for what they are (for example woman, man, girl, boy, person). '
    '"descriptor": one noun phrase of at most 45 words that starts with "a" or "an" and covers only '
    'what is visible about the character themselves: apparent age group, apparent ethnicity when it '
    'is visible, build, skin tone, hair colour, length and style, notable facial features, and the '
    'clothing and accessories they would wear anywhere. Leave out anything that belongs to this one '
    'situation rather than to the person: footwear, gear or props that are visible only because of '
    'what they are doing here (for example riding boots while riding, or a tool they are using), '
    'anything they are holding, and any animal or vehicle. Do not mention the background, the pose, '
    'the action, the camera, the lighting or the image style.'
)

FACE_PROMPT = (
    'Reply with only a JSON object with one key. "face_box": the bounding box of the main '
    "character's face, from the top of the forehead to the chin and from ear to ear, as "
    '[x1, y1, x2, y2] in coordinates from 0 to 1000, where 0,0 is the top-left corner of the image '
    'and 1000,1000 is the bottom-right corner; or null if no face is visible.'
)

CHECK_PROMPT = (
    'The first image shows the reference character. The second image is a candidate picture. '
    'Reply with only a JSON object with four keys. '
    '"identity_score": an integer from 1 to 10 for how clearly the candidate shows the same character '
    'as the reference (face, hair and clothing), where 10 is unmistakably the same and 1 is a different '
    'person. '
    '"shot": exactly one of extreme wide shot, wide shot, medium shot, medium close-up, close-up, '
    'extreme close-up, describing the candidate. '
    '"pose": at most 12 words describing the candidate\'s pose or action, without pronouns. '
    '"setting": at most 8 words naming the candidate\'s surroundings.'
)

FACE_MIN_HEIGHT = 0.15
CREATE_MIN_FREE_GIB = 2.0
TRAIN_MIN_FREE_GIB_PER_KIND = 8.0
TRAIN_MIN_AVAIL_GIB = 30.0
GENERATE_MIN_AVAIL_GIB = 20.0
VLM_WAIT_S = 600
AVAIL_WAIT_S = 600

TRAIN_MODEL_DIR = os.path.join(SKILL.LTX2_MLX_DIR, "models", "ltx-2.3-mlx-q8-dev")
TEST_MODEL_DIR = os.path.join(SKILL.LTX2_MLX_DIR, "models", "ltx-2.5-mlx-q8")
VIDEO_RANK = 32
VIDEO_STEPS = 1000
VIDEO_FINAL_CKPT = "lora_weights_step_01000.safetensors"
STILLS_RANK = 16
STILLS_TARGET_STEPS = 2400
MFLUX_TRAIN = os.environ.get("CHARACTER_MFLUX_TRAIN",
                             os.path.expanduser("~/mflux/.venv/bin/mflux-train"))
MFLUX_HF_HOME = os.environ.get("Z_IMAGE_HF_HOME", os.path.expanduser("~/hf_home"))

PREPROCESS_TIMEOUT_S = 1800
VIDEO_TRAIN_TIMEOUT_S = 14400
STILLS_TRAIN_TIMEOUT_S = 21600
TEST_RENDER_TIMEOUT_S = 1800
ZIMAGE_CHILD_TIMEOUT_S = 3600

TEST_SEED = 42


class DatasetError(Exception):
    """A dataset, training or safety-gate failure; printed after "Error: "."""


# ---------------------------------------------------------------------------
# Pure helpers (copied verbatim from make_dataset_seed.py)
# ---------------------------------------------------------------------------

def extract_json(text):
    """Parse a JSON dict from model output; raise ValueError on failure."""
    text = text.strip()
    fence_match = re.search(r'```(?:json)?\s*(.*?)```', text, re.DOTALL)
    if fence_match:
        raw = fence_match.group(1).strip()
    else:
        idx = text.find("{")
        if idx == -1:
            raise ValueError("no JSON object found in text")
        raw = text[idx:]
    try:
        obj, _ = json.JSONDecoder().raw_decode(raw)
    except json.JSONDecodeError as e:
        raise ValueError("JSON decode error: %s" % e)
    if not isinstance(obj, dict):
        raise ValueError("expected a JSON object, got %s" % type(obj).__name__)
    return obj


def validate_description(d):
    """Validate describe-phase response dict; return (class_noun, descriptor)."""
    if "class_noun" not in d:
        raise ValueError("missing key: class_noun")
    if "descriptor" not in d:
        raise ValueError("missing key: descriptor")
    class_noun = d["class_noun"]
    if not isinstance(class_noun, str):
        raise ValueError("class_noun must be a string")
    class_noun = class_noun.lower().strip()
    if not re.match(r'^[a-z]+$', class_noun):
        raise ValueError("class_noun must match ^[a-z]+$, got %r" % class_noun)
    if not (3 <= len(class_noun) <= 12):
        raise ValueError("class_noun length must be 3-12, got %d" % len(class_noun))
    descriptor = d["descriptor"]
    if not isinstance(descriptor, str):
        raise ValueError("descriptor must be a string")
    descriptor = descriptor.strip()
    if descriptor.endswith("."):
        descriptor = descriptor[:-1].strip()
    words = descriptor.split()
    if not (8 <= len(words) <= 60):
        raise ValueError("descriptor word count must be 8-60, got %d" % len(words))
    # Normalise first letter to lowercase
    if descriptor and descriptor[0].isupper():
        descriptor = descriptor[0].lower() + descriptor[1:]
    if not re.match(r'^(a |an )', descriptor, re.IGNORECASE):
        raise ValueError("descriptor must start with 'a ' or 'an ', got %r" % descriptor[:30])
    return class_noun, descriptor


def validate_check(d):
    """Validate check-phase response dict; return normalised dict."""
    if "identity_score" not in d:
        raise ValueError("missing key: identity_score")
    score = d["identity_score"]
    if isinstance(score, bool):
        raise ValueError("identity_score must be int, not bool")
    if not isinstance(score, int):
        raise ValueError("identity_score must be int, got %s" % type(score).__name__)
    if not (1 <= score <= 10):
        raise ValueError("identity_score must be 1-10, got %d" % score)
    if "shot" not in d:
        raise ValueError("missing key: shot")
    shot = d["shot"]
    if not isinstance(shot, str):
        raise ValueError("shot must be a string")
    shot = shot.lower().strip()
    if shot not in SHOTS:
        raise ValueError("shot %r not in SHOTS" % shot)
    if "pose" not in d:
        raise ValueError("missing key: pose")
    pose = d["pose"]
    if not isinstance(pose, str):
        raise ValueError("pose must be a string")
    pose = pose.strip()
    if pose.endswith("."):
        pose = pose[:-1].strip()
    pose_words = pose.split()
    if not (1 <= len(pose_words) <= 12):
        raise ValueError("pose word count must be 1-12, got %d" % len(pose_words))
    if "setting" not in d:
        raise ValueError("missing key: setting")
    setting = d["setting"]
    if not isinstance(setting, str):
        raise ValueError("setting must be a string")
    setting = setting.strip()
    if setting.endswith("."):
        setting = setting[:-1].strip()
    if setting.lower().startswith("in "):
        setting = setting[3:].strip()
    setting_words = setting.split()
    if not (1 <= len(setting_words) <= 8):
        raise ValueError("setting word count must be 1-8, got %d" % len(setting_words))
    return {
        "identity_score": score,
        "shot": shot,
        "pose": pose,
        "setting": setting,
    }


def gen_prompt(shot, pose, setting, descriptor):
    """Build an image-generation prompt."""
    shot_cap = shot[0].upper() + shot[1:]
    return "%s of %s, %s, in %s. %s." % (shot_cap, descriptor, pose, setting, STYLE)


def caption(trigger, class_noun, check):
    """Build a training caption string."""
    return "%s %s, %s, %s, in %s, %s." % (
        trigger, class_noun, check["shot"], check["pose"], check["setting"], STYLE
    )


def image_data_url(path, max_side=768):
    """Return a data URL for the image at path, scaled so max side <= max_side."""
    img = Image.open(path).convert("RGB")
    img.thumbnail((max_side, max_side), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=90)
    b64 = base64.b64encode(buf.getvalue()).decode("ascii")
    return "data:image/jpeg;base64," + b64


def vlm_call(content_parts, max_tokens=600):
    """POST to the VLM and return the reply text; raise RuntimeError on failure."""
    payload = json.dumps({
        "model": VLM_MODEL,
        "messages": [{"role": "user", "content": content_parts}],
        "temperature": 0,
        "max_tokens": max_tokens,
        "chat_template_kwargs": {"enable_thinking": False},
    }).encode()
    req = urllib.request.Request(
        VLM_URL,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=300) as resp:
            body = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        raise RuntimeError("HTTP %d from VLM: %s" % (e.code, e.read().decode(errors="replace")))
    except Exception as e:
        raise RuntimeError("VLM request failed: %s" % e)
    try:
        return body["choices"][0]["message"]["content"]
    except (KeyError, IndexError) as e:
        raise RuntimeError("unexpected VLM response shape: %s" % e)


def verify_ffprobe(mp4):
    """Check that mp4 has exactly 1 frame via ffprobe; raise DatasetError on failure."""
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-count_frames", "-show_entries", "stream=nb_read_frames",
         "-of", "default=nokey=1:noprint_wrappers=1", mp4],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        raise DatasetError("ffprobe failed for %s: %s" % (mp4, result.stderr.strip()))
    nb = result.stdout.strip()
    if nb != "1":
        raise DatasetError("ffprobe: expected 1 frame in %s, got %r" % (mp4, nb))


def validate_face(d):
    """Face height as a fraction of the image height, or None when no face is visible.
    Raises ValueError on any malformed reply (spec 4.5)."""
    if "face_box" not in d:
        raise ValueError("missing key: face_box")
    box = d["face_box"]
    if box is None:
        return None
    if (not isinstance(box, list) or len(box) != 4
            or any(isinstance(v, bool) or not isinstance(v, (int, float)) for v in box)):
        raise ValueError("face_box must be null or a list of 4 numbers, got %r" % (box,))
    x1, y1, x2, y2 = box
    if not (0 <= x1 < x2 <= 1000 and 0 <= y1 < y2 <= 1000):
        raise ValueError("face_box must satisfy 0 <= x1 < x2 <= 1000 and 0 <= y1 < y2 <= 1000, "
                         "got %r" % (box,))
    return (y2 - y1) / 1000.0


def trigger_test_prompt(trigger, class_noun):
    return "%s %s, medium shot, standing and facing the camera, %s." % (trigger, class_noun, STYLE)


# ---------------------------------------------------------------------------
# Safety gates and process helpers (spec 4.8, 4.12)
# ---------------------------------------------------------------------------

_STATE_RE = re.compile(r"^\s*state:\s*(.+?)\s*$")


def vlm_ready():
    try:
        req = urllib.request.Request(MODELS_URL, method="GET")
        with urllib.request.urlopen(req, timeout=10) as resp:
            body = json.loads(resp.read())
        return VLM_MODEL in [m["id"] for m in body["data"]]
    except Exception:
        return False


def story_server(cmd):
    """Run bin/story-server CMD, print the last 5 lines of its output, return its exit code."""
    result = subprocess.run([STORY_SERVER, cmd], capture_output=True, text=True)
    tail_lines = (result.stdout + result.stderr).strip().splitlines()
    for line in tail_lines[-5:]:
        print(line)
    return result.returncode


def story_server_state():
    """The value of bin/story-server status's "state:" line (SERVING <mode>, FOREIGN pid N,
    LOADING <mode> or STOPPED), or "UNKNOWN" on any failure, which callers treat as not
    stopped (fail closed)."""
    try:
        proc = subprocess.run([STORY_SERVER, "status"], capture_output=True, text=True,
                              timeout=60)
    except (OSError, subprocess.TimeoutExpired):
        return "UNKNOWN"
    if proc.returncode != 0:
        return "UNKNOWN"
    for line in proc.stdout.splitlines():
        match = _STATE_RE.match(line)
        if match:
            return match.group(1)
    return "UNKNOWN"


def wait_for_vlm(timeout_s):
    deadline = time.monotonic() + timeout_s
    while True:
        if vlm_ready():
            return True
        if time.monotonic() > deadline:
            return False
        time.sleep(10)


def wait_for_avail(min_gib, timeout_s):
    deadline = time.monotonic() + timeout_s
    while psutil.virtual_memory().available < min_gib * 2 ** 30:
        if time.monotonic() > deadline:
            return False
        time.sleep(5)
    return True


def busy_process():
    """(pid, first 120 characters of its command line) for the first render, training or
    Z-Image process found, else None. Fail-closed by design (spec 4.12, G17)."""
    skip = {os.getpid(), os.getppid()}
    for proc in psutil.process_iter(["pid", "cmdline"]):
        try:
            pid = proc.info["pid"]
            cmdline = proc.info["cmdline"] or []
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
        if pid in skip:
            continue
        joined = " ".join(cmdline)
        if (("ltx-2-mlx" in joined
             and any(t in cmdline for t in ("generate", "train", "preprocess")))
                or any(marker in joined for marker in (
                    "mflux-train", "bin/ltx-movie", "bin/ltx-mlx-render",
                    "bin/ltx-story-images", "character_dataset.py zimage"))):
            return pid, joined[:120]
    return None


def free_gib(path):
    path = os.path.abspath(path)
    while not os.path.exists(path):
        parent = os.path.dirname(path)
        if parent == path:
            break
        path = parent
    return shutil.disk_usage(path).free / 2 ** 30


def _lock_holder(path):
    try:
        with open(path, encoding="utf-8") as f:
            pid = int(f.read().strip())
    except (OSError, ValueError):
        return None
    if pid <= 0:
        return None
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return None
    except PermissionError:
        return pid
    return pid


@contextlib.contextmanager
def library_lock():
    """Hold <library>/.lock (holding our pid) for the duration of the block. A lock held by
    a live pid raises DatasetError; a dead or unreadable one is removed and retried once."""
    lib = character_lib.library_dir()
    os.makedirs(lib, exist_ok=True)
    path = os.path.join(lib, character_lib.LOCK_NAME)
    for attempt in range(2):
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
        except FileExistsError:
            holder = _lock_holder(path)
            if holder is not None:
                raise DatasetError("another bin/character create/train is running (pid %d); "
                                   "run one at a time" % holder)
            if attempt == 1:
                raise DatasetError("could not acquire the library lock %s" % path)
            with contextlib.suppress(FileNotFoundError):
                os.remove(path)
            continue
        with os.fdopen(fd, "w") as f:
            f.write(str(os.getpid()))
        break
    try:
        yield path
    finally:
        with contextlib.suppress(FileNotFoundError):
            os.remove(path)


def run_logged(cmd, log_path, cwd, env, timeout_s):
    """Run cmd with stdout+stderr merged, streaming every line to sys.stdout and to log_path
    (appended). A watchdog SIGKILLs the whole process group after timeout_s. Returns the
    exit code, or -9 after a timeout kill."""
    print("Running: %s" % shlex.join(cmd))
    print("log: %s" % log_path)
    sys.stdout.flush()
    timed_out = [False]
    with open(log_path, "a") as logf:
        proc = subprocess.Popen(cmd, cwd=cwd, env=env, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, text=True, bufsize=1,
                                start_new_session=True)

        def _kill_group():
            timed_out[0] = True
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            except OSError:
                pass

        timer = threading.Timer(timeout_s, _kill_group)
        timer.daemon = True
        timer.start()
        try:
            for line in proc.stdout:
                sys.stdout.write(line)
                sys.stdout.flush()
                logf.write(line)
                logf.flush()
            proc.wait()
        finally:
            timer.cancel()
    return -9 if timed_out[0] else proc.returncode


def step_log_path(char_dir, step):
    logs = os.path.join(char_dir, "logs")
    os.makedirs(logs, exist_ok=True)
    return os.path.join(logs, "%s-%s.log" % (time.strftime("%Y%m%dT%H%M%SZ", time.gmtime()), step))


def _error(message):
    print("Error: %s" % message, file=sys.stderr)
    return 2


def _sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


# ---------------------------------------------------------------------------
# VLM analysis (spec 4.4 helpers, 4.5)
# ---------------------------------------------------------------------------

def face_height(seed_path):
    content_parts = [{"type": "text", "text": FACE_PROMPT},
                     {"type": "image_url", "image_url": {"url": image_data_url(seed_path)}}]
    reply, error = None, None
    for _attempt in range(2):
        reply = vlm_call(content_parts)
        try:
            return validate_face(extract_json(reply))
        except ValueError as e:
            error = e
    raise DatasetError("face check failed: %s; last reply: %r" % (error, reply))


def describe(seed_path):
    """(class_noun, descriptor, raw reply) for the seed image's main character."""
    content_parts = [{"type": "text", "text": DESCRIBE_PROMPT},
                     {"type": "image_url", "image_url": {"url": image_data_url(seed_path)}}]
    reply, error = None, None
    for _attempt in range(2):
        reply = vlm_call(content_parts)
        try:
            class_noun, descriptor = validate_description(extract_json(reply))
            character_lib.validate_descriptor(descriptor)
            return class_noun, descriptor, reply
        except (ValueError, character_lib.CharacterError) as e:
            error = e
    raise DatasetError("describe failed: %s; last reply: %r" % (error, reply))


def score_still(ref_path, cand_path):
    """(normalized check dict, None), or the zero-score dict and an "unparseable: ..." reason
    after two unparseable replies. A RuntimeError from the VLM call propagates."""
    content_parts = [{"type": "text", "text": CHECK_PROMPT},
                     {"type": "image_url", "image_url": {"url": image_data_url(ref_path)}},
                     {"type": "image_url", "image_url": {"url": image_data_url(cand_path)}}]
    error = None
    for _attempt in range(2):
        reply = vlm_call(content_parts)
        try:
            return validate_check(extract_json(reply)), None
        except ValueError as e:
            error = e
    return ({"identity_score": 0, "shot": "", "pose": "", "setting": ""},
            "unparseable: %s" % error)


# ---------------------------------------------------------------------------
# Dataset building: create (spec 4.4, 4.6, 4.7)
# ---------------------------------------------------------------------------

def wrap_still(png, mp4):
    """Wrap one still into a 1-frame h264 mp4 (the make_dataset_seed.py ffmpeg argv)."""
    try:
        subprocess.run(
            ["ffmpeg", "-v", "error", "-nostdin", "-y",
             "-loop", "1", "-i", png,
             "-frames:v", "1", "-r", "24",
             "-c:v", "libx264", "-pix_fmt", "yuv420p", mp4],
            check=True,
        )
    except subprocess.CalledProcessError as e:
        raise DatasetError("ffmpeg failed to wrap %s into %s (exit %d)" % (png, mp4, e.returncode))
    except OSError as e:
        raise DatasetError("ffmpeg could not be run to wrap %s: %s" % (png, e))


def write_contact_sheet(items, stills_dir, out_path):
    cols, tw, th, lh = 5, 256, 160, 20
    rows = (len(items) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * tw, rows * (th + lh)), (0, 0, 0))
    draw = ImageDraw.Draw(sheet)
    for k, item in enumerate(items):
        x, y = (k % cols) * tw, (k // cols) * (th + lh)
        path = os.path.join(stills_dir, "char_%02d.png" % item["n"])
        if os.path.isfile(path):
            with Image.open(path) as img:
                sheet.paste(img.convert("RGB").resize((tw, th), Image.LANCZOS), (x, y))
        if not item["kept"]:
            draw.rectangle([x, y, x + tw - 1, y + th - 1], outline=(255, 0, 0), width=4)
        draw.text((x + 4, y + th + 3), "%02d  score %d  %s"
                  % (item["n"], item["identity_score"], "kept" if item["kept"] else "DROPPED"),
                  fill=(255, 255, 255))
    sheet.save(out_path, format="JPEG", quality=90)


def build_dataset(data, face_height):
    """Generate, score, caption and wrap the dataset for character.json data; write
    dataset/manifest.json, dataset/contact_sheet.jpg and the updated character.json.
    Returns 0, 1 (a DatasetError or RuntimeError, printed; status stays "dataset") or 3
    (fewer than MIN_KEEP stills kept)."""
    try:
        return _build_dataset(data, face_height)
    except (DatasetError, RuntimeError) as e:
        print("Error: %s" % e, file=sys.stderr)
        return 1


def _build_dataset(data, face_height):
    name = data["name"]
    char_dir = character_lib.character_dir(name)
    json_path = character_lib.character_json_path(name)
    dataset_dir = os.path.join(char_dir, "dataset")
    stills_dir = os.path.join(dataset_dir, "stills")
    captions_dir = os.path.join(dataset_dir, "captions")
    videos_dir = os.path.join(dataset_dir, "videos")
    seed_mode = data["source"]["type"] == "seed_image"
    if seed_mode:
        with Image.open(os.path.join(char_dir, "seed.png")) as img:
            ImageOps.fit(img.convert("RGB"), (WIDTH, HEIGHT), Image.LANCZOS,
                         centering=(0.5, 0.5)).save(os.path.join(stills_dir, "char_00.png"))
    spec = {"jobs": [{"prompt": gen_prompt(shot, pose, setting, data["descriptor"]),
                      "output_path": os.path.join(stills_dir, "char_%02d.png" % i),
                      "seed": data["seed"], "width": WIDTH, "height": HEIGHT}
                     for i, (shot, pose, setting) in enumerate(VARIANTS, 1)],
            "loras": None}

    print("=== generate ===")
    rc = story_server("stop")
    if rc != 0:
        print("warning: story-server stop returned %d" % rc, file=sys.stderr)
    try:
        if not wait_for_avail(GENERATE_MIN_AVAIL_GIB, AVAIL_WAIT_S):
            raise DatasetError("timed out waiting for 20 GiB available memory after stopping the "
                               "story server")
        run_zimage_child(spec, char_dir, "generate")
    finally:
        rc = story_server("vision")
        if rc != 0:
            print("warning: story-server vision returned %d" % rc, file=sys.stderr)
        if not wait_for_vlm(VLM_WAIT_S):
            raise DatasetError("timed out waiting for the vision server to come back")

    ref_n = 0 if seed_mode else 1
    ref_png = os.path.join(stills_dir, "char_%02d.png" % ref_n)
    if not os.path.isfile(ref_png):
        raise DatasetError("the reference still char_%02d was blocked by the content screen; edit "
                           "the descriptor in %s and run bin/character create %s --regenerate"
                           % (ref_n, json_path, name))

    print("=== score ===")
    items = []
    for n in (range(0, 25) if seed_mode else range(1, 25)):
        png = os.path.join(stills_dir, "char_%02d.png" % n)
        gen_prompt_str = None
        if n > 0:
            shot, pose, setting = VARIANTS[n - 1]
            gen_prompt_str = gen_prompt(shot, pose, setting, data["descriptor"])
        if not os.path.isfile(png):
            items.append({"n": n, "gen_prompt": gen_prompt_str, "identity_score": 0, "shot": "",
                          "pose": "", "setting": "", "kept": False,
                          "reason": "blocked by the content screen", "caption": None})
            continue
        check_result, reason = score_still(ref_png, png)
        kept = (n == ref_n) or check_result["identity_score"] >= character_lib.MIN_SCORE
        cap = None
        if kept:
            cap = caption(data["trigger"], data["class_noun"], check_result)
            with open(os.path.join(captions_dir, "char_%02d.txt" % n), "w") as f:
                f.write(cap)
            mp4 = os.path.join(videos_dir, "char_%02d.mp4" % n)
            wrap_still(png, mp4)
            verify_ffprobe(mp4)
        items.append({
            "n":              n,
            "gen_prompt":     gen_prompt_str,
            "identity_score": check_result["identity_score"],
            "shot":           check_result["shot"],
            "pose":           check_result["pose"],
            "setting":        check_result["setting"],
            "kept":           kept,
            "reason":         reason,
            "caption":        cap,
        })

    manifest = {"seed_image": data["source"].get("path"), "trigger": data["trigger"],
                "class_noun": data["class_noun"], "descriptor": data["descriptor"],
                "seed": data["seed"], "min_score": character_lib.MIN_SCORE,
                "reference": "char_%02d" % ref_n, "face_height": face_height, "items": items}
    with open(os.path.join(dataset_dir, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)
    sheet = os.path.join(dataset_dir, "contact_sheet.jpg")
    write_contact_sheet(items, stills_dir, sheet)

    kept_count = sum(1 for item in items if item["kept"])
    total = len(items)
    data["dataset"] = {"reference": "char_%02d" % ref_n, "kept": kept_count, "total": total,
                       "min_score": character_lib.MIN_SCORE, "face_height": face_height,
                       "contact_sheet": sheet}
    data["status"] = "untrained" if kept_count >= character_lib.MIN_KEEP else "dataset"
    character_lib.write_character(data)

    print("%-4s %-6s %-5s %s" % ("n", "score", "kept", "caption"))
    for item in items:
        cap_str = item["caption"] or "(dropped)"
        print("%-4d %-6d %-5s %s" % (
            item["n"], item["identity_score"], str(item["kept"]), cap_str
        ))
    print("dataset: %d/%d stills kept (minimum %d) in %s"
          % (kept_count, total, character_lib.MIN_KEEP, dataset_dir))
    print("contact sheet: %s" % sheet)
    if kept_count < character_lib.MIN_KEEP:
        print('Error: only %d/%d stills kept (need %d); the dataset is kept in %s; edit '
              '"descriptor" in %s and run bin/character create %s --regenerate'
              % (kept_count, total, character_lib.MIN_KEEP, dataset_dir, json_path, name),
              file=sys.stderr)
        return 3
    print('next: review the contact sheet. To change the look, edit "descriptor" in %s and run '
          'bin/character create %s --regenerate; otherwise run bin/character train %s'
          % (json_path, name, name))
    return 0


def _face_problem(fh):
    """(error text, warning text) for a seed face that is missing or below FACE_MIN_HEIGHT
    (spec 4.5, CE18)."""
    if fh is None:
        return ("the vision model found no face in the seed image; pass --force to proceed anyway.",
                "the vision model found no face in the seed image; proceeding (--force)")
    head = ("the main character's face fills only %d%% of the seed image's height (minimum 15%%); "
            "a small face makes a weak identity reference" % round(100 * fh))
    return (head + ". Use a closer crop of the character, or pass --force to proceed anyway.",
            head + "; proceeding (--force)")


def create(args):
    """bin/character create (spec 4.4). Returns 0, 1, 2 or 3."""
    import ltx_image_fit
    name = args.name
    try:
        character_lib.validate_name(name)
    except character_lib.CharacterError as e:
        return _error(e)
    char_dir = character_lib.character_dir(name)
    json_path = character_lib.character_json_path(name)
    data = None
    if args.regenerate:
        if (any(v is not None for v in (args.phrase, args.seed_image, args.descriptor,
                                        args.class_noun, args.trigger, args.seed))
                or args.force):
            return _error("--regenerate takes no --phrase, --seed-image, --descriptor, --class, "
                          "--trigger, --seed or --force; edit %s instead" % json_path)
        try:
            data = character_lib.load_character(name)
        except character_lib.CharacterError as e:
            return _error(e)
        if data["status"] == "trained":
            return _error("character %s is trained; regenerating its dataset would orphan its "
                          "LoRAs. Create a new character instead" % name)
    else:
        if os.path.exists(char_dir):
            return _error("character %s already exists (%s); use --regenerate to rebuild its "
                          "dataset" % (name, char_dir))
        if args.phrase is None:
            return _error("create needs --phrase")
        try:
            phrase = character_lib.normalize_phrase(args.phrase)
        except character_lib.CharacterError as e:
            return _error("--phrase: %s" % e)
        if (args.seed_image is None) == (args.descriptor is None):
            return _error("create needs exactly one of --seed-image or --descriptor")
        if args.class_noun is not None:
            try:
                character_lib.validate_class_noun(args.class_noun)
            except character_lib.CharacterError as e:
                return _error(e)
        elif args.descriptor is not None:
            return _error("--descriptor needs --class NOUN (there is no image to take it from)")
        seed_path = descriptor = None
        if args.descriptor is not None:
            try:
                _, descriptor = validate_description({"class_noun": args.class_noun,
                                                      "descriptor": args.descriptor})
                character_lib.validate_descriptor(descriptor)
            except (ValueError, character_lib.CharacterError) as e:
                return _error("--descriptor: %s" % e)
        else:
            seed_path = os.path.abspath(args.seed_image)
            if not os.path.isfile(seed_path):
                return _error("--seed-image not found: %s" % seed_path)
            try:
                ltx_image_fit.load_oriented_rgb(seed_path)
            except Exception as e:
                return _error("--seed-image is not a readable image: %s: %s" % (seed_path, e))
        seed = args.seed if args.seed is not None else 0
        if seed < 0:
            return _error("--seed must be >= 0")
        if args.trigger is not None:
            try:
                character_lib.validate_trigger(args.trigger)
            except character_lib.CharacterError as e:
                return _error(e)
            owner = character_lib.registered_triggers().get(args.trigger)
            if owner is not None:
                return _error("trigger %s is already used by character %s; triggers are never "
                              "reused" % (args.trigger, owner))
            if (args.trigger in [w.lower() for w in phrase.split()]
                    or args.trigger == args.class_noun):
                return _error("trigger %s must not be a word of the phrase or the class noun"
                              % args.trigger)

    with contextlib.ExitStack() as stack:
        try:
            stack.enter_context(library_lock())
        except DatasetError as e:
            return _error(e)
        busy = busy_process()
        if busy is not None:
            return _error("a render or training process is running (pid %d: %s); bin/character "
                          "never trains or generates concurrently with a render" % busy)
        lib = character_lib.library_dir()
        free = free_gib(lib)
        if free < CREATE_MIN_FREE_GIB:
            return _error("only %.1f GiB free at %s; create needs 2 GiB" % (free, lib))
        if not vlm_ready():
            return _error("the vision model %s is not being served at %s; start it with: "
                          "bin/story-server vision" % (VLM_MODEL, MODELS_URL))

        if data is not None:
            return _regenerate(data)

        fh = raw = cls_vlm = None
        try:
            if seed_path is not None:
                fh = face_height(seed_path)
                if fh is None or fh < FACE_MIN_HEIGHT:
                    error_text, warning_text = _face_problem(fh)
                    if not args.force:
                        return _error(error_text)
                    print("Warning: %s" % warning_text, file=sys.stderr)
                cls_vlm, descriptor, raw = describe(seed_path)
                cls = args.class_noun or cls_vlm
            else:
                cls = args.class_noun
        except (DatasetError, RuntimeError) as e:
            print("Error: %s" % e, file=sys.stderr)
            return 1
        trigger = args.trigger or character_lib.auto_trigger(
            name, cls, character_lib.registered_triggers(), avoid=phrase.split())
        if args.trigger is not None and trigger == cls:
            return _error("trigger %s must not be a word of the phrase or the class noun" % trigger)

        for sub in ("stills", "captions", "videos"):
            os.makedirs(os.path.join(char_dir, "dataset", sub), exist_ok=True)
        os.makedirs(os.path.join(char_dir, "logs"), exist_ok=True)
        if seed_path is not None:
            ltx_image_fit.load_oriented_rgb(seed_path).save(os.path.join(char_dir, "seed.png"),
                                                            format="PNG")
            with open(os.path.join(char_dir, "dataset", "description.json"), "w",
                      encoding="utf-8") as f:
                json.dump({"class_noun": cls_vlm, "descriptor": descriptor, "raw": raw}, f,
                          indent=2)
        character_lib.register_trigger(trigger, name)
        data = {"schema_version": character_lib.SCHEMA_VERSION, "name": name, "trigger": trigger,
                "class_noun": cls, "referring_phrase": phrase, "descriptor": descriptor,
                "seed": seed,
                "source": ({"type": "seed_image", "path": seed_path} if seed_path is not None
                           else {"type": "descriptor"}),
                "strength": None, "status": "dataset", "created_at": character_lib.utc_now(),
                "dataset": None, "loras": {"video": None, "stills": None},
                "stills_skip_reason": None}
        character_lib.write_character(data)
        return build_dataset(data, fh)


def _regenerate(data):
    """create --regenerate after its preflights: wipe and rebuild dataset/ from character.json,
    keeping face_height and dataset/description.json; no face check, no describe."""
    prev_fh = data["dataset"]["face_height"] if data["dataset"] else None
    dataset_dir = os.path.join(character_lib.character_dir(data["name"]), "dataset")
    description = os.path.join(dataset_dir, "description.json")
    saved_description = None
    if os.path.isfile(description):
        with open(description, "rb") as f:
            saved_description = f.read()
    if os.path.isdir(dataset_dir):
        shutil.rmtree(dataset_dir)
    for sub in ("stills", "captions", "videos"):
        os.makedirs(os.path.join(dataset_dir, sub))
    if saved_description is not None:
        with open(description, "wb") as f:
            f.write(saved_description)
    data["status"] = "dataset"
    data["dataset"] = None
    character_lib.write_character(data)
    return build_dataset(data, prev_fh)


# --- Z-Image child process (spec 4.9) ---

def run_zimage_child(spec, char_dir, step):
    """Run the jobs in spec through z_image_skill in a child process and return its report:
    {"jobs": [{"output_path", "status", "seconds"}], "injected_lora_modules": N or None}."""
    log = step_log_path(char_dir, step)
    stem = log[:-len(".log")]
    spec_path = stem + ".spec.json"
    report_path = stem + ".report.json"
    with open(spec_path, "w", encoding="utf-8") as f:
        json.dump(dict(spec, report_path=report_path), f, indent=2)
    rc = run_logged([sys.executable, os.path.join(WS, "character_dataset.py"), "zimage",
                     "--spec", spec_path], log, WS, dict(os.environ), ZIMAGE_CHILD_TIMEOUT_S)
    if rc != 0:
        error = DatasetError("Z-Image child process exited %d; log: %s" % (rc, log))
        error.log_path = log
        raise error
    with open(report_path, encoding="utf-8") as f:
        return json.load(f)


def child_zimage(spec_path):
    """The child side: render every job, count the injected LoRA modules, write the report.
    Imports the heavy stack here and only here."""
    import torch
    import z_image_skill
    from content_safety import ContentSafetyError

    with open(spec_path, encoding="utf-8") as f:
        spec = json.load(f)
    kwargs = {"loras": [tuple(x) for x in spec["loras"]]} if spec["loras"] else {}
    jobs = []
    for job in spec["jobs"]:
        started = time.monotonic()
        try:
            z_image_skill.generate_image(job["prompt"], output_path=job["output_path"],
                                         width=job["width"], height=job["height"],
                                         generator=torch.Generator("cpu").manual_seed(job["seed"]), **kwargs)
            status = "ok"
        except ContentSafetyError:
            status = "blocked"
        jobs.append({"output_path": job["output_path"], "status": status,
                     "seconds": round(time.monotonic() - started, 1)})
    injected = None
    if spec["loras"] and z_image_skill._pipeline is not None:
        injected = sum(1 for module in z_image_skill._pipeline.transformer.modules()
                       if isinstance(getattr(module, "lora_A", None), torch.nn.ModuleDict)
                       and "lora0" in module.lora_A)
    with open(spec["report_path"], "w", encoding="utf-8") as f:
        json.dump({"jobs": jobs, "injected_lora_modules": injected}, f, indent=2)
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="character_dataset.py",
        description="bin/character's internal helper: the Z-Image child process.")
    sub = parser.add_subparsers(dest="command", metavar="COMMAND")
    sub.required = True
    z = sub.add_parser("zimage", help="render a spec file's jobs with z_image_skill")
    z.add_argument("--spec", required=True, metavar="PATH")
    args = parser.parse_args(argv)
    return child_zimage(args.spec)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
