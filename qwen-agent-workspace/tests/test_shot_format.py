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
                          "with no speaker, adding that beat when the beat count allows it, and "
                          "leave it out only when it does not.")
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


# --- SFT1 (Task 2 part): the writer constants (SF6-SF8) ----------------------------------------

WORD_RANGES = {"chained": {"image1": (120, 170), "motion1": (55, 105), "motion": (55, 105)},
               "no_stills": {"prompt": (150, 220)},
               "shots": {"image": (80, 170), "motion": (55, 105)}}
PACING_SENTENCE = se.PACING_SENTENCE
KEY_LINES = {
    "chained_motion1": (
        "motion: W1 to W2 words: one or two plain sentences of what the characters physically do "
        "during these @@SECONDS@@ seconds, then the camera sentence. Name each character only by "
        "their referring phrase, word for word. Describe ONE continuous physical motion, not a "
        "sequence of separate steps: @@SECONDS@@ seconds is enough for a single gesture, a few "
        "footsteps or the start of a movement." + PACING_SENTENCE),
    "chained_motion": (
        "motion: W1 to W2 words: one or two plain sentences of what the characters physically do "
        "during these @@SECONDS@@ seconds, continuing from where the previous panel left them, "
        "then the camera sentence. Name each character only by their referring phrase, word for "
        "word. Describe ONE continuous physical motion, not a sequence of separate steps: "
        "@@SECONDS@@ seconds is enough for a single gesture, a few footsteps or the start of a "
        "movement." + PACING_SENTENCE + " Do not describe appearance, clothing, setting, "
        "lighting, colour or style -- all of that is already on screen."),
    "shots_motion": (
        "motion: W1 to W2 words: ONE sentence naming ONE character by their referring phrase and "
        "the ONE physical action they perform during these @@SECONDS@@ seconds, told in concrete "
        "detail (where in the frame they start, how they move and where they end), then the "
        "camera sentence. Never chain actions with then, while, meanwhile, simultaneously, "
        "afterwards, followed by or a comma before and, and never use a semicolon."),
}
CAMERA_WRITER_SENTENCE = (" End this field with exactly one camera sentence, for this panel's "
                          "planned camera, in which the camera @@CAMERA_MOVE@@: begin it with "
                          "'The camera' and write it like @@CAMERA_FORM@@, with your own words in "
                          "place of the part in angle brackets. Write no other camera direction "
                          "anywhere in this field.")
CAMERA_WRITER_FORMS = {
    "slow push-in": ("pushes in", "'The camera pushes in — as the move completes, <what then "
                                  "fills the frame>.'"),
    "slow pull-back": ("pulls back", "'The camera pulls back — as the move completes, <what the "
                                     "wider frame then shows>.'"),
    "tracking": ("tracks the movement", "'The camera tracks <whom it follows> — as the move "
                                        "completes, <where the frame ends>.'"),
    "handheld": ("moves handheld", "'The camera follows with handheld movement — as the move "
                                   "completes, <where the frame ends>.'"),
    "slow pan left": ("pans left", "'The camera pans left — as the move completes, <what the "
                                   "frame ends on>.'"),
    "slow pan right": ("pans right", "'The camera pans right — as the move completes, <what the "
                                     "frame ends on>.'"),
    "slow tilt up": ("tilts up", "'The camera tilts up — as the move completes, <what the frame "
                                 "ends on>.'"),
    "slow tilt down": ("tilts down", "'The camera tilts down — as the move completes, <what the "
                                     "frame ends on>.'"),
    "static": ("stays static", "'The camera stays static, holding <what stays in the frame>.'"),
}
# Shot prompt format spec SF7, D7: a shots speaking panel's reaction after the line, and the
# speaker staying in frame (every mode).
SPEAKING_REACTION_SENTENCE = (" The pipeline puts the spoken line right after your first "
                              "sentence. Between that sentence and the camera sentence you may "
                              "write one short sentence, beginning with @@SPEAKER@@, of how they "
                              "react once the line is said, such as a nod, a breath or a glance "
                              "down; nobody else acts in it.")
SPEAKING_NO_REACTION_SENTENCE = (" The pipeline puts the spoken line right after your first "
                                 "sentence, so write no other action sentence.")
SPEAKING_STAY_SENTENCE = (" In this whole panel @@SPEAKER@@ never leaves, turns away or moves "
                          "out of the frame, even when the beat says so.")
SPEAKING_CHAINED_MOTION_SENTENCE = (
    " In this panel @@SPEAKER@@ speaks the dialogue, and the pipeline inserts it right after the "
    "first sentence about what @@SPEAKER@@ does. Write that first sentence as everything "
    "@@SPEAKER@@ does before the dialogue, ending with them near the camera, face toward it (if "
    "the dialogue comes before they do anything, it is how they turn or step toward the camera; "
    "never write only that they face it); after it you may write one short second sentence of "
    "how @@SPEAKER@@ reacts once the line is said, such as a nod, a breath or a glance down, in "
    "which nobody else acts. Begin each of these sentences with @@SPEAKER@@, word for word, and "
    "write nothing about anyone else before the first one. Never put an action from before the "
    "dialogue and one from after it in the same sentence, and do not write the spoken words or a "
    "speaking verb; the pipeline adds them.")
FORMAT_REFERENCE_SHA256 = "d2fe46c687bdaf8ebc75235bdf530d5d751aa1fa62f9bf393bf9855bef7681dd"


def test_sft1b_writer_constants():
    assert se.WORD_RANGES == WORD_RANGES
    for key, line in KEY_LINES.items():
        assert se.KEY_LINE_TEMPLATES[key] == line, key
    for key in ("no_stills_prompt", "no_stills_prompt_speaking"):
        line = se.KEY_LINE_TEMPLATES[key]
        assert "you may also state a camera movement" not in line, key
        assert ("and states the camera viewpoint and the lighting and colour. Name each character "
                "only by their referring phrase.") in line, key
    assert se.CAMERA_WRITER_SENTENCE == CAMERA_WRITER_SENTENCE
    assert se.CAMERA_WRITER_FORMS == CAMERA_WRITER_FORMS
    assert set(se.CAMERA_WRITER_FORMS) == set(se.CAMERA_KEYS)
    assert se.SPEAKING_REACTION_SENTENCE == SPEAKING_REACTION_SENTENCE
    assert se.SPEAKING_NO_REACTION_SENTENCE == SPEAKING_NO_REACTION_SENTENCE
    assert se.SPEAKING_STAY_SENTENCE == SPEAKING_STAY_SENTENCE
    assert se.SPEAKING_CHAINED_MOTION_SENTENCE == SPEAKING_CHAINED_MOTION_SENTENCE
    reference = se.FORMAT_REFERENCE
    assert hashlib.sha256(reference.encode("utf-8")).hexdigest() == FORMAT_REFERENCE_SHA256
    assert (len(reference), len(reference.split())) == (2406, 421)
    assert "@@" not in reference
    for text in ([reference, se.CAMERA_WRITER_SENTENCE, se.SPEAKING_REACTION_SENTENCE,
                  se.SPEAKING_NO_REACTION_SENTENCE, se.SPEAKING_STAY_SENTENCE,
                  se.SPEAKING_CHAINED_MOTION_SENTENCE]
                 + [se.KEY_LINE_TEMPLATES[key] for key in KEY_LINES]
                 + [form for _move, form in se.CAMERA_WRITER_FORMS.values()]):
        assert "slowly" not in text.lower(), text


# --- SFT3 (Task 2 part): the chained paste-time speaking camera (SF4, SF6) --------------------

def test_sft3b_a_chained_speaking_pan_pastes_a_push_in(ws, story_env):
    ctx = seu.make_ctx(se, ws, mode="chained", panels=2, members=_members(story_env),
                       narration="speech")
    raw = _raw("chained", 2, [["c1"], ["c1"]], ["", "c1"])
    raw["beats"][1]["camera"] = "slow pan right"
    plan, _shape = se.normalize_plan(ctx, raw)
    assert plan["beats"][1]["camera"] == "slow pan right"
    assert se.panel_camera(ctx, plan, 2) == "slow push-in"
    assert se.panel_camera(ctx, plan, 1) == plan["beats"][0]["camera"]
    assert se.pasted_pieces(ctx, plan, 2)["motion"] == ["The woman in grey faces the camera.",
                                                        "The camera pushes in."]


