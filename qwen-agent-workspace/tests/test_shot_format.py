"""Tests for the shot prompt format (docs/superpowers/specs/2026-10-28-shot-prompt-format-
design.md, Section 4.1: SFT1-SFT25, and the plan's Review Focus 1-5): the planner gets one camera
move per beat with static capped at one beat in three (P18), the writer writes the panel's one
camera sentence (N20), a speaking panel ends with the speaker in frame and nobody else acting
(N21), speaking verbs are cut (N7), writers see a format reference they must not copy (N22), the
manifest composes a speech movie's prompts in a fixed order with the audio sentence last, and the
user is told when the narrative's exit after its last line is left out (P19).

Run from the workspace root: python3 -m pytest -q -p no:cacheprovider tests/test_shot_format.py
Stdlib plus pytest. No test renders, reads the real HOME, or contacts a model server, a daemon or
the Anthropic API: every model call goes to the fake bin/qwen-agent of a temp workspace
(story_engine_testutil.make_ws), every ctx lives under tmp_path, and every test runs under the
autouse story_env fixture (a temporary HOME, character library and LoRA catalog).
"""

import base64
import copy
import hashlib
import importlib.machinery
import json
import os
import re
import subprocess
import sys

import pytest

WS = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
sys.path.insert(0, WS)
sys.path.insert(0, os.path.join(WS, "tests"))

import story_engine_testutil as seu  # noqa: E402


def _load(name, rel):
    return importlib.machinery.SourceFileLoader(name, os.path.join(WS, rel)).load_module()


lib = _load("character_lib_for_shot_format", "character_lib.py")
se = _load("story_engine_for_shot_format", "story_engine.py")
story_manifest = _load("ltx_story_manifest_for_shot_format",
                       os.path.join("bin", "ltx-story-manifest"))
ltx_movie = _load("ltx_movie_for_shot_format", os.path.join("bin", "ltx-movie"))


@pytest.fixture(autouse=True)
def story_env(monkeypatch, tmp_path):
    return seu.set_story_env(monkeypatch, tmp_path)


@pytest.fixture
def ws(tmp_path):
    return seu.make_ws(tmp_path)


# --- Copied verbatim from tests/test_speaker_attribution.py (spec 4.1) -------------------------

KYRA = "the woman in grey"
RONIN = "the ronin"
CAST2 = [{"id": "c1", "phrase": "x", "descriptor": "a woman"},
         {"id": "c2", "phrase": "y", "descriptor": "a man"}]
LINES_NARRATIVE = ('At dusk Kyra climbs the stone steps of a mountain temple, and the ronin walks '
                   'one step behind her. Near the top Kyra turns and says, "We reach the gate '
                   'before dark." They pass under the gate together, and Kyra says, "Stay close '
                   'to me."')


def _members(story_env):
    """kyra (c1, "the woman in grey") and ronin (c2, "the ronin") from the test library."""
    seu.kyra(story_env["lib"])
    seu.ronin(story_env["lib"])
    return lib.resolve_cast([(None, "kyra"), (None, "ronin")])


def _raw(mode, n, casts, speakers=None):
    """A plan reply for n beats with CAST2 (normalisation replaces both entries with the
    members): beat k gets cast casts[k - 1] and, when speakers is given, speaker
    speakers[k - 1]."""
    raw = seu.plan_json(mode, n, cast=copy.deepcopy(CAST2))
    for k, beat in enumerate(raw["beats"], start=1):
        beat["cast"] = list(casts[k - 1])
        if speakers is not None:
            beat["speaker"] = speakers[k - 1]
    return raw


def _read_json(story_dir, name):
    with open(os.path.join(story_dir, name), encoding="utf-8") as f:
        return json.load(f)


# --- Copied verbatim from tests/test_dialogue.py (spec 4.1: the manifest tests) ----------------

# A valid 1x1 PNG: bin/ltx-story-manifest only checks that each panel still opens.
PNG_1X1 = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA"
                           "60e6kgAAAABJRU5ErkJggg==")
CAST_PLAN = {"schema": "ltx-movie.plan.v1", "cast": [
    {"id": "c1", "phrase": "the courier", "descriptor": seu.COURIER, "cast_name": None},
    {"id": "c2", "phrase": "the old monk", "descriptor": seu.MONK, "cast_name": None}],
    "beats": [{"cast": ["c1"]}, {"cast": ["c2"]}]}


