"""Shared helpers for tests/test_story_engine.py and tests/test_lora_catalog.py (robust story
engine and LoRA catalog spec, docs/superpowers/specs/2026-10-17-robust-story-lora-catalog-design.md
Section 5.2).

Not a test module (pytest does not collect it). Every helper writes under a tmp_path the caller
passes in; nothing here reads or writes the real HOME, generated/loras/ or generated/characters/.
REAL_CATALOG_STAT is captured when this module is first imported, so RST63 can prove the real
catalog file was never touched during the session.
"""

import hashlib
import json
import os
import struct
import sys

WS = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
TESTS = os.path.join(WS, "tests")
sys.path.insert(0, WS)
sys.path.insert(0, TESTS)

import fleet_testutil  # noqa: E402

REAL_CATALOG = os.path.join(WS, "generated", "loras", "catalog.json")


def _stat_or_none(path):
    try:
        info = os.stat(path)
    except OSError:
        return None
    return (info.st_size, info.st_mtime_ns)


REAL_CATALOG_STAT = _stat_or_none(REAL_CATALOG)

DESC_K = "a young woman with long black hair pinned up with jade hairpins wearing a grey kimono"
DESC_R = "a lean man in his late thirties with a topknot and a scarred brow wearing an indigo haori"
VIDEO_BYTES = b"fake-video-lora!"
STILLS_BYTES = b"fake-stills-lora"
CHARACTER_BASE_MODEL = "MLXBits/ltx-2.3-10eros-v1.2-dmd-mlx-q8"
VIDEO_MODEL = "MLXBits/ltx-2.3-10eros-v1.2-dmd-mlx-q8"
STILLS_MODEL = "Tongyi-MAI/Z-Image-Turbo"


def set_story_env(monkeypatch, tmp_path):
    """Section 5.1's environment for one test: HOME, CHARACTER_LIBRARY_DIR and LORA_CATALOG_DIR
    under tmp_path, QWEN_AGENT_DAEMON_URL at a closed loopback port, STORY_PIPELINE_LOGGED=1,
    and no ANTHROPIC_API_KEY. Returns {"home", "lib", "catalog"} (paths as str)."""
    home = os.path.join(str(tmp_path), "home")
    lib = os.path.join(str(tmp_path), "characters")
    catalog = os.path.join(str(tmp_path), "loras")
    for path in (home, lib, catalog):
        os.makedirs(path, exist_ok=True)
    monkeypatch.setenv("HOME", home)
    monkeypatch.setenv("CHARACTER_LIBRARY_DIR", lib)
    monkeypatch.setenv("LORA_CATALOG_DIR", catalog)
    monkeypatch.setenv("QWEN_AGENT_DAEMON_URL", "http://127.0.0.1:%d" % fleet_testutil.free_port())
    monkeypatch.setenv("STORY_PIPELINE_LOGGED", "1")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("QWEN_AGENT_PREFLIGHT_DONE", raising=False)
    return {"home": home, "lib": lib, "catalog": catalog}


def fake_safetensors(path, rank, alpha, pairs=True, metadata=None, data=b"\x00" * 16):
    """Write a minimal safetensors file: an 8-byte little-endian header length, the JSON
    header (one lora_A tensor of shape [rank, 8], plus its lora_B pair when pairs, plus
    __metadata__ with lora_alpha when alpha is not None, merged with metadata), then data.
    Returns path."""
    header = {"blocks.0.attn.to_q.lora_A.weight":
              {"dtype": "F16", "shape": [rank, 8], "data_offsets": [0, 8]}}
    if pairs:
        header["blocks.0.attn.to_q.lora_B.weight"] = {"dtype": "F16", "shape": [8, rank],
                                                     "data_offsets": [8, 16]}
    meta = {}
    if alpha is not None:
        meta["lora_alpha"] = str(alpha)
    meta.update(metadata or {})
    if meta:
        header["__metadata__"] = meta
    raw = json.dumps(header).encode("utf-8")
    with open(path, "wb") as f:
        f.write(struct.pack("<Q", len(raw)) + raw + data)
    return path