# --- SFT5: the writer prompt (SF7, SF8, SK9) ---------------------------------------------------

def _sft5(ws, mode="shots", narration="speech", cameras=("tracking", "slow push-in", "static"),
          speaker_beat=2, **ctx_kw):
    """(ctx, plan, parts) of a 3-panel movie: beat k's camera cameras[k - 1], the courier (c1)
    speaking in beat speaker_beat (none when 0), empty writer parts."""
    ctx = seu.make_ctx(se, ws, mode=mode, panels=3, narration=narration, **ctx_kw)
    raw = seu.plan_json(mode, 3)
    for beat, camera in zip(raw["beats"], cameras):
        beat["camera"] = camera
    if speaker_beat:
        raw["beats"][speaker_beat - 1]["speaker"] = "c1"
    plan, _shape = se.normalize_plan(ctx, raw)
    return ctx, plan, [se.empty_parts(mode, k, plan, ctx) for k in (1, 2, 3)]


def _key_line(prompt, key):
    return [line for line in prompt.split("\n") if line.startswith(key + ": ")][0]


def _writer_sentence(camera):
    move, form = se.CAMERA_WRITER_FORMS[camera]
    return (se.CAMERA_WRITER_SENTENCE.replace("@@CAMERA_MOVE@@", move)
            .replace("@@CAMERA_FORM@@", form))


def test_sft5_the_writer_prompt(ws):
    ctx, plan, parts = _sft5(ws)
    first = se.build_panel_prompt(ctx, plan, parts, 1)
    assert _key_line(first, "motion").endswith(_writer_sentence("tracking"))
    second = se.build_panel_prompt(ctx, plan, parts, 2)
    speaking = (se.SPEAKING_ACTION_SENTENCE + se.SPEAKING_REACTION_SENTENCE
                + se.SPEAKING_STAY_SENTENCE).replace("@@SPEAKER@@", '"the courier"')
    assert speaking + _writer_sentence("slow push-in") in _key_line(second, "motion")
    for prompt in (first, second):
        assert prompt.count(se.FORMAT_REFERENCE) == 1
        assert (se.FORMAT_REFERENCE + "Write this panel as one JSON object") in prompt
        assert "@@" not in prompt
    ctx, plan, parts = _sft5(ws, clip_seconds=5.04)
    short = _key_line(se.build_panel_prompt(ctx, plan, parts, 2), "motion")
    no_reaction = (se.SPEAKING_ACTION_SENTENCE + se.SPEAKING_NO_REACTION_SENTENCE
                   + se.SPEAKING_STAY_SENTENCE).replace("@@SPEAKER@@", '"the courier"')
    assert no_reaction + _writer_sentence("slow push-in") in short
    assert "of how they react once the line is said" not in short
    ctx, plan, parts = _sft5(ws, mode="chained", cameras=("tracking", "static", "static"),
                             speaker_beat=0)
    for k in (1, 2):
        prompt = se.build_panel_prompt(ctx, plan, parts, k)
        assert prompt.count(se.FORMAT_REFERENCE) == 1, k
        assert "@@" not in prompt, k
    assert "in which the camera stays static" in _key_line(
        se.build_panel_prompt(ctx, plan, parts, 2), "motion")
    for mode, narration in (("no_stills", "speech"), ("no_stills", True), ("chained", False),
                            ("shots", False), ("no_stills", False)):
        ctx, plan, parts = _sft5(ws, mode=mode, narration=narration)
        for k in (1, 2, 3):
            prompt = se.build_panel_prompt(ctx, plan, parts, k)
            assert "FORMAT REFERENCE ONLY" not in prompt, (mode, narration, k)
            assert "@@" not in prompt, (mode, narration, k)
    ctx, plan, parts = _sft5(ws, cameras=("", "slow push-in", "static"))
    assert "End this field with exactly one camera sentence" not in _key_line(
        se.build_panel_prompt(ctx, plan, parts, 1), "motion")


# --- SFT6: the pasted camera is only a fallback (SF6, plan ruling PR1, SK5) ----------------------

SFT6_ACTION = "The courier steps onto the wet quay at real-time speed."
SFT6_CAMERA = "The camera pushes in — as the move completes, her face fills the frame."


def test_sft6_the_pasted_camera_is_only_a_fallback(ws):
    for mode in ("chained", "shots", "no_stills"):
        label = "Prompt" if mode == "no_stills" else "Motion"
        for speaks in (False, True):
            ctx = seu.make_ctx(se, ws, mode=mode, panels=2, narration="speech")
            raw = seu.plan_json(mode, 2)
            for beat in raw["beats"]:
                beat["camera"] = "slow push-in"
                beat["speaker"] = "c1" if speaks else ""
            plan, _shape = se.normalize_plan(ctx, raw)
            for k in (1, 2):
                where = (mode, speaks, k)
                assert se.panel_camera(ctx, plan, k) == "slow push-in", where
                reply = seu.panel_json(mode, k)
                if speaks:
                    reply["dialogue"] = "Go now."
                for writer in (SFT6_ACTION, SFT6_ACTION + " " + SFT6_CAMERA):
                    reply[label.lower()] = writer
                    parts = [se.empty_parts(mode, j, plan, ctx) for j in (1, 2)]
                    parts[k - 1] = se.parse_panel_reply(ctx, plan, k, json.dumps(reply))
                    field = dict(se.panel_fields(ctx, plan, parts, k))[label]
                    assert field.count("The camera") == 1, where
                    if writer == SFT6_ACTION:
                        assert field.endswith(" The camera pushes in."), where
                    else:
                        assert SFT6_CAMERA in field, where
                        assert "The camera pushes in." not in field, where


# --- SFT21: the prompt budget (SF8) ------------------------------------------------------------

def test_sft21_the_reference_adds_exactly_its_own_length(ws, monkeypatch):
    ctx, plan, parts = _sft5(ws)
    reference = se.FORMAT_REFERENCE
    full = se.build_panel_prompt(ctx, plan, parts, 2)
    monkeypatch.setattr(se, "FORMAT_REFERENCE", "")
    bare = se.build_panel_prompt(ctx, plan, parts, 2)
    assert len(full) - len(bare) == len(reference) == 2406
    assert len(full) < 9000


# --- SFT1 (Task 3 part): the check constants (SF9-SF12, SF14) ----------------------------------

REFERENCE_TERMS = ("fishmonger", "fishmongers", "herring", "herrings", "zinc", "ice trays",
                   "market hall", "fish market", "harbour doors", "meltwater",
                   "forty years of mornings")
REFERENCE_COPY_SEGMENTS = (
    "The old fishmonger drags a tall stack of empty herring crates across the wet concrete of "
    "the market hall toward the half-open shutter",
    "her heavy steps splashing through shallow puddles that hold the first glow from the "
    "harbour doors",
    "she reaches the shutter at frame centre, the long rows of bare zinc counters stretching "
    "away behind her",
    "The old fishmonger looks up from the empty ice trays to the camera, drying her knuckles on "
    "a folded cloth at the zinc counter",
    "The old fishmonger lets the folded cloth drop onto the counter, her shoulders sinking",
    "her face fills the frame from chin to brow, the bare counters soft behind her",
    "The old fishmonger presses her forehead against the cold ribs of the half-closed steel "
    "shutter",
    "both palms flat on the metal, her breath fogging the ribbed steel as a thin trickle of "
    "meltwater runs past her knuckles and drips onto the wet concrete at her feet",
    "holding her face, her knuckles and the ribbed steel tight in the frame as her eyelids drop "
    "shut and the shutter stops trembling",
    "Forty years of mornings. Not one more.",
)
REPAIR_NOTE = "panel %d: %s %s: %s: the pipeline removed %s"
GENERATION_CHECKS = ("N1", "N2", "N3", "N4", "N5", "N6", "N7", "N8", "N9", "N10", "N11", "N12",
                     "N14", "N15", "N16", "N17", "N18", "T1", "T2", "T3", "N20", "N21", "N22",
                     "Q1", "N19")