def _manifest_ws(tmp_path, monkeypatch, story_id, text, plan=None, images=1):
    """A workspace for bin/ltx-story-manifest (its module WS patched), with character_lib.py and
    lora_catalog.py symlinked in, the story.md, `images` panel stills, and plan (a dict, or the
    raw file text) as generated/stories/<story_id>/plan.json when given."""
    ws = tmp_path / "mws"
    if not ws.exists():
        ws.mkdir()
        for name in ("character_lib.py", "lora_catalog.py"):
            os.symlink(os.path.join(WS, name), str(ws / name))
    monkeypatch.setattr(story_manifest, "WS", str(ws))
    story_md = tmp_path / ("%s.md" % story_id)
    story_md.write_text(text, encoding="utf-8")
    paths = []
    for k in range(1, images + 1):
        path = tmp_path / ("%s_%02d.png" % (story_id, k))
        path.write_bytes(PNG_1X1)
        paths.append(str(path))
    if plan is not None:
        story_dir = ws / "generated" / "stories" / story_id
        story_dir.mkdir(parents=True, exist_ok=True)
        (story_dir / "plan.json").write_text(plan if isinstance(plan, str) else json.dumps(plan),
                                             encoding="utf-8")
    return str(story_md), paths, str(ws)


def _manifest_argv(story_id, story_md, images, mode="chain", panels=2, frames=145, extra=()):
    argv = ["--story-id", story_id, "--prompts-md", story_md]
    if mode == "chain":
        argv += ["--chain", "--image", images[0]]
    elif mode == "shots":
        argv += ["--shots"]
        for image in images:
            argv += ["--image", image]
    else:
        argv += ["--no-images"]
    return argv + ["--fps", "24", "--target-seconds", repr(frames * panels / 24.0),
                   "--min-frames", str(frames), "--max-frames", str(frames), "--force"] + list(extra)


def _read_manifest(ws, story_id):
    with open(os.path.join(ws, "generated", "stories", story_id, "manifest.json"),
              encoding="utf-8") as f:
        return json.load(f)


# --- Extra helpers (spec 4.1) ----------------------------------------------------------------

REF_PHRASE = "the old fishmonger"
REF_PARTS = (
    {"shot": "The shot is a wide shot.",
     "motion": ("The old fishmonger drags a tall stack of empty herring crates across the wet "
                "concrete of the market hall toward the half-open shutter at real-time speed, her "
                "heavy steps splashing through shallow puddles that hold the first glow from the "
                "harbour doors. The camera tracks alongside her from the left — as the move "
                "completes, she reaches the shutter at frame centre, the long rows of bare zinc "
                "counters stretching away behind her."),
     "speaker": None, "line": ""},
    {"shot": "The shot is a medium shot.",
     "motion": ("The old fishmonger looks up from the empty ice trays to the camera, drying her "
                "knuckles on a folded cloth at the zinc counter at real-time speed. The old "
                "fishmonger lets the folded cloth drop onto the counter, her shoulders sinking. "
                "The camera pushes in — as the move completes, her face fills the frame from "
                "chin to brow, the bare counters soft behind her. The old fishmonger faces the "
                "camera."),
     "speaker": "the old fishmonger", "line": "Forty years of mornings. Not one more."},
    {"shot": "The shot is a close-up.",
     "motion": ("The old fishmonger presses her forehead against the cold ribs of the half-closed "
                "steel shutter at real-time speed, both palms flat on the metal, her breath "
                "fogging the ribbed steel as a thin trickle of meltwater runs past her knuckles "
                "and drips onto the wet concrete at her feet. The camera stays static, holding her "
                "face, her knuckles and the ribbed steel tight in the frame as her eyelids drop "
                "shut and the shutter stops trembling."),
     "speaker": None, "line": ""},
)
# The narrative of the recorded hockey runs ($S/hockey/narrative.txt, written out; it equals the
# narrative of tests/fixtures/writer_pacing/hockey-2x145-f/plan.json).
HOCKEY_NARRATIVE = (
    'A hockey player in a reddish-orange and white uniform with "FuboTV" in a big logo on the '
    'front stands in a hockey rink with "FuboTV" on the sides of the rink and on digital banners '
    'on the bleachers, with cheering crowds in the stands. He skates forward towards the camera '
    'and says "Getting the best deal on hockey isn\'t a hat trick..." then stops short, kicking '
    'up ice mist into the air, then says "It\'s just FuboTV." then skates away.')