def sha256_file(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def catalog_entry(path, entry_id, kind="motion", target="video", triggers=(), rank=16,
                  base_models=(VIDEO_MODEL,), default_strength=0.8, strength_range=(0.5, 1.0),
                  description="a test LoRA", use_when="a test fits", avoid_when=""):
    """A valid catalog entry for the existing file at path (sha256 and bytes from the file)."""
    return {"id": entry_id, "kind": kind, "path": os.path.abspath(path),
            "sha256": sha256_file(path), "bytes": os.path.getsize(path),
            "base_models": list(base_models), "target": target, "triggers": list(triggers),
            "rank": rank, "alpha": rank, "default_strength": default_strength,
            "strength_range": list(strength_range), "description": description,
            "use_when": use_when, "avoid_when": avoid_when, "added_at": "2026-10-17T12:00:00Z"}


def make_catalog(directory, entries):
    """Write <directory>/catalog.json with the given entries (sorted by id) and return its
    path. The directory is created."""
    os.makedirs(directory, exist_ok=True)
    path = os.path.join(directory, "catalog.json")
    data = {"schema_version": 1, "entries": sorted(entries, key=lambda e: e["id"])}
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")
    return path


def lora_file(directory, name, rank=16, alpha=None, pairs=True):
    """A fake safetensors LoRA <directory>/<name>.safetensors (alpha defaults to rank)."""
    os.makedirs(directory, exist_ok=True)
    return fake_safetensors(os.path.join(directory, name + ".safetensors"), rank,
                            rank if alpha is None else alpha, pairs=pairs)


def make_character(lib, name, trigger, phrase, class_noun, descriptor, stills=True,
                   strength=None, base_model=CHARACTER_BASE_MODEL):
    """Write a valid trained character.json under lib/name (character library spec 2.2 shape):
    a 16-byte lora/video.safetensors, plus a 16-byte lora/stills.safetensors when stills, each
    entry with its real sha256. Returns the dict."""
    cdir = os.path.join(lib, name)
    os.makedirs(os.path.join(cdir, "lora"), exist_ok=True)
    dataset = {"reference": "char_00", "kept": 24, "total": 25, "min_score": 7,
               "face_height": 0.38,
               "contact_sheet": os.path.join(cdir, "dataset", "contact_sheet.jpg")}
    video_path = os.path.join(cdir, "lora", "video.safetensors")
    with open(video_path, "wb") as f:
        f.write(VIDEO_BYTES)
    video = {"path": video_path, "sha256": hashlib.sha256(VIDEO_BYTES).hexdigest(),
             "base_model": base_model, "rank": 32, "alpha": 32, "steps": 1000,
             "trained_at": "2026-10-06T02:00:00Z", "sample_path": None, "control_path": None}
    stills_entry = None
    if stills:
        stills_path = os.path.join(cdir, "lora", "stills.safetensors")
        with open(stills_path, "wb") as f:
            f.write(STILLS_BYTES)
        stills_entry = {"path": stills_path, "sha256": hashlib.sha256(STILLS_BYTES).hexdigest(),
                        "base_model": STILLS_MODEL, "rank": 16, "alpha": 16, "steps": 2400,
                        "trained_at": "2026-10-06T03:00:00Z", "sample_path": None,
                        "control_path": None}
    data = {"schema_version": 1, "name": name, "trigger": trigger, "class_noun": class_noun,
            "referring_phrase": phrase, "descriptor": descriptor, "seed": 0,
            "source": {"type": "seed_image", "path": "/fixtures/seed.png"},
            "strength": strength, "status": "trained", "created_at": "2026-10-06T01:02:03Z",
            "dataset": dataset, "loras": {"video": video, "stills": stills_entry},
            "stills_skip_reason": None}
    with open(os.path.join(cdir, "character.json"), "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    return data


def kyra(lib, **kw):
    return make_character(lib, "kyra", "kyrawmn", "the woman in grey", "woman", DESC_K, **kw)


def ronin(lib, **kw):
    return make_character(lib, "ronin", "roninmn", "the ronin", "man", DESC_R, **kw)


def make_untrained(lib, name):
    """A valid untrained character (no LoRAs) under lib/name."""
    data = make_character(lib, name, name + "trg", "the " + name, "person",
                          "an old man with a white beard wearing a saffron robe and beads")
    data["status"] = "untrained"
    data["loras"] = {"video": None, "stills": None}
    with open(os.path.join(lib, name, "character.json"), "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    return data


# --- the temp workspace and the fake bin/qwen-agent (spec 5.1, 5.2) ------------------------

LINKED_FILES = ("character_lib.py", "story_engine.py", "lora_catalog.py", "fleet_lib.py",
                "pipeline_log.py", "ltx_image_fit.py", "ltx2_mlx_video_skill.py")

FAKE_AGENT_SOURCE = r'''#!/usr/bin/env python3
"""Fake bin/qwen-agent for the story engine tests (spec 5.2). Pops the next scripted reply for
the stage named by the --user-prompt's first line, logs the call, prints one envelope."""
import json
import os
import re
import sys
import time

argv = sys.argv[1:]
prompt = argv[argv.index("--user-prompt") + 1] if "--user-prompt" in argv else ""
first = prompt.split("\n", 1)[0]
panel = None
if first.startswith("You are planning"):
    stage = "plan"
elif first.startswith("You are writing panel "):
    stage = "panel"
    panel = int(re.match(r"You are writing panel (\d+) of", first).group(1))
elif first.startswith("You are the critic"):
    stage = "critic"
else:
    stage = "unknown"
script_path = os.environ["FAKE_AGENT_SCRIPT"]
with open(script_path, encoding="utf-8") as f:
    script = json.load(f)
queue = None
if stage == "panel":
    panels = script.setdefault("panel", {})
    for key in (str(panel), "*"):
        if panels.get(key):
            queue = panels[key]
            break
elif script.get(stage):
    queue = script[stage]
with open(os.environ["FAKE_AGENT_LOG"], "a", encoding="utf-8") as f:
    f.write(json.dumps({"argv": argv, "stage": stage, "panel": panel,
                        "env_preflight": os.environ.get("QWEN_AGENT_PREFLIGHT_DONE")}) + "\n")
if not queue:
    sys.exit(9)
item = queue.pop(0)
with open(script_path, "w", encoding="utf-8") as f:
    json.dump(script, f)
if item.get("sleep"):
    time.sleep(item["sleep"])
if item.get("no_envelope"):
    print("garbage")
    sys.exit(1)
status = item.get("status", "ok")
answer = item.get("answer")
print("some log line")
print(json.dumps({"schema": "qwen-agent.oneshot.v1", "status": status, "answer": answer,
                  "error": None, "rounds": 1, "tool_calls": 0}))
sys.exit(0 if status == "ok" else 3)
'''


def make_ws(tmp_path, fake_agent=True, fake_judge=False):
    """<tmp>/ws: symlinks to the real LINKED_FILES, a real bin/ holding symlinks to every real
    bin/* file except qwen-agent (the fake agent when fake_agent) and judge-story (the fake
    judge when fake_judge), and generated/stories/. Returns the ws path (str)."""
    ws = os.path.join(str(tmp_path), "ws")
    os.makedirs(os.path.join(ws, "bin"))
    os.makedirs(os.path.join(ws, "generated", "stories"))
    for name in LINKED_FILES:
        os.symlink(os.path.join(WS, name), os.path.join(ws, name))
    for name in sorted(os.listdir(os.path.join(WS, "bin"))):
        if (name == "qwen-agent" and fake_agent) or (name == "judge-story" and fake_judge):
            continue
        os.symlink(os.path.join(WS, "bin", name), os.path.join(ws, "bin", name))
    if fake_agent:
        _write_executable(os.path.join(ws, "bin", "qwen-agent"), FAKE_AGENT_SOURCE)
    if fake_judge:
        _write_executable(os.path.join(ws, "bin", "judge-story"), FAKE_JUDGE_SOURCE)
    return ws


def _write_executable(path, source):
    with open(path, "w", encoding="utf-8") as f:
        f.write(source)
    os.chmod(path, 0o755)


def script_agent(monkeypatch, tmp_path, plan=(), panel=None, critic=()):
    """Write the fake agent's script ({"plan": [...], "panel": {"<k>"|"*": [...]}, "critic":
    [...]}) and point FAKE_AGENT_SCRIPT / FAKE_AGENT_LOG at it. Returns the log path."""
    script = os.path.join(str(tmp_path), "agent_script.json")
    log = os.path.join(str(tmp_path), "agent_log.jsonl")
    with open(script, "w", encoding="utf-8") as f:
        json.dump({"plan": list(plan), "panel": dict(panel or {}), "critic": list(critic)}, f)
    if os.path.exists(log):
        os.remove(log)
    monkeypatch.setenv("FAKE_AGENT_SCRIPT", script)
    monkeypatch.setenv("FAKE_AGENT_LOG", log)
    return log


def agent_log(path):
    """The fake agent's call records, in call order ([] when it was never called)."""
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def answer(obj):
    """A fake-agent reply item whose answer is obj (a dict is JSON-encoded)."""
    return {"answer": obj if isinstance(obj, str) else json.dumps(obj)}


def make_ctx(se, ws, **overrides):
    """A story_engine.StoryContext for ws with test defaults (chained, 3 panels, uncast, empty
    catalog, auto LoRA on); keyword arguments replace fields."""
    story_id = overrides.pop("story_id", "s1")
    fields = dict(ws=ws, story_id=story_id,
                  story_dir=os.path.join(ws, "generated", "stories", story_id), mode="chained",
                  panels=3, seconds="6",
                  narrative="A courier carries a sealed letter across a rainy harbour town.",
                  goal=None, members=[], seed_image=None, seed_agent_image=None,
                  story_model=None, context_window=None, video_model=VIDEO_MODEL,
                  auto_lora=True, catalog={"schema_version": 1, "entries": []}, pinned=[],
                  stills_pinned=[], judge=False)
    fields.update(overrides)
    os.makedirs(fields["story_dir"], exist_ok=True)
    return se.StoryContext(**fields)


FAKE_JUDGE_SOURCE = r'''#!/usr/bin/env python3
"""Fake bin/judge-story --patches for the story engine tests (spec 5.2)."""
import json
import os
import sys

argv = sys.argv[1:]
with open(os.environ["FAKE_JUDGE_LOG"], "a", encoding="utf-8") as f:
    f.write(json.dumps({"argv": argv}) + "\n")
reply = json.loads(os.environ["FAKE_JUDGE_REPLY"])
if "exit" in reply:
    print("judge-story failed")
    sys.exit(reply["exit"])
story_md = argv[argv.index("--story-md") + 1]
with open(os.path.join(os.path.dirname(story_md), "judgment.patches.json"), "w",
          encoding="utf-8") as f:
    json.dump({"scores": reply["scores"], "verdict": reply["verdict"],
               "patches": reply["patches"]}, f)
print("Scores: ...")
sys.exit(0)
'''


# --- plan builders (spec 5.2) ---------------------------------------------------------------

COURIER = "a young man with short brown hair and a lean build wearing a yellow rain jacket and grey trousers"
MONK = "an old man with a shaved head and a calm face wearing a saffron robe and wooden sandals"
HARBOUR = ("The setting is a rainy harbour town in modern Japan, wet cobblestones underfoot, "
           "fishing boats behind, under grey afternoon light.")
TEMPLE = ("The setting is a hilltop temple gate in modern Japan, worn stone steps underfoot, "
          "pine trees behind, under warm sunset light.")
ACTIONS = (
    "pedals a bicycle along the wet harbour road past the moored fishing boats",
    "swerves around a stack of fishing crates on the slippery quay",
    "rides hard up the narrow lane between the shuttered shops",
    "brakes at the foot of the temple steps and climbs off the bicycle",
    "climbs the worn stone steps two at a time toward the gate",
    "holds out the sealed letter at the temple gate with both hands",
    "turns back toward the harbour as the rain finally stops",
    "leans the bicycle against a lamp post beside the gate",
)


def arcs(n):
    """A valid arc sequence for n beats (RS10 P5/P6)."""
    if n == 1:
        return ["climax"]
    if n == 2:
        return ["introduction", "resolution"]
    return ["introduction"] + ["rising"] * (n - 3) + ["climax", "resolution"]


def plan_json(mode, n, cast=None, **overrides):
    """A valid plan-writer reply (Section 2.2 keys) for n beats: cast c1 "the courier" (and c2
    "the old monk", never on screen), locations l1 (harbour) and l2 (temple), every beat at l1
    with cast ["c1"]. cast replaces the cast list (e.g. fixed library characters); every
    keyword replaces a top-level key."""
    phrase = (cast[0]["phrase"] if cast else "the courier")
    plan = {
        "title": "The Sealed Letter",
        "logline": "A courier carries a sealed letter through a rainy harbour town and "
                   "delivers it at the temple gate.",
        "cast": cast if cast is not None else [
            {"id": "c1", "phrase": "the courier", "descriptor": COURIER},
            {"id": "c2", "phrase": "the old monk", "descriptor": MONK}],
        "locations": [{"id": "l1", "setting": HARBOUR}, {"id": "l2", "setting": TEMPLE}],
        "props": [{"id": "p1", "name": "the sealed letter"}],
        "beats": [{"index": k, "arc": arc, "action": phrase + " " + ACTIONS[(k - 1) % len(ACTIONS)],
                   "shot": "medium shot" if k % 2 else "wide shot",
                   "camera": "static" if k % 2 else "tracking", "location": "l1", "cast": ["c1"]}
                  for k, arc in enumerate(arcs(n), start=1)],
        "loras": {"global": [], "per_beat": {}, "stills": []},
    }
    plan.update(overrides)
    return plan