def test_sft1c_check_constants():
    assert se.REFERENCE_TERMS == REFERENCE_TERMS
    assert se.REFERENCE_COPY_SEGMENTS == REFERENCE_COPY_SEGMENTS
    assert se.REPAIR_NOTE == REPAIR_NOTE
    assert se.GENERATION_CHECKS == GENERATION_CHECKS
    assert se.GENERATION_CHECKS[16:20] == ("N18", "T1", "T2", "T3")
    assert se.GENERATION_CHECKS[-2:] == ("Q1", "N19")
    assert se.GENERATION_CHECKS[-1] == "N19"
    assert len(se.REFERENCE_SIX_GRAMS) == 138
    assert set(se.CAMERA_WRITER_FORMS) == set(se.CAMERA_KEYS) == set(se.CAMERA_MOVE_WORDS)
    for key, sentence in se.CAMERA_SENTENCES:
        form = re.sub(r"<[^<>]*>", "x", se.CAMERA_WRITER_FORMS[key][1].strip("'"))
        for text in (sentence, form):
            assert se._names_camera(text, key), (key, text)
            assert not se._mixed_camera(text), (key, text)
            assert se.camera_problem(lib, text, [], key) is None, (key, text)


# --- SFT7, Review Focus 5: N20 detection (SF9, SK5) --------------------------------------------

SFT7_ROWS = (
    ("The courier runs. The camera pushes in.", "slow push-in", None),
    ("The courier runs. The camera holds on him as he recedes. The camera stays static.", "static",
     "has 2 camera directions"),
    ("The courier runs while the camera tracks him. The camera pushes in.", "slow push-in",
     "has 2 camera directions"),
    ("The courier runs while the camera tracks him.", "",
     "puts the camera direction inside the action sentence"),
    ("The camera pushes in and stays static.", "slow push-in",
     "the camera sentence 'The camera pushes in and stays static.' has the camera both stay still "
     "and move"),
    ("The camera pans left.", "slow push-in",
     "the camera sentence 'The camera pans left.' does not move the camera the planned way"),
    ("The camera follows with handheld movement.", "handheld", None),
    ("The camera follows her.", "tracking", None),
    ("The camera holds steady on her.", "static", None),
    ("The courier faces the camera.", "static", None),
    ("The shot is a medium shot. The courier runs. The camera tracks alongside the movement.",
     "tracking", None),
)
HOCKEY_E2 = ("The FuboTV hockey player carves a sharp stop, spraying ice mist into the air, his "
             "face toward the lens, then pushes off and skates away from the camera. The camera "
             "holds on him as he recedes. The camera stays static.")


def test_sft7_n20_detection(ws):
    for text, key, start in SFT7_ROWS:
        detail = se.camera_problem(lib, text, ["the courier"], key)
        if start is None:
            assert detail is None, text
        else:
            assert detail is not None and detail.startswith(start), (text, detail)
    ctx, plan, parts = _hockey(ws, story_id="sf7")
    parts[1]["motion"] = HOCKEY_E2
    text = se.assemble(ctx, plan, parts)
    path = os.path.join(ctx.story_dir, "check.md")
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    hard, _advisory = se.panel_checks(ctx, plan, parts, text, path)
    assert ("panel 2: N20 camera direction: Motion: has 2 camera directions ('The camera holds on "
            "him as he recedes.'; 'The camera stays static.'); a panel has exactly one camera "
            "sentence; write one camera sentence in which the camera stays static") in hard


def test_review_focus_5_an_adverb_on_the_planned_move_is_one_valid_direction(ws):
    for camera, text in (("slow push-in", "The courier runs. The camera slowly pushes in on her."),
                         ("slow pan left",
                          "The courier runs. The camera gently pans left toward the harbour.")):
        ctx = seu.make_ctx(se, ws, mode="shots", panels=1)
        raw = seu.plan_json("shots", 1)
        raw["beats"][0]["camera"] = camera
        plan, _shape = se.normalize_plan(ctx, raw)
        assert se.camera_problem(lib, text, ["the courier"], camera) is None, text
        assert se.repair_action_text(ctx, plan, 1, text) == (text, []), text


# --- SFT8: the N20 and N7 repairs at parse time (SF11, SF13a, SK5, SK8) --------------------------

def test_sft8_the_parse_time_repairs(ws):
    ctx = seu.make_ctx(se, ws, mode="shots", panels=1)
    raw = seu.plan_json("shots", 1)
    raw["beats"][0]["camera"] = "slow push-in"
    plan, _shape = se.normalize_plan(ctx, raw)

    def note(check, name, removed):
        return se.REPAIR_NOTE % (1, check, name, "Motion", se._q(removed))

    rows = (
        ("The courier runs. The camera pans left.",
         ("The courier runs.", [note("N20", "camera direction", "The camera pans left.")])),
        ("The courier runs while the camera tracks him.",
         ("The courier runs.", [note("N20", "camera direction", "while the camera tracks him.")])),
        ("The courier runs. The camera pushes in. The camera holds.",
         ("The courier runs. The camera pushes in.",
          [note("N20", "camera direction", "The camera holds.")])),
        ("The courier turns toward the camera and speaks.",
         ("The courier turns toward the camera.",
          [note("N7", "dialogue and text", "and speaks.")])),
        ("The courier speaks softly. The courier waves.",
         ("The courier waves.", [note("N7", "dialogue and text", "The courier speaks softly.")])),
        ("The courier speaks.", ("The courier speaks.", [])),
        ("The camera pans left.", ("The camera pans left.", [])),
    )
    for text, want in rows:
        assert se.repair_action_text(ctx, plan, 1, text) == want, text
    reply = dict(seu.panel_json("shots", 1), motion="The courier runs. The camera pans left.")
    part = se.parse_panel_reply(ctx, plan, 1, json.dumps(reply))
    assert part["motion"] == "The courier runs."
    assert part["repairs"] == [note("N20", "camera direction", "The camera pans left.")]
    plain = se.parse_panel_reply(ctx, plan, 1, json.dumps(seu.panel_json("shots", 1)))
    assert "repairs" not in plain
    text = se.assemble(ctx, plan, [part])
    path = os.path.join(ctx.story_dir, "check.md")
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    hard, advisory = se.panel_checks(ctx, plan, [part], text, path)
    assert note("N20", "camera direction", "The camera pans left.") in advisory
    assert [m for m in hard if " N20 " in m] == []


# --- SFT9: N7 is hard while generating, on the Motion or Prompt only (SF11, SK8) ----------------

def test_sft9_n7_severity(ws):
    ctx = seu.make_ctx(se, ws, mode="shots", panels=1)
    plan, _shape = se.normalize_plan(ctx, seu.plan_json("shots", 1))

    def n7(label, text, generating):
        hard, advisory = se._field_checks(ctx, lib, plan, 1, "T", [(label, text)], {label: text},
                                          se.GENERATION_CHECKS, (), generating=generating)
        return [m for m in hard if " N7 " in m], [m for m in advisory if " N7 " in m]

    assert n7("Motion", "The courier speaks.", True) == (
        ["panel 1: N7 dialogue and text: Motion: says 'speaks'; the pipeline adds the spoken line "
         "itself, so write only what the speaker physically does, with no speaking verb"], [])
    assert n7("Motion", "The courier speaks.", False) == (
        [], ["panel 1: N7 dialogue and text: Motion: says 'speaks'"])
    assert n7("Image", "The courier speaks.", True) == (
        [], ["panel 1: N7 dialogue and text: Image: says 'speaks'"])
    quoted = 'The courier holds up a sign reading "Closed".'
    for generating in (True, False):
        assert n7("Motion", quoted, generating) == (
            [], ["panel 1: N7 dialogue and text: Motion: contains a double quote"]), generating


# --- SFT10, Review Focus 4: N21 detection (SF10, SK7) ------------------------------------------

def N21_EXIT(label, sentence, words, speaker):
    return ("panel 1: N21 after the line: %s: '%s' has a character leave the frame or turn away "
            "('%s'); '%s' speaks in this panel, so end it with '%s' still in frame, face toward "
            "the camera" % (label, sentence, words, speaker, speaker))


def N21_ACTOR(label, sentence, actor, speaker):
    return ("panel 1: N21 after the line: %s: '%s' has '%s' act after the spoken line; after the "
            "line only '%s' reacts, and nobody else acts" % (label, sentence, actor, speaker))


def _n21_plan(ws, story_env, mode, speaker="c1"):
    """A 1-panel movie with kyra (c1) and ronin (c2); beat 1 cast both, speaker `speaker`."""
    ctx = seu.make_ctx(se, ws, mode=mode, panels=1, members=_members(story_env),
                       narration="speech")
    plan, _shape = se.normalize_plan(ctx, _raw(mode, 1, [["c1", "c2"]], [speaker]))
    return ctx, plan