HOCKEY_FIX = os.path.join(WS, "tests", "fixtures", "writer_pacing", "hockey-2x145-f")


def ref_shots():
    """The three "Shot N" texts of se.FORMAT_REFERENCE: each line's text after its "): "."""
    return [line.split("): ", 1)[1] for line in se.FORMAT_REFERENCE.split("\n")
            if line.startswith("Shot ")]


def _hockey(ws, **kw):
    """(ctx, plan, parts) of the recorded hockey-2x145-f run: chained, 2 panels of 145 frames,
    --speech-only, its plan.json and its parts.json panels without their "index" key."""
    plan = _read_json(HOCKEY_FIX, "plan.json")
    parts = [dict((key, value) for key, value in p.items() if key != "index")
             for p in _read_json(HOCKEY_FIX, "parts.json")["panels"]]
    fields = dict(mode="chained", panels=2, narration="speech", clip_seconds=145 / 24.0,
                  narrative=plan["narrative"], goal=plan["goal"])
    fields.update(kw)
    return seu.make_ctx(se, ws, **fields), plan, parts


def _plan_prompt(ws, **kw):
    """The plan prompt of make_ctx(**kw), with no catalog and no pins."""
    return se.build_plan_prompt(seu.make_ctx(se, ws, **kw), [], [])


# --- SFT1 (Task 1 part): the planner constants (SF1-SF5) --------------------------------------

CAMERA_SENTENCES = (
    ("slow push-in", "The camera pushes in."),
    ("slow pull-back", "The camera pulls back."),
    ("tracking", "The camera tracks alongside the movement."),
    ("handheld", "The camera is handheld, with slight natural movement."),
    ("slow pan left", "The camera pans left."),
    ("slow pan right", "The camera pans right."),
    ("slow tilt up", "The camera tilts up."),
    ("slow tilt down", "The camera tilts down."),
    ("static", "The camera stays static."),
)
CAMERA_RULE = (" Give every beat one camera move from this list, and use static only for a "
               "deliberate hold: at most one beat in three may be static, so at most "
               "@@MAX_STATIC@@ in this movie.")
CAMERA_SPEAKING_SENTENCE = (" On a beat with a speaker, prefer slow push-in, slow pull-back, "
                            "tracking or handheld, and never use a pan or a tilt, which sweeps "
                            "the speaker's face out of the frame.")
SPEAKING_BEAT_SENTENCE = (" Write a speaking beat's action as what the speaker physically does, "
                          "never as speaking, and end it with the speaker still in frame: nobody "
                          "else acts after the line, and when the narrative has the speaker "
                          "leave, or another character act, after a line, give that a later beat "
                          "with no speaker, or leave it out when no later beat is left.")
SPEAKER_RULE = (" speaker is the id of the one character who says something aloud on screen "
                "during the beat, or an empty string when nobody speaks; give a speaker only where "
                "a spoken line moves the story. A beat with a speaker shows only that character "
                "(its cast is just their id), facing the camera, in a medium shot, medium close-up "
                "or close-up; the speaker may move during the beat, as long as their face stays in "
                "frame and lit while they speak." + SPEAKING_BEAT_SENTENCE)
SPEAKER_RULE_KEEP_CAST = (
    " speaker is the id of the one character who says something aloud on screen during the "
    "beat, or an empty string when nobody speaks; give a speaker only where a spoken line moves "
    "the story. A beat with a speaker shows that character facing the camera, in a medium shot, "
    "medium close-up or close-up; its cast is the speaker's id plus the id of every already-cast "
    "character who is still in frame and stays silent, and no character of your own. The speaker "
    "may move during the beat, as long as their face stays in frame and lit while they speak."
    + SPEAKING_BEAT_SENTENCE)
P18_NOTE = ("beat %d: P18 static camera: camera 'static' changed to 'slow push-in': at most %d "
            "of the %d beats may be static, and the latest static beats are kept as the "
            "deliberate holds")
SPEAKING_CAMERAS = ("slow push-in", "slow pull-back", "tracking", "handheld", "static")
STILL_CAMERA_MOVES = ("static", "still", "hold", "holds", "locked-off", "push in", "pushes in",
                      "push-in", "pull back", "pulls back", "pull-back", "track", "tracks",
                      "tracking", "follow", "follows", "handheld")