def _n21(ctx, plan, writer):
    """(hard N21 messages, advisory N21 messages) of panel 1 with writer action text writer."""
    label = "Prompt" if ctx.mode == "no_stills" else "Motion"
    hard, advisory = se._field_checks(ctx, lib, plan, 1, "T", [(label, writer)], {label: writer},
                                      se.GENERATION_CHECKS, (), generating=True)
    return [m for m in hard if " N21 " in m], [m for m in advisory if " N21 " in m]


def test_sft10_n21_detection(ws, story_env):
    for mode in ("shots", "chained", "no_stills"):
        ctx, plan = _n21_plan(ws, story_env, mode)
        label = "Prompt" if mode == "no_stills" else "Motion"
        exits = (
            ("The woman in grey turns to the camera. The woman in grey skates away.",
             "The woman in grey skates away.", "skates away"),
            ("The woman in grey turns to the camera, then walks off.",
             "The woman in grey turns to the camera, then walks off.", "walks off"),
            ("The woman in grey turns. The camera holds on her as she recedes.",
             "The camera holds on her as she recedes.", "recedes"),
        )
        for writer, sentence, words in exits:
            assert _n21(ctx, plan, writer) == ([N21_EXIT(label, sentence, words, KYRA)], []), (
                mode, writer)
        actors = (
            ("The woman in grey turns. The ronin bows.", "The ronin bows.", "the ronin"),
            ("The woman in grey turns. The woman in grey nods as the ronin bows.",
             "The woman in grey nods as the ronin bows.", "the ronin"),
            ("The woman in grey turns. The crowd cheers.", "The crowd cheers.", "the crowd"),
        )
        for writer, sentence, actor in actors:
            want = [] if mode == "no_stills" else [N21_ACTOR(label, sentence, actor, KYRA)]
            assert _n21(ctx, plan, writer) == (want, []), (mode, writer)
        for writer in ("The woman in grey turns. The woman in grey glances back at the ronin.",
                       "The woman in grey turns. Her shoulders drop."):
            assert _n21(ctx, plan, writer) == ([], []), (mode, writer)
        three = "The woman in grey turns. The woman in grey nods. The woman in grey breathes."
        want = [] if mode == "no_stills" else [
            "panel 1: N21 after the line: %s: has 2 sentences after the first one, which the "
            "spoken line follows; after the line write at most one short sentence of how '%s' "
            "reacts" % (label, KYRA)]
        assert _n21(ctx, plan, three) == ([], want), mode
        ctx, silent = _n21_plan(ws, story_env, mode, speaker="")
        assert _n21(ctx, silent, exits[0][0]) == ([], []), mode
    ctx = seu.make_ctx(se, ws, mode="shots", panels=1, narration="speech")
    raw = seu.plan_json("shots", 1)
    raw["beats"][0]["speaker"] = "c1"
    plan, _shape = se.normalize_plan(ctx, raw)
    assert _n21(ctx, plan, "The courier turns. The old monk bows.") == (
        [N21_ACTOR("Motion", "The old monk bows.", "the old monk", "the courier")], [])


def test_review_focus_4_the_speakers_own_name_and_an_object_are_not_other_actors(ws, story_env):
    for mode in ("chained", "shots"):
        ctx, plan = _n21_plan(ws, story_env, mode)
        for writer in ("The woman in grey turns. Kyra nods.",
                       "The woman in grey turns. The woman in grey waves to the crowd.",
                       "The woman in grey turns. She glances at the ronin."):
            assert _n21(ctx, plan, writer) == ([], []), (mode, writer)


# --- SFT12: N22, the reference copy (SF12, SK9) ------------------------------------------------

def test_sft12_reference_copies(ws):
    narrative = seu.make_ctx(se, ws).narrative
    raw = seu.plan_json("shots", 1)
    assert se.reference_copies(narrative, raw, "The courier walks past the zinc counter.") == [
        "zinc"]
    hits = se.reference_copies(narrative, raw,
                               "The courier looks up from the empty ice trays to the camera")
    assert hits[0] == "ice trays"
    assert "looks up from the empty ice" in hits
    assert se.reference_copies(narrative, raw, "The courier runs at real-time speed.") == []
    market = "The courier locks the fish market."
    assert se.reference_copies(narrative, raw, market) == ["fish market"]
    assert se.reference_copies("A courier closes a fish market at dawn.", raw, market) == []
    ctx = seu.make_ctx(se, ws, mode="shots", panels=1)
    plan, _shape = se.normalize_plan(ctx, raw)
    part = se.parse_panel_reply(ctx, plan, 1, json.dumps(
        dict(seu.panel_json("shots", 1), motion=se.REFERENCE_COPY_SEGMENTS[4] + ".")))
    text = se.assemble(ctx, plan, [part])
    path = os.path.join(ctx.story_dir, "check.md")
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    hard, _advisory = se.panel_checks(ctx, plan, [part], text, path)
    assert [m for m in hard if " N22 " in m] == [
        "panel 1: N22 reference copy: Motion: copies the format reference ('fishmonger', 'cloth "
        "drop onto the counter her', 'drop onto the counter her shoulders'); describe only this "
        "movie's own people, places, objects and words"]
    fixtures = os.path.join(WS, "tests", "fixtures")
    seen = 0
    for root, _dirs, names in os.walk(fixtures):
        for name in names:
            with open(os.path.join(root, name), encoding="utf-8") as f:
                words = se.line_words(f.read())
            seen += 1
            line = " " + " ".join(words) + " "
            assert not (se._six_grams(words) & se.REFERENCE_SIX_GRAMS), name
            assert [t for t in se.REFERENCE_TERMS
                    if " %s " % " ".join(se.line_words(t)) in line] == [], name
    assert seen >= 40
    for segment in se.REFERENCE_COPY_SEGMENTS[:-1]:
        assert segment in se.FORMAT_REFERENCE, segment
    assert ('"Forty years of mornings." After a breath, "Not one more."' in se.FORMAT_REFERENCE)
    assert se.line_words(se.REFERENCE_COPY_SEGMENTS[-1]) == se.line_words(
        "Forty years of mornings. Not one more.")


# --- SFT15: the S4/S5 parameters of generation (SF14, SF15c) -----------------------------------

def test_sft15_the_s4_and_s5_parameters(ws):
    two = "The courier lifts the letter at real-time speed. The courier nods. The camera pushes in."
    three = ("The courier lifts the letter. The courier nods. The courier sighs. The camera pushes "
             "in.")
    assert lib.motion_problems(two, ["the courier"], max_actions=2) == []
    assert lib.motion_problems(three, ["the courier"], max_actions=2) == [
        ("S5 one action", "Motion: has 3 action sentences; a speaking shot has one, or one and "
                          "the speaker's reaction, optionally followed by a camera sentence")]
    assert lib.motion_problems(two, ["the courier"]) == [
        ("S5 one action", "Motion: has 2 action sentences; it must have exactly one, optionally "
                          "followed by a camera sentence")]
    ctx = seu.make_ctx(se, ws, mode="shots", panels=1, narration="speech")
    raw = seu.plan_json("shots", 1)
    raw["beats"][0].update(speaker="c1", camera="slow push-in")
    plan, _shape = se.normalize_plan(ctx, raw)
    part = {"title": "The Letter", "image": seu.panel_json("shots", 1)["image"], "motion": two,
            "dialogue": "Go now."}
    text = se.assemble(ctx, plan, [part])
    path = os.path.join(ctx.story_dir, "check.md")
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    _hard, advisory = se.panel_checks(ctx, plan, [part], text, path)
    assert [m for m in advisory if " S5 one action" in m] == []
    panels = se._story_manifest(ctx.ws)._parse_prompts_md(path)[1]
    assert [v for v in lib.shots_violations(text, panels, 1, [], True, ignore_facing=True)
            if " S5 one action" in v] == [
        "panel 1: S5 one action: Motion: has 2 action sentences; it must have exactly one, "
        "optionally followed by a camera sentence"]
    motion = " ".join(["word"] * 19) + " end."
    assert lib.shots_advisories([{"number": 1, "motion": motion, "image": ""}], [],
                                motion_words=(55, 105)) == [
        "panel 1: S4 motion length: Motion: is 20 words; aim for 55-105"]
    assert lib.shots_advisories([{"number": 1, "motion": motion, "image": ""}], []) == []


# --- SFT17: old stories re-check exactly as before (D12, SK10) ---------------------------------

def test_sft17_an_old_story_rechecks_as_before(ws, monkeypatch):
    monkeypatch.setattr(ltx_movie, "WS", ws)
    ctx, _plan, _parts = _hockey(ws, story_id="sf17")
    for name in ("plan.json", "story.md"):
        with open(os.path.join(HOCKEY_FIX, name), encoding="utf-8") as f:
            text = f.read()
        with open(os.path.join(ctx.story_dir, name), "w", encoding="utf-8") as f:
            f.write(text)
    with open(os.path.join(ctx.story_dir, "story.md"), encoding="utf-8") as f:
        story = f.read()
    assert "as he speaks." in story and (
        "The camera holds on him as he recedes. FuboTV hockey player faces the camera. "
        "The camera stays static." in story)

    def refuse(*args, **kwargs):
        raise AssertionError("recheck must not repair, compare with the reference or cap cameras")

    for name in ("repair_action_text", "reference_copies", "cap_static_cameras"):
        monkeypatch.setattr(se, name, refuse)
    rc, advisories = se.recheck(ctx, ltx_movie._validate_story_md)
    assert rc == 0
    assert "panel 1: N7 dialogue and text: Motion: says 'speaks'" in advisories
    assert [a for a in advisories if " N20 " in a or " N21 " in a or " N22 " in a] == []
    checks = _read_json(ctx.story_dir, "story_checks.json")
    assert checks["hard"] == [] and checks["source"] == "recheck"


# --- SFT18: the exit verbs (SF10) --------------------------------------------------------------

def test_sft18_exit_verbs():
    for words in ("skates away", "walks off", "turns away", "steps off", "pulls away",
                  "leaves the frame", "exits", "disappears into", "out of frame", "out of the shot",
                  "into the distance", "recedes", "turns her back"):
        assert se.EXIT_RE.search("She %s now." % words), words
    for words in ("pushes off from the kerb", "turns off the light", "the leaves fall",
                  "the exit sign", "steps back", "turns toward the camera", "runs down the steel"):
        assert se.EXIT_RE.search("She %s now." % words) is None, words


# --- SFT1 (Task 4 part): the repair constants (SF13) -------------------------------------------

FORMAT_IDS = ("N7", "N20", "N21", "N22")
REPAIR_IDS = ("N7", "N11", "N18", "N20", "N21", "N22", "T1", "T2", "T3")
CRITIC_SPEAKING_MOTION_CLAUSE = (
    " On a panel with a Dialogue: line, the pipeline inserts the spoken words right after the "
    "first sentence about what the speaker does, so keep everything the speaker does before "
    "the line in that first sentence and at most one short sentence of the speaker's reaction "
    "after it, in which nobody else acts and the speaker never leaves the frame. Begin each of "
    "those sentences with the speaker's referring phrase.")
MOTION_LINE = ('- target "panel", field "%s", index = the panel number, only for a panel with '
               "a [hard] T2, T3, N7, N20, N21 or N22 problem: replacement is the panel's whole new "
               "%s: writer text, identical to the current text except for the sentence or "
               "sentences that cause the problem.")
DIALOGUE_LINE = ('- target "panel", field "dialogue", index = the panel number, only for a panel '
                 "with a [hard] T1, N18 or N22 problem: replacement is the new spoken line, "
                 "without the speaker's phrase and without quotation marks, within the limit a T1 "
                 "problem states.")


def test_sft1d_repair_constants():
    assert se.FORMAT_IDS == FORMAT_IDS
    assert se.REPAIR_IDS == REPAIR_IDS
    assert se.CRITIC_SPEAKING_MOTION_CLAUSE == CRITIC_SPEAKING_MOTION_CLAUSE
    assert "slowly" not in se.CRITIC_SPEAKING_MOTION_CLAUSE.lower()


# --- SFT11, Review Focus 2: the round-0 re-ask, then the trim (SF13d, SK7) ----------------------

SFT11_EXIT = "The woman in grey turns to the camera. The woman in grey walks away."
SFT11_CLEAN = "The woman in grey turns to the camera at real-time speed."


def _sft11_reply(motion):
    return seu.answer({"title": "At The Gate", "image": seu.panel_json("shots", 1, KYRA)["image"],
                       "motion": motion, "dialogue": "We go now."})


def _sft11_run(ws, tmp_path, monkeypatch, story_env, story_id, panel_1):
    """(rc, ctx, agent log) of a shots run: 2 panels, kyra and ronin pinned, --speech-only; beat
    1 casts kyra, who speaks; beat 2 casts the ronin, silent; panel 1 gets the replies panel_1."""
    raw = _raw("shots", 2, [["c1"], ["c2"]], ["c1", ""])
    log = seu.script_agent(monkeypatch, tmp_path, plan=[seu.answer(raw)],
                           panel={"1": panel_1,
                                  "2": [seu.answer(seu.panel_json("shots", 2, RONIN))]})
    ctx = seu.make_ctx(se, ws, mode="shots", panels=2, members=_members(story_env),
                       narration="speech", story_id=story_id)
    rc, _advisories = se.run(ctx)
    return rc, ctx, seu.agent_log(log)


def _motion_lines(ctx):
    with open(os.path.join(ctx.story_dir, "story.md"), encoding="utf-8") as f:
        return [line for line in f.read().splitlines() if line.startswith("Motion: ")]


def _messages(ctx, key):
    return [entry["message"] for entry in _read_json(ctx.story_dir, "story_checks.json")[key]]


def test_sft11_the_round_0_re_ask_then_the_trim(ws, tmp_path, monkeypatch, story_env):
    removed = se.REPAIR_NOTE % (1, "N21", "after the line", "Motion",
                                "'The woman in grey walks away.'")
    rc, ctx, log = _sft11_run(ws, tmp_path, monkeypatch, story_env, "sf11a",
                              [_sft11_reply(SFT11_EXIT), _sft11_reply(SFT11_CLEAN)])
    assert rc == 0
    assert [r["stage"] for r in log] == ["plan", "panel", "panel", "panel"]
    with open(os.path.join(ctx.story_dir, "story_rounds", "round_0", "panel_01_prompt_2.txt"),
              encoding="utf-8") as f:
        assert ("Your previous version of this panel was rejected. Problems:\n- panel 1: N21 after "
                "the line: Motion: ") in f.read()
    assert _motion_lines(ctx)[0].startswith("Motion: " + SFT11_CLEAN)
    assert [m for m in _messages(ctx, "advisory") if "the pipeline removed" in m] == []
    rc, ctx, log = _sft11_run(ws, tmp_path, monkeypatch, story_env, "sf11b",
                              [_sft11_reply(SFT11_EXIT), _sft11_reply(SFT11_EXIT)])
    assert rc == 0
    assert [r["stage"] for r in log] == ["plan", "panel", "panel", "panel"]
    assert "walks away" not in _motion_lines(ctx)[0]
    assert _motion_lines(ctx)[0].startswith("Motion: The woman in grey turns to the camera. ")
    assert removed in _messages(ctx, "advisory")
    rc, ctx, log = _sft11_run(ws, tmp_path, monkeypatch, story_env, "sf11c",
                              [_sft11_reply("The woman in grey skates away.")] * 2)
    assert rc == 2
    assert [r["stage"] for r in log][:4] == ["plan", "panel", "panel", "panel"]
    assert _messages(ctx, "hard") == [N21_EXIT("Motion", "The woman in grey skates away.",
                                               "skates away", KYRA)]


def test_review_focus_2_an_unparseable_re_ask_keeps_the_first_reply_and_trims(
        ws, tmp_path, monkeypatch, story_env):
    rc, ctx, log = _sft11_run(ws, tmp_path, monkeypatch, story_env, "sfrf2",
                              [_sft11_reply(SFT11_EXIT), {"answer": "not json"}])
    assert rc == 0
    assert [r["stage"] for r in log] == ["plan", "panel", "panel", "panel"]
    assert _motion_lines(ctx)[0] == ("Motion: The woman in grey turns to the camera. The woman in "
                                     "grey faces the camera. The camera stays static.")
    assert se.REPAIR_NOTE % (1, "N21", "after the line", "Motion",
                             "'The woman in grey walks away.'") in _messages(ctx, "advisory")