RECHECK_IDS_3970E96 = ("N1", "N2", "N3", "N4", "N7", "N8", "N9", "N10", "N11", "N12", "N14", "N15",
                       "N16", "N17", "N18", "T1", "T2", "T3", "Q1", "N19")
PLAN_FREE_IDS_3970E96 = ("N1", "N7", "N8", "N9", "N10", "N11", "N15")


def test_sft1a_planner_constants():
    assert se.CAMERA_SENTENCES == CAMERA_SENTENCES
    assert se.CAMERA_KEYS == tuple(key for key, _sentence in CAMERA_SENTENCES)
    assert [se.max_static(n) for n in range(1, 8)] == [1, 1, 1, 2, 2, 2, 3]
    assert se.CAMERA_RULE == CAMERA_RULE
    assert se.CAMERA_SPEAKING_SENTENCE == CAMERA_SPEAKING_SENTENCE
    assert se.SPEAKING_BEAT_SENTENCE == SPEAKING_BEAT_SENTENCE
    assert se.SPEAKER_RULE == SPEAKER_RULE
    assert se.SPEAKER_RULE_KEEP_CAST == SPEAKER_RULE_KEEP_CAST
    assert se.SPEAKING_CAMERAS == SPEAKING_CAMERAS
    assert se.STILL_CAMERA_MOVES == STILL_CAMERA_MOVES
    assert se.STILL_CAMERA_MOVES[-1] == "handheld"
    assert se.P18_NOTE == P18_NOTE
    assert se.RECHECK_IDS == RECHECK_IDS_3970E96
    assert se.PLAN_FREE_IDS == PLAN_FREE_IDS_3970E96
    for text in ([sentence for _key, sentence in se.CAMERA_SENTENCES]
                 + [se.CAMERA_RULE, se.CAMERA_SPEAKING_SENTENCE, se.SPEAKING_BEAT_SENTENCE,
                    se.SPEAKER_RULE, se.SPEAKER_RULE_KEEP_CAST, se.P18_NOTE]):
        assert "slowly" not in text.lower(), text


def test_sft1_the_pipeline_files_compile_under_both_pythons():
    script = ("import sys\n"
              "for path in sys.argv[1:]:\n"
              "    with open(path, encoding='utf-8') as f:\n"
              "        compile(f.read(), path, 'exec')\n"
              "print('compiled %d' % (len(sys.argv) - 1))\n")
    files = [os.path.join(WS, name) for name in
             ("story_engine.py", "character_lib.py", os.path.join("bin", "ltx-story-manifest"))]
    pythons = [sys.executable] + (["/usr/bin/python3"] if os.path.exists("/usr/bin/python3")
                                  else [])
    for python in pythons:
        proc = subprocess.run([python, "-c", script] + files, capture_output=True, text=True)
        assert (proc.returncode, proc.stdout) == (0, "compiled 3\n"), (python, proc.stderr)


# --- SFT2: the plan prompt camera rule (SF2, SK4) ------------------------------------------------

CAMERA_LIST = ("camera is exactly one of: slow push-in, slow pull-back, tracking, handheld, slow "
               "pan left, slow pan right, slow tilt up, slow tilt down, static.")


def test_sft2_the_plan_prompt(ws, story_env):
    for panels, most in zip(range(1, 8), (1, 1, 1, 2, 2, 2, 3)):
        rule = se.CAMERA_RULE.replace("@@MAX_STATIC@@", str(most))
        prompt = _plan_prompt(ws, mode="shots", panels=panels, narration="speech")
        assert (CAMERA_LIST + rule + se.CAMERA_SPEAKING_SENTENCE + " location is") in prompt, panels
        silent = _plan_prompt(ws, mode="shots", panels=panels, narration=False)
        assert (CAMERA_LIST + rule + " location is") in silent, panels
        assert se.CAMERA_SPEAKING_SENTENCE not in silent, panels
    members = _members(story_env)
    for mode in ("chained", "shots", "no_stills"):
        for narration in (True, "speech", False):
            for cast in ([], members):
                where = (mode, narration, bool(cast))
                prompt = _plan_prompt(ws, mode=mode, narration=narration, members=cast)
                assert "the camera may stay static" not in prompt, where
                assert "@@" not in prompt, where
    assert se.SPEAKER_RULE_KEEP_CAST in _plan_prompt(ws, mode="chained", members=members)
    assert se.SPEAKER_RULE in _plan_prompt(ws, mode="shots", members=members)