# --- SFT16, Review Focus 1: the critic, the patches and merge_repair (SF13e-h) -----------------

def _patch(target, index, field, replacement, reason="because"):
    return {"target": target, "index": index, "field": field, "reason": reason,
            "replacement": replacement}


def _speaking_state(ws, motion):
    """(ctx, state) of a 1-panel shots movie, --speech-only: the courier speaks, the camera is
    a slow push-in, and the writer's Motion is motion."""
    ctx = seu.make_ctx(se, ws, mode="shots", panels=1, narration="speech")
    raw = seu.plan_json("shots", 1)
    raw["beats"][0].update(speaker="c1", camera="slow push-in")
    plan, _shape = se.normalize_plan(ctx, raw)
    part = {"title": "The Gate", "image": seu.panel_json("shots", 1)["image"], "motion": motion,
            "dialogue": "Go now."}
    return ctx, {"plan": plan, "parts": [part]}


SFT16_EXIT = "The courier turns to the camera. The courier walks away."


def test_sft16_the_critic_lines_the_patches_and_merge_repair(ws):
    for mode, label in (("chained", "Motion"), ("shots", "Motion"), ("no_stills", "Prompt")):
        assert se.critic_field_lines(mode, None) == (
            MOTION_LINE % (label.lower(), label) + "\n" + DIALOGUE_LINE), mode
    ctx, state = _speaking_state(ws, SFT16_EXIT)
    new, applied, rejected = se.apply_patches(
        ctx, state, [_patch("panel", 1, "motion", "The courier turns to the camera.")],
        repairable={1: {"N21"}})
    assert (len(applied), rejected) == (1, [])
    assert new["parts"][0]["motion"] == "The courier turns to the camera."
    new, applied, rejected = se.apply_patches(
        ctx, state, [_patch("panel", 1, "motion", SFT16_EXIT)], repairable={1: {"N21"}})
    assert applied == []
    assert [r["reason"] for r in rejected] == [
        "the patch does not fix the panel's N7, N20, N21 or N22 problem"]
    new, applied, rejected = se.apply_patches(
        ctx, state, [_patch("panel", 1, "motion",
                            "The courier sits. The courier waits. The courier nods.")],
        repairable={1: {"T2"}})
    assert [r["reason"] for r in rejected] == [
        "the patch changes 2 sentences; it may change at most 1 contiguous sentence(s) and must "
        "keep every other sentence word for word"]
    old = dict(state["parts"][0], image="The courier stands by the zinc counter.")
    fixed = dict(state["parts"][0], image="The courier stands by the wooden gate.")
    assert se.merge_repair(ctx, state["plan"], 1, old, fixed, {"N22"})["image"] == (
        "The courier stands by the wooden gate.")
    assert se.merge_repair(ctx, state["plan"], 1, old, fixed, {"T2"})["image"] == (
        "The courier stands by the zinc counter.")


def test_review_focus_1_a_critic_patch_keeps_an_end_framed_camera_sentence_whole(ws):
    ctx, state = _speaking_state(ws, SFT16_EXIT)
    replacement = ("The courier turns to the camera. The camera pushes in — as the move "
                   "completes, his face fills the frame.")
    new, applied, rejected = se.apply_patches(
        ctx, state, [_patch("panel", 1, "motion", replacement)], repairable={1: {"N21"}})
    assert (len(applied), rejected) == (1, [])
    assert new["parts"][0]["motion"] == replacement
    field = dict(se.panel_fields(ctx, new["plan"], new["parts"], 1))["Motion"]
    assert field == ("The courier turns to the camera. The camera pushes in — as the move "
                     "completes, his face fills the frame. The courier faces the camera.")


# --- SFT19, SFT20, Review Focus 3: the trim (SF13b) --------------------------------------------

def test_sft19_the_trim_keeps_the_only_action(ws):
    ctx, plan, parts = _hockey(ws, story_id="sf19")
    part = dict(parts[1], motion="The FuboTV hockey player skates away.")
    assert se.trim_format(ctx, plan, 2, part) == part
    assert se.format_problems(ctx, plan, part, 2) != []


def test_sft20_the_chained_hockey_shape(ws):
    ctx, plan, parts = _hockey(ws, story_id="sf20")
    first, cut = ("The FuboTV hockey player carves a sharp stop, spraying ice mist into the air, "
                  "his face toward the lens, then pushes off and skates away from the camera.",
                  "The FuboTV hockey player carves a sharp stop, spraying ice mist into the air, "
                  "his face toward the lens, then pushes off.")
    assert se.panel_camera(ctx, plan, 2) == "static"
    assert se.format_problems(ctx, plan, parts[1], 2) == [
        "panel 2: N21 after the line: Motion: '%s' has a character leave the frame or turn away "
        "('skates away'); 'FuboTV hockey player' speaks in this panel, so end it with 'FuboTV "
        "hockey player' still in frame, face toward the camera" % first]
    trimmed = se.trim_format(ctx, plan, 2, parts[1])
    assert trimmed["motion"] == cut
    assert trimmed["repairs"] == [
        se.REPAIR_NOTE % (2, "N21", "after the line", "Motion",
                          "'and skates away from the camera.'"),
        se.REPAIR_NOTE % (2, "N21", "after the line", "Motion",
                          "'The camera holds on him as he recedes.'")]
    assert se.format_problems(ctx, plan, trimmed, 2) == []
    assert se.repair_action_text(ctx, plan, 2, parts[1]["motion"]) == (parts[1]["motion"], [])
    assert se.repair_action_text(ctx, plan, 1, parts[0]["motion"]) == (
        "The FuboTV hockey player skates forward toward the camera, his face toward the lens, in "
        "frame and lit.", [se.REPAIR_NOTE % (1, "N7", "dialogue and text", "Motion",
                                             "'as he speaks.'")])


def test_review_focus_3_an_end_frame_in_the_references_words_falls_back(ws):
    camera = ("The camera pushes in — as the move completes, her face fills the frame from chin "
              "to brow.")
    ctx, state = _speaking_state(ws, "The courier turns to the camera at real-time speed. "
                                 + camera)
    plan, part = state["plan"], state["parts"][0]
    problems = se.format_problems(ctx, plan, part, 1)
    assert [m for m in problems if " N22 " in m] == problems
    assert len(problems) == 1
    assert problems[0].startswith("panel 1: N22 reference copy: Motion: copies the format "
                                  "reference ('")
    trimmed = se.trim_format(ctx, plan, 1, part)
    assert trimmed["motion"] == "The courier turns to the camera at real-time speed."
    assert trimmed["repairs"] == [se.REPAIR_NOTE % (1, "N22", "reference copy", "Motion",
                                                    se._q(camera))]
    assert dict(se.panel_fields(ctx, plan, [trimmed], 1))["Motion"] == (
        "The courier turns to the camera at real-time speed. The courier faces the camera. The "
        "camera pushes in.")


# --- SFT23, SFT24, SFT25: P19, the exit after the last line (amendment SF-A1) --------------------

P19_NOTE = ("plan: P19 exit left out: the narrative's exit after its last spoken line (%s) was "
            "left out, because that line is in the last beat and a speaking beat never shows its "
            "speaker leave; %s")
P19_ROOM_HINT = ("the planner could have added a beat for it (this movie may have up to %d), so "
                 "rerun with --force-story, or rerun with --force-story --panels %d to keep it")


def test_sft23_the_narratives_exit_after_its_last_line():
    assert HOCKEY_NARRATIVE == _read_json(HOCKEY_FIX, "plan.json")["narrative"]
    rows = (
        (HOCKEY_NARRATIVE, "skates away"),
        (LINES_NARRATIVE, None),
        ('Kyra says, "Go." She walks off.', "walks off"),
        ('Kyra walks off. Kyra says, "Go."', None),
        ('Kyra says, "Go," and the ronin leaves the frame.', None),
        ('Kyra says, "Go." Later the crowd says, "Yes." Kyra turns away.', "turns away"),
        ('A sign reads "Closed". Kyra walks away.', None),
        ('Kyra says, "Go." She pushes off from the kerb.', None),
        ('Kyra says, “Go.” She skates away.', "skates away"),
    )
    for narrative, want in rows:
        assert se.narrative_exit_after_last_line(narrative) == want, narrative


def _p19_plan(ws, mode, lines, narrative=HOCKEY_NARRATIVE, narration="speech"):
    """(ctx, normalised plan) of len(lines) beats: beat k says lines[k - 1], spoken by the courier
    (c1) when it has lines."""
    ctx = seu.make_ctx(se, ws, mode=mode, panels=len(lines), narrative=narrative,
                       narration=narration)
    raw = seu.plan_json(mode, len(lines))
    for beat, numbers in zip(raw["beats"], lines):
        beat.update(lines=list(numbers), speaker="c1" if numbers else "")
    plan, _shape = se.normalize_plan(ctx, raw)
    return ctx, plan


def test_sft24_when_p19_fires(ws):
    rows = (
        ("chained", [[1], [2]], {}, [P19_NOTE % ("'skates away'", P19_ROOM_HINT % (4, 3))]),
        ("chained", [[1, 2]], {}, [P19_NOTE % ("'skates away'", P19_ROOM_HINT % (3, 2))]),
        ("shots", [[1], [2], []], {}, []),
        ("shots", [[1], [], [2]], {}, [P19_NOTE % ("'skates away'", P19_ROOM_HINT % (5, 4))]),
        ("chained", [[1], [2]], {"narration": False}, []),
        ("chained", [[1], []], {}, []),
        ("chained", [[1], [2]], {"narrative": LINES_NARRATIVE}, []),
        ("shots", [[1], [], [2]], {"narrative": LINES_NARRATIVE}, []),
    )
    for mode, lines, kw, want in rows:
        ctx, plan = _p19_plan(ws, mode, lines, **kw)
        assert se.exit_left_out_notes(ctx, plan) == want, (mode, lines, kw)
    assert se.P19_NOTE == P19_NOTE
    violation = se.parse_violation(P19_NOTE % ("'x'", 3))
    assert (violation["id"], violation["name"], violation["scope"], violation["index"]) == (
        "P19", "exit left out", "plan", None)


def _sft25_run(ws, tmp_path, monkeypatch, story_id, narrative):
    """(rc, advisories, ctx) of a chained 2-panel --speech-only run of narrative: beat k says
    spoken line k, spoken by the courier."""
    raw = seu.plan_json("chained", 2)
    raw["beats"][0].update(speaker="c1", lines=[1])
    raw["beats"][1].update(speaker="c1", lines=[2])
    panel = {"1": [seu.answer({"title": "Skate In", "image": seu.panel_json("chained", 1)["image"],
                               "motion": "The courier glides toward the camera at real-time "
                                         "speed, his face to the lens.",
                               "dialogue": "x"})],
             "2": [seu.answer({"title": "The Stop",
                               "motion": "The courier carves a hard stop at real-time speed, a "
                                         "big bright spray of ice in the air.",
                               "dialogue": "x"})]}
    seu.script_agent(monkeypatch, tmp_path, plan=[seu.answer(raw)], panel=panel)
    ctx = seu.make_ctx(se, ws, mode="chained", panels=2, narration="speech", narrative=narrative,
                       story_id=story_id)
    rc, advisories = se.run(ctx)
    return rc, advisories, ctx


def test_sft25_p19_end_to_end(ws, tmp_path, monkeypatch, capsys):
    note = P19_NOTE % ("'skates away'", P19_ROOM_HINT % (4, 3))
    rc, advisories, ctx = _sft25_run(ws, tmp_path, monkeypatch, "sf25", HOCKEY_NARRATIVE)
    assert rc == 0
    assert [a for a in advisories if " P19 " in a] == [note]
    assert note.endswith(", or rerun with --force-story --panels 3 to keep it")
    assert [m for m in _messages(ctx, "advisory") if " P19 " in m] == [note]
    assert note in _read_json(ctx.story_dir, "plan.json")["speech_notes"]
    capsys.readouterr()
    rc, advisories = se.recheck(ctx, lambda path, panels, no_stills=False: [])
    captured = capsys.readouterr()
    assert rc == 0
    assert [a for a in advisories if "P19" in a] == []
    assert "P19" not in captured.out + captured.err
    rc, advisories, ctx = _sft25_run(ws, tmp_path, monkeypatch, "sf25b", LINES_NARRATIVE)
    assert rc == 0
    assert [a for a in advisories if "P19" in a] == []
    assert [m for m in _messages(ctx, "advisory") if "P19" in m] == []


# --- SFT1 (Task 6 part): the audio sentences (SF15a, SF15b) -------------------------------------

ACOUSTIC_SENTENCE = ("The audio is clear close-mic dialogue with a subtle natural room tone; "
                     "the dialogue takes priority over the quiet ambience, and there is no music.")
AMBIENCE_SENTENCE = "The audio is the natural ambient sound of the place, with no music."


def test_sft1e_audio_constants():
    assert lib.ACOUSTIC_SENTENCE == ACOUSTIC_SENTENCE
    assert lib.AMBIENCE_SENTENCE == AMBIENCE_SENTENCE
    assert se.FORMAT_REFERENCE.count(ACOUSTIC_SENTENCE) == 1
    assert se.FORMAT_REFERENCE.count(AMBIENCE_SENTENCE) == 2


# --- SFT13: the composition and the reference's self-consistency (SF15, SF8, SK6) ---------------

def test_sft13_the_composition_and_the_reference(ws):
    shots = ref_shots()
    assert len(shots) == 3
    for part, shot in zip(REF_PARTS, shots):
        assert lib.panel_prompt(part["motion"], part["shot"], part["speaker"], part["line"],
                                "beats", [REF_PHRASE]) == shot
    for part, key in zip(REF_PARTS, ("tracking", "slow push-in", "static")):
        assert se.camera_problem(lib, part["motion"], [REF_PHRASE], key) is None, key
    post = se.post_line_sentences(lib, REF_PARTS[1]["motion"], [REF_PHRASE])
    assert post == ["The old fishmonger lets the folded cloth drop onto the counter, her "
                    "shoulders sinking."]
    assert se._other_actor(post[0], [], se._mentions([{"id": "c1", "phrase": REF_PHRASE}])) is None
    assert lib.compose_motion("The camera tracks alongside the movement. A runs.", "S", ["x"]) == (
        "A runs. S The camera tracks alongside the movement.")
    assert lib.compose_motion("A. X faces the camera. B. The camera tracks alongside the movement.",
                              "S", ["x"]) == (
        "A. X faces the camera. S B. The camera tracks alongside the movement.")
    assert lib.compose_motion("X faces the camera. The camera tracks alongside the movement.", "S",
                              ["x"], "AUDIO.", "The shot is a close-up.") == (
        "The shot is a close-up. X faces the camera. S The camera tracks alongside the movement. "
        "AUDIO.")
    assert lib.compose_motion("The shot is a close-up. A runs.", "", ["x"], "",
                              "The shot is a close-up.") == "The shot is a close-up. A runs."
    assert lib.framing_sentence("The courier waits. The shot is a wide shot. The shot is a "
                                "close-up.") == "The shot is a close-up."
    assert lib.framing_sentence("The courier waits.") == ""
    assert lib.panel_prompt("A runs.", "", "x", "Go.", "plain") == 'A runs. X says: "Go."'
    assert lib.panel_prompt("A runs.", "", "x", "Go.", "beats-no-acoustic") == (
        'A runs. X says, "Go."')
    assert lib.panel_prompt("A runs.", "", None, "", "beats") == "A runs. " + AMBIENCE_SENTENCE
    assert lib.panel_prompt("A runs.", "", None, "", "plain") == "A runs."


# --- SFT14: the manifest composes a speech movie in the fixed order (SF16, SK6) ----------------

SFT14_SETTING = seu.HARBOUR


def _sft14_story(panel_1_speech):
    """A 2-panel shots story.md: panel 1 a medium shot with panel_1_speech (a Dialogue: or
    Narration: line), panel 2 a silent wide shot with a Narration: line."""
    return ("# The Letter\n\nA courier brings a letter.\n\n## Characters\n"
            "- \"the courier\": %s.\n\n"
            "## Panel 1 — The Gate\n"
            "Image: %s The courier stands at the gate. The courier faces the camera. The shot is a "
            "medium shot.\n"
            "Motion: The courier lifts the sealed letter at real-time speed. The courier faces the "
            "camera. The camera pushes in.\n"
            "%s\n\n"
            "## Panel 2 — The Road\n"
            "Image: %s The courier walks down the road. The shot is a wide shot.\n"
            "Motion: The courier walks down the road at real-time speed. The camera tracks "
            "alongside the movement.\n"
            "Narration: The road was long.\n") % (seu.COURIER, SFT14_SETTING, panel_1_speech,
                                                   SFT14_SETTING)