# --- SFT3 (Task 1 part): the P14 speaking coercion (SF4, SK4) -----------------------------------

def test_sft3a_a_speaking_pan_or_tilt_becomes_a_slow_push_in(ws, story_env):
    ctx = seu.make_ctx(se, ws, mode="shots", panels=1, members=_members(story_env),
                       narration="speech")
    for camera in ("slow pan left", "slow pan right", "slow tilt up", "slow tilt down", "",
                   "handheld", "static", "tracking", "slow pull-back", "slow push-in"):
        raw = _raw("shots", 1, [["c1"]], ["c1"])
        raw["beats"][0]["camera"] = camera
        plan, _shape = se.normalize_plan(ctx, raw)
        notes = [n for n in plan["speech_notes"] if " camera " in n]
        if camera in se.SPEAKING_CAMERAS:
            assert (plan["beats"][0]["camera"], notes) == (camera, []), camera
        else:
            assert plan["beats"][0]["camera"] == "slow push-in", camera
            assert notes == ["beat 1: P14 speaking beat: camera %s changed to 'slow push-in' so "
                             "the speaker's face stays readable" % se._q(camera)], camera


# --- SFT4: P18, the static cap (SF5, SK4) ------------------------------------------------------

def test_sft4_the_static_cap(ws):
    names = {"s": "static", "t": "tracking", "p": "slow push-in"}
    for before, after in (("sss", "pps"), ("stss", "ptss"), ("ssssss", "ppppss"),
                          ("sstssss", "pptpsss")):
        n = len(before)
        ctx = seu.make_ctx(se, ws, mode="shots", panels=n)
        plan = {"beats": [{"camera": names[c]} for c in before]}
        notes = se.cap_static_cameras(ctx, plan)
        assert [beat["camera"] for beat in plan["beats"]] == [names[c] for c in after], before
        changed = [k for k, (a, b) in enumerate(zip(before, after), start=1) if a != b]
        assert notes == [se.P18_NOTE % (k, se.max_static(n), n) for k in changed], before
        violation = se.parse_violation(notes[0])
        assert (violation["id"], violation["name"], violation["scope"], violation["index"]) == (
            "P18", "static camera", "beat", changed[0]), before
    ctx = seu.make_ctx(se, ws, mode="shots", panels=2)
    plan = {"beats": [{"camera": "static"}, {"camera": "tracking"}]}
    assert se.cap_static_cameras(ctx, plan) == []
    assert [beat["camera"] for beat in plan["beats"]] == ["static", "tracking"]


def test_sft4_e2e_the_cap_runs_once_after_the_plan(ws, tmp_path, monkeypatch):
    log = seu.script_agent(monkeypatch, tmp_path, plan=[seu.answer(seu.plan_json("shots", 3))],
                           panel=dict((str(k), [seu.answer(seu.panel_json("shots", k))])
                                      for k in (1, 2, 3)))
    ctx = seu.make_ctx(se, ws, mode="shots", panels=3, story_id="sf4")
    rc, advisories = se.run(ctx)
    note = se.P18_NOTE % (1, 1, 3)
    assert rc == 0
    assert [r["stage"] for r in seu.agent_log(log)] == ["plan", "panel", "panel", "panel"]
    plan = _read_json(ctx.story_dir, "plan.json")
    assert [beat["camera"] for beat in plan["beats"]] == ["slow push-in", "tracking", "static"]
    assert plan["speech_notes"] == [note]
    checks = _read_json(ctx.story_dir, "story_checks.json")
    assert note in [a["message"] for a in checks["advisory"]]
    assert note in advisories
    with open(os.path.join(ctx.story_dir, "story.md"), encoding="utf-8") as f:
        motions = [line for line in f.read().splitlines() if line.startswith("Motion: ")]
    assert motions[0].endswith(". The camera pushes in.")


# --- SFT22: no server and no real HOME (spec 4.1 conventions) -----------------------------------

def test_sft22_no_server_and_no_real_home(story_env, tmp_path):
    assert os.path.expanduser("~") == story_env["home"]
    assert story_env["home"].startswith(str(tmp_path))
    assert os.environ["QWEN_AGENT_DAEMON_URL"].startswith("http://127.0.0.1:")
    assert "ANTHROPIC_API_KEY" not in os.environ