SFT14_CHAIN = """# The Gate

A courier reaches a hilltop temple.

## Panel 1 — The Steps
Image: %s The courier climbs toward the gate. The shot is a wide shot.
Motion: The courier climbs the last worn step at real-time speed. The camera tracks alongside the movement.
Narration: The bell had not yet rung.

## Panel 2 — At the Gate
Motion: The old monk lifts his eyes at real-time speed. The old monk faces the camera. The camera pushes in.
Dialogue: the old monk: You came far.
""" % SFT14_SETTING


def _sft14_prompts(tmp_path, monkeypatch, story_id, text, mode, extra=(), plan=None):
    story_md, images, ws = _manifest_ws(tmp_path, monkeypatch, story_id, text, plan=plan,
                                        images=1 if mode == "chain" else 2)
    if mode == "v2":
        argv = ["--story-id", story_id, "--prompts-md", story_md, "--image", images[0],
                "--image", images[1], "--fps", "24", "--target-seconds", repr(145 * 2 / 24.0),
                "--min-frames", "145", "--max-frames", "145", "--force"] + list(extra)
    else:
        argv = _manifest_argv(story_id, story_md, images, mode=mode, extra=extra)
    assert story_manifest.main(argv) == 0
    return [p["motion_prompt"] for p in _read_manifest(ws, story_id)["panels"]]


def test_sft14_the_manifest_composes_the_fixed_order(tmp_path, monkeypatch):
    speaking = _sft14_story("Dialogue: the courier: Go now.")
    assert _sft14_prompts(tmp_path, monkeypatch, "sf14a", speaking, "shots") == [
        "The shot is a medium shot. The courier lifts the sealed letter at real-time speed. The "
        "courier faces the camera. The courier says, \"Go now.\" The camera pushes in. "
        + ACOUSTIC_SENTENCE,
        "The shot is a wide shot. The courier walks down the road at real-time speed. The camera "
        "tracks alongside the movement. " + AMBIENCE_SENTENCE]
    assert _sft14_prompts(tmp_path, monkeypatch, "sf14b", SFT14_CHAIN, "chain",
                          plan=CAST_PLAN) == [
        "The shot is a wide shot. The courier climbs the last worn step at real-time speed. The "
        "camera tracks alongside the movement. " + AMBIENCE_SENTENCE,
        "The old monk lifts his eyes at real-time speed. The old monk faces the camera. The old "
        "monk says, \"You came far.\" The camera pushes in. " + ACOUSTIC_SENTENCE]
    silent = _sft14_story("Narration: The gate was shut.")
    assert _sft14_prompts(tmp_path, monkeypatch, "sf14c", silent, "shots") == [
        "The courier lifts the sealed letter at real-time speed. The courier faces the camera. The "
        "camera pushes in.",
        "The courier walks down the road at real-time speed. The camera tracks alongside the "
        "movement."]
    assert _sft14_prompts(tmp_path, monkeypatch, "sf14d", speaking, "v2") == [
        "The courier lifts the sealed letter at real-time speed. The courier faces the camera. The "
        "courier says, \"Go now.\" The camera pushes in. " + ACOUSTIC_SENTENCE,
        "The courier walks down the road at real-time speed. The camera tracks alongside the "
        "movement."]
    assert _sft14_prompts(tmp_path, monkeypatch, "sf14e", speaking, "shots",
                          extra=["--speech-delivery", "plain"]) == [
        "The shot is a medium shot. The courier lifts the sealed letter at real-time speed. The "
        "courier faces the camera. The courier says: \"Go now.\" The camera pushes in.",
        "The shot is a wide shot. The courier walks down the road at real-time speed. The camera "
        "tracks alongside the movement."]


# --- Final review fix wave (FW-I1 to FW-I4) ----------------------------------------------------

def test_fw1_old_chained_story_rechecks_without_new_t2(ws, tmp_path, monkeypatch):
    monkeypatch.setattr(ltx_movie, "WS", ws)
    raw = seu.plan_json("chained", 2)
    for k, beat in enumerate(raw["beats"]):
        beat["camera"] = ("tracking", "slow pan left")[k]
        beat["speaker"] = ""
    part_1 = seu.panel_json("chained", 1)
    part_2 = seu.panel_json("chained", 2)
    part_2["title"] = "Quay"
    part_2["motion"] = ("The courier pedals steadily along the wet road toward the quay. The courier "
                        "leans into the bend. The camera pans left across the moored fishing boats.")
    part_2["narration"] = seu.NARRATIONS[1]
    seu.script_agent(monkeypatch, tmp_path, plan=[seu.answer(raw)],
                     panel={"1": [seu.answer(part_1)], "2": [seu.answer(part_2)]},
                     critic=[seu.answer(seu.critic_json())] * 4)
    made = seu.make_ctx(se, ws, mode="chained", panels=2, story_id="fw1", clip_seconds=121 / 24.0)
    se.run(made)
    ctx = seu.make_ctx(se, ws, mode="chained", panels=2, story_id="fw1_r",
                       clip_seconds=121 / 24.0)
    for name in ("plan.json", "story.md"):
        with open(os.path.join(made.story_dir, name), encoding="utf-8") as f:
            text = f.read()
        with open(os.path.join(ctx.story_dir, name), "w", encoding="utf-8") as f:
            f.write(text)
    rc, _advisories = se.recheck(ctx, ltx_movie._validate_story_md)
    checks = _read_json(ctx.story_dir, "story_checks.json")
    assert rc == 0
    assert checks["unresolved"] == []
    assert checks["hard"] == []


def test_fw2_paraphrased_camera_sentence_is_repaired(ws):
    ctx, plan, _parts = _hockey(ws)
    plan["beats"][0]["camera"] = "slow push-in"
    player = "The FuboTV hockey player glides toward the camera at real-time speed."
    for removed in ("The camera glides closer — as the move completes, his face fills the frame.",
                    "The camera slowly moves in — as the move completes, his face fills the "
                    "frame."):
        repaired, notes = se.repair_action_text(ctx, plan, 1, player + " " + removed)
        assert repaired == player
        assert notes == [se.REPAIR_NOTE % (1, "N20", "camera direction", "Motion", se._q(removed))]
        part = {"title": "t", "image": "A rink.", "motion": repaired, "dialogue": "x"}
        assembled = dict(se.panel_fields(ctx, plan, [part, {}], 1))["Motion"]
        assert assembled == (player + " FuboTV hockey player faces the camera. "
                             "The camera pushes in.")
        assert [m for m in se.format_problems(ctx, plan, part, 1) if " N20 " in m] == []


def test_fw3_merge_repair_takes_new_repairs(ws):
    ctx, plan, _parts = _hockey(ws)
    player = "The FuboTV hockey player"
    old = {"title": "t", "motion": player + " carves a stop at real-time speed. " + player + " nods.",
           "dialogue": "It's just FuboTV.",
           "repairs": ["panel 2: N7 dialogue and text: Motion: the pipeline removed 'OLD STALE'"]}
    new = {"title": "t",
           "motion": player + " carves a short stop at real-time speed. " + player + " nods.",
           "dialogue": "It's just FuboTV.",
           "repairs": ["panel 2: N7 dialogue and text: Motion: the pipeline removed 'NEW'"]}
    merged = se.merge_repair(ctx, plan, 2, old, new, {"T2"})
    assert merged["motion"] == new["motion"]
    assert merged["repairs"] == new["repairs"]
    bare = dict((key, value) for key, value in new.items() if key != "repairs")
    merged = se.merge_repair(ctx, plan, 2, old, bare, {"T2"})
    assert merged["motion"] == bare["motion"]
    assert "repairs" not in merged


def test_fw4_exit_re_ignores_runoff_over_the_body():
    for text in ("rain running off his hood", "snow drifting off her shoulders"):
        assert se.EXIT_RE.search("The courier stands, %s." % text) is None, text
    for text in ("skates off", "walks off", "steps off", "skates off the ice",
                 "pushes off and skates away"):
        assert se.EXIT_RE.search("She %s now." % text), text
