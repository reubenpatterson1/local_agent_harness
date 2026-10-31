"""Tests for chained end frames (docs/superpowers/specs/2026-10-30-chained-end-frames-design.md,
Section 6: CT1-CT16 and CT29, with the plan's Review Focus pin 3): five camera moves join the
fixed list, words after "as the move completes" or "holding" no longer make a camera sentence
mixed (M1), double quotes in a writer's action text become apostrophes, the chained planner
writes an end frame for every beat (P22, P23, P24 and the plan reference), writer k is told the
frame it opens on and the frame it ends on, and its camera clause must land on the planned end
frame (N23).

Run from the workspace root: python3 -m pytest -q -p no:cacheprovider tests/test_chained_end_frames.py
Stdlib plus pytest. No test renders, reads the real HOME, or contacts a model server, a daemon,
ffmpeg or the Anthropic API: every model call goes to the fake bin/qwen-agent of a temp workspace
(story_engine_testutil.make_ws and script_agent), every ctx lives under tmp_path, and every test
runs under the autouse story_env fixture (a temporary HOME, character library and LoRA catalog).
"""

import base64
import copy
import glob
import hashlib
import importlib.machinery
import json
import os
import re
import shutil
import subprocess
import sys

import pytest

WS = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
sys.path.insert(0, WS)
sys.path.insert(0, os.path.join(WS, "tests"))

import story_engine_testutil as seu  # noqa: E402


def _load(name, rel):
    return importlib.machinery.SourceFileLoader(name, os.path.join(WS, rel)).load_module()


lib = _load("character_lib_for_chained_end_frames", "character_lib.py")
se = _load("story_engine_for_chained_end_frames", "story_engine.py")
story_manifest = _load("ltx_story_manifest_for_chained_end_frames",
                       os.path.join("bin", "ltx-story-manifest"))
ltx_movie = _load("ltx_movie_for_chained_end_frames", os.path.join("bin", "ltx-movie"))

# Captured at import, before any fixture sets HOME (CT29).
REAL_HOME = os.path.expanduser("~")


@pytest.fixture(autouse=True)
def story_env(monkeypatch, tmp_path):
    return seu.set_story_env(monkeypatch, tmp_path)


@pytest.fixture
def ws(tmp_path):
    return seu.make_ws(tmp_path)


# --- Test data (spec Section 6) ----------------------------------------------------------------

REF_NARRATIVE = ('At dawn the old fishmonger drags her empty herring crates to the shutter of the '
                 'market hall. At the zinc counter she says, "Forty years of mornings." After a '
                 'breath she says, "Not one more." She rests her head on her folded hands.')
END_FRAME = ("The courier stands at frame centre on the wet quay, facing the camera, seen from the "
             "waist up, beat %d.")
QUOTE_TEXT = 'The courier reads the "urgent" note and the “closed” sign.'
# A valid 1x1 PNG: bin/ltx-story-manifest only checks that each panel still opens.
PNG_1X1 = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA"
                           "60e6kgAAAABJRU5ErkJggg==")


def ref_ctx(ws, **kw):
    """The reference movie's ctx: chained, 3 panels of 145 frames, --speech-only, REF_NARRATIVE,
    no auto LoRA; keyword arguments replace fields."""
    fields = dict(mode="chained", panels=3, narration="speech", clip_seconds=145 / 24.0,
                  narrative=REF_NARRATIVE, auto_lora=False)
    fields.update(kw)
    return seu.make_ctx(se, ws, **fields)


def ef_plan(n, mode="chained"):
    """EF_PLAN(n): seu.plan_json(mode, n) with beat k's end_frame END_FRAME % k (20 words)."""
    raw = seu.plan_json(mode, n)
    for k, beat in enumerate(raw["beats"], start=1):
        beat["end_frame"] = END_FRAME % k
    return raw


def _normalized(ctx, raw):
    plan, shape = se.normalize_plan(ctx, raw)
    assert shape == []
    return plan


def _read_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _ronin_plan(ws, camera, **ctx_kw):
    """(ctx, plan) of a 1-beat chained plan whose cast c1 is "the ronin" and whose camera is
    camera."""
    ctx = seu.make_ctx(se, ws, panels=1, **ctx_kw)
    raw = seu.plan_json("chained", 1, cast=[{"id": "c1", "phrase": "the ronin",
                                             "descriptor": seu.DESC_R}])
    raw["beats"][0]["camera"] = camera
    return ctx, _normalized(ctx, raw)


# --- CT29: no server and no real HOME (spec Section 6 conventions) -----------------------------

def test_ct29_no_server_and_no_real_home(story_env, tmp_path):
    assert os.path.expanduser("~") == story_env["home"]
    assert os.path.expanduser("~") != REAL_HOME
    assert story_env["home"].startswith(str(tmp_path))
    assert os.environ["QWEN_AGENT_DAEMON_URL"].startswith("http://127.0.0.1:")
    assert "ANTHROPIC_API_KEY" not in os.environ


# --- CT1 (Task 1 part): the camera constants (CE1, CE2) ----------------------------------------

CAMERA_SENTENCES = (
    ("slow push-in", "The camera pushes in."),
    ("slow pull-back", "The camera pulls back."),
    ("tracking", "The camera tracks alongside the movement."),
    ("slow tracking left", "The camera tracks left alongside the movement."),
    ("slow tracking right", "The camera tracks right alongside the movement."),
    ("handheld", "The camera is handheld, with slight natural movement."),
    ("slow pan left", "The camera pans left."),
    ("slow pan right", "The camera pans right."),
    ("slow tilt up", "The camera tilts up."),
    ("slow tilt down", "The camera tilts down."),
    ("slow crane up", "The camera cranes up."),
    ("slow crane down", "The camera cranes down."),
    ("slow orbit", "The camera arcs around the subject in a partial orbit."),
    ("static", "The camera stays static."),
)
PLAN_CAMERA_KEYS = ("slow push-in", "slow pull-back", "slow tracking left", "slow tracking right",
                    "handheld", "slow pan left", "slow pan right", "slow tilt up",
                    "slow tilt down", "slow crane up", "slow crane down", "slow orbit", "static")
CAMERA_SPEAKING_SENTENCE = (" On a beat with a speaker, prefer slow push-in, slow pull-back, "
                            "slow tracking left, slow tracking right or handheld, and never use a "
                            "pan, a tilt, a crane or an orbit, which sweep the speaker's face out "
                            "of the frame.")
SPEAKING_CAMERAS = ("slow push-in", "slow pull-back", "tracking", "slow tracking left",
                    "slow tracking right", "handheld", "static")
TRACK_WORDS = ("track", "tracks", "tracking", "follow", "follows", "dolly", "dollies")
CAMERA_MOVE_WORDS = {
    "slow push-in": ("push in", "pushes in", "push-in", "dolly", "dollies", "zoom", "zooms"),
    "slow pull-back": ("pull back", "pulls back", "pull-back", "dolly", "dollies", "zoom",
                       "zooms"),
    "tracking": TRACK_WORDS,
    "slow tracking left": TRACK_WORDS,
    "slow tracking right": TRACK_WORDS,
    "handheld": ("handheld",),
    "slow pan left": ("pan", "pans"),
    "slow pan right": ("pan", "pans"),
    "slow tilt up": ("tilt", "tilts"),
    "slow tilt down": ("tilt", "tilts"),
    "slow crane up": ("crane", "cranes"),
    "slow crane down": ("crane", "cranes"),
    "slow orbit": ("orbit", "orbits"),
    "static": ("static", "still", "hold", "holds", "locked-off"),
}
NEW_WRITER_FORMS = {
    "slow tracking left": ("tracks left", "'The camera tracks left alongside <whom it follows> — "
                                         "as the move completes, <where the frame ends>.'"),
    "slow tracking right": ("tracks right", "'The camera tracks right alongside <whom it follows> "
                                            "— as the move completes, <where the frame ends>.'"),
    "slow crane up": ("cranes up", "'The camera cranes up — as the move completes, <what the "
                                   "frame ends on>.'"),
    "slow crane down": ("cranes down", "'The camera cranes down — as the move completes, <what "
                                       "the frame ends on>.'"),
    "slow orbit": ("arcs around the subject in a partial orbit", "'The camera arcs around <whom it "
                   "circles> in a partial orbit — as the move completes, <where the frame "
                   "ends>.'"),
}


def _form_sentence(form):
    """A CAMERA_WRITER_FORMS form as a sentence: its quotes off and every <...> part made "x"."""
    return re.sub(r"<[^<>]*>", "x", form.strip("'"))


def test_ct1a_the_camera_constants():
    assert se.CAMERA_SENTENCES == CAMERA_SENTENCES
    assert se.CAMERA_KEYS == tuple(key for key, _sentence in CAMERA_SENTENCES)
    assert se.PLAN_CAMERA_KEYS == PLAN_CAMERA_KEYS
    assert se.CAMERA_SPEAKING_SENTENCE == CAMERA_SPEAKING_SENTENCE
    assert se.SPEAKING_CAMERAS == SPEAKING_CAMERAS
    assert se.CAMERA_MOVE_WORDS == CAMERA_MOVE_WORDS
    for key, value in NEW_WRITER_FORMS.items():
        assert se.CAMERA_WRITER_FORMS[key] == value, key
    assert set(se.CAMERA_WRITER_FORMS) == set(se.CAMERA_KEYS) == set(se.CAMERA_MOVE_WORDS)
    for key, sentence in se.CAMERA_SENTENCES:
        for text in (sentence, _form_sentence(se.CAMERA_WRITER_FORMS[key][1])):
            assert lib._is_camera_sentence(text, ["the courier"]), (key, text)
            assert se._names_camera(text, key), (key, text)
            assert not se._mixed_camera(text), (key, text)
    for text in ([sentence for _key, sentence in CAMERA_SENTENCES] + [CAMERA_SPEAKING_SENTENCE]
                 + [move + " " + form for move, form in NEW_WRITER_FORMS.values()]):
        assert "slowly" not in text.lower(), text


# --- CT12: M1, the end clause is not camera language (CE2, CK4) --------------------------------

def test_ct12_a_standing_still_end_frame_survives_the_repair(ws):
    ctx, plan = _ronin_plan(ws, "slow push-in")
    phrases = se.cast_phrases(ctx, plan)
    text = ("The ronin runs to the wall. The camera pushes in — as the move completes, the ronin "
            "stands still at the right edge.")
    assert se.repair_action_text(ctx, plan, 1, text) == (text, [])
    assert se.camera_problem(lib, text, phrases, "slow push-in") is None
    sentence = "The camera pushes in — as the move completes, the ronin stands still at the right edge."
    assert se.camera_head(sentence) == "The camera pushes in — "
    assert se.end_clause(sentence) == "the ronin stands still at the right edge"
    assert (se.camera_head("The camera pushes in."), se.end_clause("The camera pushes in.")) == (
        "The camera pushes in.", "")
    assert not se._mixed_camera(sentence) and se._names_camera(sentence, "slow push-in")


def test_ct12_stays_still_and_pushes_in_is_still_mixed(ws):
    ctx, plan = _ronin_plan(ws, "slow push-in")
    phrases = se.cast_phrases(ctx, plan)
    mixed = "The ronin runs to the wall. The camera stays still and pushes in."
    detail = se.camera_problem(lib, mixed, phrases, "slow push-in")
    assert "has the camera both stay still and move" in detail
    assert se.repair_action_text(ctx, plan, 1, mixed) == (
        "The ronin runs to the wall.",
        [se.REPAIR_NOTE % (1, "N20", "camera direction", "Motion",
                           "'The camera stays still and pushes in.'")])


def test_ct12_static_holding_and_the_head_rule(ws):
    ctx, plan = _ronin_plan(ws, "static")
    phrases = se.cast_phrases(ctx, plan)
    held = ("The ronin runs to the wall. The camera stays static, holding the ronin as he stands "
            "still at the right edge.")
    assert se.camera_problem(lib, held, phrases, "static") is None
    assert se.repair_action_text(ctx, plan, 1, held) == (held, [])
    pushed = ("The ronin runs to the wall. The camera pushes in — as the move completes, she holds "
              "still at the right edge.")
    assert "does not move the camera the planned way" in se.camera_problem(lib, pushed, phrases,
                                                                           "static")


# --- CT13: quotes reserved for spoken lines (CE10, CK5) ----------------------------------------

def _quote_parts(mode, n=2):
    """seu.panel_json parts for n panels, the action text of every panel QUOTE_TEXT plus the usual
    words, and panel 2 saying "Go now." when it speaks."""
    key = "prompt" if mode == "no_stills" else "motion"
    parts = []
    for k in range(1, n + 1):
        part = seu.panel_json(mode, k)
        part[key] = QUOTE_TEXT + " " + part[key]
        parts.append(part)
    parts[1]["dialogue"] = "Go now."
    return parts


def _speaking(ctx, n=2):
    raw = seu.plan_json(ctx.mode, n)
    raw["beats"][1]["speaker"] = "c1"
    return _normalized(ctx, raw)


def test_ct13_writer_double_quotes_become_apostrophes(ws, tmp_path):
    for mode in ("chained", "shots", "no_stills"):
        ctx = seu.make_ctx(se, ws, mode=mode, panels=2, story_id="q-" + mode.replace("_", "-"))
        plan = _speaking(ctx)
        parts = _quote_parts(mode)
        label = "Prompt" if mode == "no_stills" else "Motion"
        for k in (1, 2):
            fields = dict(se.panel_fields(ctx, plan, parts, k))
            assert "'urgent'" in fields[label] and "'closed'" in fields[label], (mode, k)
            assert not any(q in fields[label] for q in ('"', "“", "”")), (mode, k)
        assert dict(se.panel_fields(ctx, plan, parts, 2))["Dialogue"] == "the courier: Go now."
        assert se.reserve_quotes(QUOTE_TEXT) == "The courier reads the 'urgent' note and the 'closed' sign."
    ctx = seu.make_ctx(se, ws, mode="chained", panels=2, story_id="q-checks")
    plan = _speaking(ctx)
    parts = _quote_parts("chained")
    text = se.assemble(ctx, plan, parts)
    path = os.path.join(str(tmp_path), "q-checks.md")
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    _hard, advisory = se.panel_checks(ctx, plan, parts, text, path)
    assert "panel 1: N7 dialogue and text: Motion: contains a double quote" in advisory


def test_ct13_the_manifest_keeps_only_the_spoken_line_quoted(ws, tmp_path, monkeypatch):
    ctx = seu.make_ctx(se, ws, mode="chained", panels=2, story_id="q-story")
    plan = _speaking(ctx)
    text = se.assemble(ctx, plan, _quote_parts("chained"))
    mws = tmp_path / "mws"
    mws.mkdir()
    for name in ("character_lib.py", "lora_catalog.py"):
        os.symlink(os.path.join(WS, name), str(mws / name))
    monkeypatch.setattr(story_manifest, "WS", str(mws))
    story_dir = mws / "generated" / "stories" / "q-story"
    story_dir.mkdir(parents=True)
    (story_dir / "plan.json").write_text(json.dumps(plan), encoding="utf-8")
    story_md = tmp_path / "q-story.md"
    story_md.write_text(text, encoding="utf-8")
    image = tmp_path / "q-story_01.png"
    image.write_bytes(PNG_1X1)
    argv = ["--story-id", "q-story", "--prompts-md", str(story_md), "--chain", "--image",
            str(image), "--fps", "24", "--target-seconds", repr(145 * 2 / 24.0), "--min-frames",
            "145", "--max-frames", "145", "--force"]
    assert story_manifest.main(argv) == 0
    prompts = [p["motion_prompt"] for p in _read_json(str(story_dir / "manifest.json"))["panels"]]
    assert [p.count('"') for p in prompts] == [0, 2]
    assert 'The courier says, "Go now."' in prompts[1]
    assert not any(q in p for p in prompts for q in ("“", "”"))


def test_ct13_the_fixture_parts_assemble_with_no_double_quote(ws):
    found = []
    for path in sorted(glob.glob(os.path.join(WS, "tests", "fixtures", "**", "parts.json"),
                                 recursive=True)):
        sibling = os.path.join(os.path.dirname(path), "plan.json")
        if not os.path.isfile(sibling):
            continue
        plan = _read_json(sibling)
        if plan.get("mode") not in ("chained", "shots"):
            continue
        found.append(os.path.basename(os.path.dirname(path)))
        parts = [dict((key, value) for key, value in p.items() if key != "index")
                 for p in _read_json(path)["panels"]]
        ctx = seu.make_ctx(se, ws, mode=plan["mode"], panels=len(plan["beats"]),
                           narration="speech", narrative=plan["narrative"], goal=plan["goal"],
                           story_id=found[-1])
        motions = [line for line in se.assemble(ctx, plan, parts).split("\n")
                   if line.startswith("Motion: ")]
        assert motions and not any(q in m for m in motions for q in ('"', "“", "”")), found[-1]
    assert found == ["hockey-1x241-f", "hockey-2x145-f"]


# --- CT1 (Task 2 part): the planner constants (CE4-CE7) ----------------------------------------

END_FRAME_RULE = (" end_frame is one sentence of 8 to 30 words, in the present tense, of the "
                  "frame the beat ends on: who or what is in frame, where each one is (left, "
                  "centre or right; foreground or background), which way they face and how tight "
                  "the shot is. It never names a camera move, the lighting, a colour or a style, "
                  "has no spoken words and no double quotes, and names only characters in the "
                  "beat's cast. Beat k's end frame is exactly where beat k+1 begins; write beat "
                  "k+1's action so it starts from that composition. The last beat's end frame "
                  "closes the story.")
PLAN_REFERENCE_INTRO = ("FORMAT REFERENCE ONLY — never reuse its people, places, objects or "
                        "words. This is the complete plan of a three-beat movie made as one "
                        "continuous take, a different story from this one.%s It shows the format "
                        "of every plan: each beat's end_frame says exactly where the beat ends, "
                        "the next beat's action starts from that end frame, and the last end "
                        "frame closes the story.\n")
PLAN_REFERENCE_LINES_CLAUSE = (' Its narrative quoted two spoken lines: 1 "Forty years of '
                               'mornings." and 2 "Not one more."')
PLAN_REFERENCE_KEY_WORDS = frozenset(("fishmonger", "fishmongers", "herring", "herrings",
                                      "crates", "zinc", "shutter", "cloth"))
P22_MISSING = ("beat %d: P22 end frame: end_frame is missing or empty; write one sentence of 8 "
               "to 30 words of the frame this beat ends on: who or what is in frame, where (left, "
               "centre or right; foreground or background), which way they face and how tight "
               "the shot is")
P22_LENGTH = "beat %d: P22 end frame: end_frame is %d words; write one sentence of 8 to 30 words"
P24_MESSAGE = ("plan: P24 reference copy: %s copies the plan reference (%s); write only this "
               "movie's own people, places, objects and words")
END_FRAMES_DROPPED = ("Warning: end frames dropped after %d attempts; this story has no seam "
                      "report")


def test_ct1b_the_planner_constants():
    assert se.END_FRAME_RULE == END_FRAME_RULE
    assert se.PLAN_REFERENCE_INTRO == PLAN_REFERENCE_INTRO
    assert se.PLAN_REFERENCE_LINES_CLAUSE == PLAN_REFERENCE_LINES_CLAUSE
    assert se.PLAN_REFERENCE_KEY_WORDS == PLAN_REFERENCE_KEY_WORDS
    assert se.END_FRAME_WORDS == (8, 30)
    assert se.P22_MISSING == P22_MISSING
    assert se.P22_LENGTH == P22_LENGTH
    assert se.P24_MESSAGE == P24_MESSAGE
    assert se.END_FRAMES_DROPPED == END_FRAMES_DROPPED
    for text in (END_FRAME_RULE, PLAN_REFERENCE_INTRO, PLAN_REFERENCE_LINES_CLAUSE, P22_MISSING,
                 P22_LENGTH, P24_MESSAGE, END_FRAMES_DROPPED, se.plan_reference(True),
                 se.plan_reference(False)):
        assert "slowly" not in text.lower(), text


# --- CT2: the plan reference (CE5) ---------------------------------------------------------------

def _sha(text):
    return (hashlib.sha256(text.encode("utf-8")).hexdigest(), len(text), len(text.split()))


def test_ct2_the_plan_reference_is_pinned():
    assert _sha(se._plan_reference_json(se.PLAN_REFERENCE_PLAN)) == (
        "e3329d43c6049b5d7e727531d37cd14b0a19fda8d3055f79c9298e5280123a53", 2103, 322)
    assert _sha(se.plan_reference(True)) == (
        "f01c845181417fa7a3d77f112786e52efb05c029716c141e3999c6f2c1a87fb3", 2562, 403)
    assert _sha(se.plan_reference(False)) == (
        "571591dffb3a354b21569a171420b6e762268787854d9b1c22dbd496482c1eff", 2429, 380)
    assert len(se.PLAN_REFERENCE_SIX_GRAMS) == 68
    assert json.loads(se.plan_reference(True).split("\n", 1)[1]) == se.PLAN_REFERENCE_PLAN
    no_lines = copy.deepcopy(se.PLAN_REFERENCE_PLAN)
    for beat in no_lines["beats"]:
        del beat["lines"]
    assert json.loads(se.plan_reference(False).split("\n", 1)[1]) == no_lines
    assert se.plan_reference(True).startswith(PLAN_REFERENCE_INTRO % PLAN_REFERENCE_LINES_CLAUSE)
    assert se.plan_reference(False).startswith(PLAN_REFERENCE_INTRO % "")
    for text in (se.plan_reference(True), se.plan_reference(False)):
        assert "@@" not in text and text.endswith("}\n\n")


def test_ct2_the_reference_plan_passes_the_plan_checks(ws):
    for narration in ("speech", True):
        ctx = ref_ctx(ws, narration=narration)
        plan = _normalized(ctx, copy.deepcopy(se.PLAN_REFERENCE_PLAN))
        hard, advisory = se.plan_checks(ctx, plan)
        assert hard == [], narration
        assert [m for m in advisory if re.search(r": P(?:8|22|23|24) ", m)] == [], narration
        assert se.plan_end_frame_problems(ctx, plan) == []
        assert se.line_assignment_problems(plan) == []
        assert [b["end_frame"] for b in plan["beats"]] == [
            b["end_frame"] for b in se.PLAN_REFERENCE_PLAN["beats"]]
    ctx = ref_ctx(ws, narrative="A courier delivers a letter.")
    plan = _normalized(ctx, copy.deepcopy(se.PLAN_REFERENCE_PLAN))
    problems = se.plan_copy_problems(ctx, plan)
    assert problems
    assert all(m.startswith("plan: P24 reference copy: ") for m in problems)
    assert problems[0].startswith("plan: P24 reference copy: the logline copies the plan reference (")


# --- CT3: the plan prompt (CE4) -------------------------------------------------------------------

LINES_NARRATIVE = ('At dusk Kyra climbs the stone steps of a mountain temple, and the ronin walks '
                   'one step behind her. Near the top Kyra turns and says, "We reach the gate '
                   'before dark." They pass under the gate together, and Kyra says, "Stay close '
                   'to me."')
CAMERA_LIST = ("camera is exactly one of: slow push-in, slow pull-back, slow tracking left, slow "
               "tracking right, handheld, slow pan left, slow pan right, slow tilt up, slow tilt "
               "down, slow crane up, slow crane down, slow orbit, static.")
LINES_RULE_END = "never add a beat only to separate lines that fit together."


def _plan_prompt(ws, **kw):
    """The plan prompt of make_ctx(**kw), with no catalog and no pins."""
    return se.build_plan_prompt(seu.make_ctx(se, ws, **kw), [], [])


def test_ct3_the_chained_plan_prompt(ws):
    lined = _plan_prompt(ws, narrative=LINES_NARRATIVE, narration="speech")
    assert ("with the keys index, arc, action, shot, camera, location, cast, speaker, lines and "
            "end_frame.") in lined
    assert LINES_RULE_END + se.END_FRAME_RULE + "\n" in lined
    assert CAMERA_LIST in lined
    assert lined.endswith(se.plan_reference(True) + se.NO_TOOL_SENTENCE)
    plain = _plan_prompt(ws)
    assert "with the keys index, arc, action, shot, camera, location, cast, speaker and end_frame." in plain
    assert se.END_FRAME_RULE + "\nloras: " in plain
    assert plain.endswith(se.MODE_RULES["chained"] + se.plan_reference(False) + se.NO_TOOL_SENTENCE)
    for prompt in (lined, plain):
        assert prompt.count("FORMAT REFERENCE ONLY") == 1
    silent = _plan_prompt(ws, narration=False)
    assert se.END_FRAME_RULE in silent
    assert "FORMAT REFERENCE ONLY" not in silent
    assert silent.endswith(se.MODE_RULES["chained"] + se.NO_TOOL_SENTENCE)
    for prompt, lines in ((lined, True), (plain, False), (silent, None)):
        assert "@@" not in prompt
        assert "8K" not in prompt
        rest = prompt.replace(se.plan_reference(lines), "") if lines is not None else prompt
        assert "{" not in rest and "}" not in rest


def test_ct3_shots_and_no_stills_plan_prompts(ws):
    for mode in ("shots", "no_stills"):
        for kw in ({}, {"narrative": LINES_NARRATIVE, "narration": "speech"}, {"narration": False}):
            prompt = _plan_prompt(ws, mode=mode, **kw)
            assert "end_frame" not in prompt, (mode, kw)
            assert "FORMAT REFERENCE ONLY" not in prompt, (mode, kw)
            assert CAMERA_LIST in prompt, (mode, kw)
            assert "@@" not in prompt and "{" not in prompt and "}" not in prompt, (mode, kw)


# --- CT4: normalize_plan keeps the end frame (CE3) ------------------------------------------------

def test_ct4_normalize_plan_keeps_a_chained_end_frame(ws):
    ctx = seu.make_ctx(se, ws)
    keys = list(_normalized(ctx, seu.plan_json("chained", 3)))
    raw = seu.plan_json("chained", 3)
    raw["beats"][0]["end_frame"] = "  The courier  stands at frame centre,\n facing left.  "
    plan = _normalized(ctx, raw)
    assert plan["beats"][0]["end_frame"] == "The courier stands at frame centre, facing left."
    assert list(plan) == keys
    assert "end_frame" not in plan["beats"][1]
    for value in ("", "   ", None, 7, ["The courier stands."], {"text": "x"}):
        raw = seu.plan_json("chained", 3)
        raw["beats"][0]["end_frame"] = value
        assert "end_frame" not in _normalized(ctx, raw)["beats"][0], value
    for mode in ("shots", "no_stills"):
        other = seu.make_ctx(se, ws, mode=mode, story_id="n-" + mode.replace("_", "-"))
        plan = _normalized(other, ef_plan(3, mode))
        assert not any("end_frame" in b for b in plan["beats"]), mode
        assert list(plan) == list(_normalized(other, seu.plan_json(mode, 3))), mode


# --- CT5: P22 (CE6) ---------------------------------------------------------------------------------

def _words_frame(n):
    return " ".join(["The courier stands"] + ["still"] * (n - 3)) + "."


def test_ct5_p22_end_frame_presence_and_length(ws):
    ctx = seu.make_ctx(se, ws)
    assert se.plan_end_frame_problems(ctx, _normalized(ctx, ef_plan(3))) == []
    raw = ef_plan(3)
    del raw["beats"][1]["end_frame"]
    assert se.plan_end_frame_problems(ctx, _normalized(ctx, raw)) == [P22_MISSING % 2]
    for k, words, expected in ((1, 7, [P22_LENGTH % (1, 7)]), (3, 31, [P22_LENGTH % (3, 31)]),
                               (2, 8, []), (2, 30, [])):
        raw = ef_plan(3)
        raw["beats"][k - 1]["end_frame"] = _words_frame(words)
        assert se.plan_end_frame_problems(ctx, _normalized(ctx, raw)) == expected, words
    shots = seu.make_ctx(se, ws, mode="shots", story_id="p22-shots")
    assert se.plan_end_frame_problems(shots, _normalized(shots, seu.plan_json("shots", 3))) == []
    assert se.plan_end_frame_problems(ctx, _normalized(ctx, seu.plan_json("chained", 2))) == [
        P22_MISSING % 1, P22_MISSING % 2]


# --- CT6: P23 (CE6) ---------------------------------------------------------------------------------

P23 = "beat 1: P23 end frame content: "


def _p23(ws, text, cast=("c1",)):
    ctx = seu.make_ctx(se, ws, panels=1)
    raw = seu.plan_json("chained", 1)
    raw["beats"][0]["cast"] = list(cast)
    raw["beats"][0]["end_frame"] = text
    plan = _normalized(ctx, raw)
    found = se.end_frame_advisories(ctx, lib, plan)
    assert [m for m in se.plan_checks(ctx, plan)[1] if " P23 " in m] == found
    return found


def test_ct6_p23_end_frame_content_rows(ws):
    assert _p23(ws, "The courier stands beside the old monk at frame centre, facing the camera.") == [
        P23 + "names 'the old monk', who is not in beat 1's cast"]
    assert _p23(ws, "The camera pushes in on the courier at frame centre facing left.") == [
        P23 + "says 'camera pushes'; an end frame describes the frame, never a camera move"]
    assert _p23(ws, "The courier pans the quay from the right edge, facing left.") == [
        P23 + "says 'pans'; an end frame describes the frame, never a camera move"]
    assert _p23(ws, "The courier stands at frame centre, lit by a lamp, facing left.") == [
        P23 + "says 'lit'; an end frame never describes appearance, clothing, setting, lighting, "
        "colour or style"]
    assert _p23(ws, "The courier says goodbye at frame centre, facing left.") == [
        P23 + "says 'says'; an end frame has no spoken words"]
    assert _p23(ws, 'The courier stands under the "closed" sign at frame centre, facing left.') == [
        P23 + "contains a double quote; double quotes are kept for spoken lines"]
    assert _p23(ws, "The courier stands still at frame centre, facing left, holding the sealed "
                    "letter, seen from the waist up.") == []
    assert _p23(ws, "The old monk follows the courier along the quay, both facing left at frame "
                    "centre.", cast=("c1", "c2")) == []
    ctx = ref_ctx(ws)
    assert se.end_frame_advisories(ctx, lib, _normalized(ctx, copy.deepcopy(se.PLAN_REFERENCE_PLAN))) == []
    shots = seu.make_ctx(se, ws, mode="shots", story_id="p23-shots")
    assert se.end_frame_advisories(shots, lib, _normalized(shots, seu.plan_json("shots", 1))) == []


# --- CT7: P24 (CE6) ---------------------------------------------------------------------------------

HERRING_ACTION = "The courier drags a tall stack of empty herring crates past the boats."
ZINC_FRAME = "The courier leans on the zinc counter, facing the camera, seen from the waist up."
FISHER = "a weathered man with a grey beard and short white hair wearing an oilskin coat that smells of herring"


def _p24_plan(ctx, action=None, frame=None):
    raw = ef_plan(3)
    if action is not None:
        raw["beats"][0]["action"] = action
    if frame is not None:
        raw["beats"][1]["end_frame"] = frame
    return _normalized(ctx, raw)


def test_ct7_p24_reference_copy_rows(ws, story_env):
    ctx = seu.make_ctx(se, ws)
    assert se.plan_copy_problems(ctx, _p24_plan(ctx)) == []
    assert se.plan_copy_problems(ctx, _p24_plan(ctx, action=HERRING_ACTION)) == [
        P24_MESSAGE % ("beat 1's action", "'herring', 'a tall stack of empty herring', 'tall stack "
                       "of empty herring crates'")]
    assert se.plan_copy_problems(ctx, _p24_plan(ctx, frame=ZINC_FRAME)) == [
        P24_MESSAGE % ("beat 2's end frame", "'zinc'")]
    assert se.plan_copy_problems(ctx, _p24_plan(ctx, frame=ZINC_FRAME), end_frames=False) == []
    zinc = seu.make_ctx(se, ws, narrative="A courier leans on a zinc counter in the rain.",
                        story_id="p24-zinc")
    assert se.plan_copy_problems(zinc, _p24_plan(zinc, frame=ZINC_FRAME)) == []
    basket = "The courier carries a herring basket past the boats."
    assert se.plan_copy_problems(ctx, _p24_plan(ctx, action=basket)) == [
        P24_MESSAGE % ("beat 1's action", "'herring'")]
    seu.make_character(story_env["lib"], "fisher", "fishermn", "the old fisherman", "man", FISHER)
    pinned = seu.make_ctx(se, ws, members=lib.resolve_cast([(None, "fisher")]), story_id="p24-pin")
    assert se.plan_copy_problems(pinned, _p24_plan(pinned, action=basket)) == []
    assert se.plan_copy_problems(ctx, _p24_plan(
        ctx, action="The courier turns back into the hall and walks to the gate.")) == []
    for other in (seu.make_ctx(se, ws, mode="shots", story_id="p24-shots"),
                  seu.make_ctx(se, ws, narration=False, story_id="p24-silent")):
        assert se.plan_copy_problems(other, _p24_plan(other, action=HERRING_ACTION)) == []


# --- CT8: the plan retry, end to end (CE7, CK1) -----------------------------------------------------

def _panel_replies(mode, n):
    return dict((str(k), [seu.answer(seu.panel_json(mode, k))]) for k in range(1, n + 1))


def _e2e(ws, tmp_path, monkeypatch, plans, n=3, panel=None, **ctx_kw):
    """(rc, agent log, saved plan.json or None, ctx) of se.run with the scripted plan replies
    plans and panel replies panel (default: one seu.panel_json reply per panel)."""
    log = seu.script_agent(monkeypatch, tmp_path, plan=[seu.answer(p) for p in plans],
                           panel=_panel_replies("chained", n) if panel is None else panel)
    ctx = seu.make_ctx(se, ws, panels=ctx_kw.pop("panels", n), **ctx_kw)
    rc, _advisories = se.run(ctx)
    path = os.path.join(ctx.story_dir, "plan.json")
    return rc, seu.agent_log(log), (_read_json(path) if os.path.exists(path) else None), ctx


def _assert_p22_clean(plan):
    """CK1: a saved plan either has every beat's end frame, each passing P22, or none."""
    frames = [b.get("end_frame") for b in plan["beats"]]
    if any(frames):
        assert all(se.END_FRAME_WORDS[0] <= len(f.split()) <= se.END_FRAME_WORDS[1]
                   for f in frames), frames


def test_ct8_a_plan_without_end_frames_is_asked_again(ws, tmp_path, monkeypatch, capsys):
    rc, log, plan, _ctx = _e2e(ws, tmp_path, monkeypatch, [seu.plan_json("chained", 3), ef_plan(3)])
    out = capsys.readouterr().out
    assert rc == 0
    assert [c["stage"] for c in log][:3] == ["plan", "plan", "panel"]
    assert ("YOUR PREVIOUS REPLY WAS REJECTED. Problems:\n- " + P22_MISSING % 1 + "\n") in log[1]["argv"][-1]
    assert [b["end_frame"] for b in plan["beats"]] == [END_FRAME % k for k in (1, 2, 3)]
    assert "end frames dropped" not in out
    _assert_p22_clean(plan)


def test_ct8_two_plans_without_end_frames_drop_them(ws, tmp_path, monkeypatch, capsys):
    rc, log, plan, ctx = _e2e(ws, tmp_path, monkeypatch, [seu.plan_json("chained", 3)] * 2)
    out = capsys.readouterr().out
    assert rc == 0
    assert [c["stage"] for c in log][:3] == ["plan", "plan", "panel"]
    assert END_FRAMES_DROPPED % 2 + "\n" in out
    assert not any("end_frame" in b for b in plan["beats"])
    checks = _read_json(os.path.join(ctx.story_dir, "story_checks.json"))
    assert not [m for m in checks["advisory"] if " P22 " in m["message"]]
    _assert_p22_clean(plan)


def test_ct8_a_copied_action_after_the_last_call_is_fatal(ws, tmp_path, monkeypatch, capsys):
    raw = ef_plan(3)
    raw["beats"][0]["action"] = HERRING_ACTION
    rc, log, plan, _ctx = _e2e(ws, tmp_path, monkeypatch, [raw, raw])
    err = capsys.readouterr().err
    assert rc == 1
    assert [c["stage"] for c in log] == ["plan", "plan"]
    assert "  - plan: P24 reference copy: beat 1's action copies the plan reference (" in err
    assert plan is None


def test_ct8_a_copied_end_frame_after_the_last_call_is_dropped(ws, tmp_path, monkeypatch, capsys):
    raw = ef_plan(3)
    raw["beats"][1]["end_frame"] = ZINC_FRAME
    rc, log, plan, _ctx = _e2e(ws, tmp_path, monkeypatch, [raw, raw])
    out = capsys.readouterr().out
    assert rc == 0
    assert END_FRAMES_DROPPED % 2 + "\n" in out
    assert not any("end_frame" in b for b in plan["beats"])
    _assert_p22_clean(plan)


def test_ct8_a_plan_with_end_frames_makes_one_call(ws, tmp_path, monkeypatch, capsys):
    rc, log, plan, _ctx = _e2e(ws, tmp_path, monkeypatch, [ef_plan(3)])
    out = capsys.readouterr().out
    assert rc == 0
    assert [c["stage"] for c in log].count("plan") == 1
    assert "end frames dropped" not in out
    assert [b["end_frame"] for b in plan["beats"]] == [END_FRAME % k for k in (1, 2, 3)]
    _assert_p22_clean(plan)


def test_ct8_a_fatal_call_2_falls_back_to_a_usable_call_1(ws, tmp_path, monkeypatch, capsys):
    bad = ef_plan(3)
    bad["beats"][0]["location"] = "l9"
    rc, log, plan, _ctx = _e2e(ws, tmp_path, monkeypatch, [seu.plan_json("chained", 3), bad])
    captured = capsys.readouterr()
    assert rc == 0
    assert [c["stage"] for c in log][:3] == ["plan", "plan", "panel"]
    assert "did not return a usable plan" not in captured.err
    assert END_FRAMES_DROPPED % 2 + "\n" in captured.out
    assert [b["location"] for b in plan["beats"]] == ["l1", "l1", "l1"]
    assert not any("end_frame" in b for b in plan["beats"])
    _assert_p22_clean(plan)


def test_ct8_a_timeout_before_call_2_keeps_a_usable_call_1(ws, tmp_path, monkeypatch, capsys):
    checks = []

    def expired(self):
        checks.append(1)
        return len(checks) == 2

    monkeypatch.setattr(se._Run, "expired", expired)
    rc, log, plan, _ctx = _e2e(ws, tmp_path, monkeypatch, [seu.plan_json("chained", 3), ef_plan(3)])
    out = capsys.readouterr().out
    assert rc == 0
    assert [c["stage"] for c in log][:2] == ["plan", "panel"]
    assert END_FRAMES_DROPPED % 1 + "\n" in out
    assert not any("end_frame" in b for b in plan["beats"])
    _assert_p22_clean(plan)


# --- CT16: the soft panel count (CE7; [SPC]) -------------------------------------------------------

def test_ct16_an_added_beat_needs_its_own_end_frame(ws, tmp_path, monkeypatch, capsys):
    four = ef_plan(4)
    del four["beats"][3]["end_frame"]
    rc, log, plan, _ctx = _e2e(ws, tmp_path, monkeypatch, [four, ef_plan(4)], n=4, panels=3)
    assert rc == 0
    assert [c["stage"] for c in log][:2] == ["plan", "plan"]
    assert "YOUR PREVIOUS REPLY WAS REJECTED. Problems:\n- " + P22_MISSING % 4 + "\n" in log[1]["argv"][-1]
    assert len(plan["beats"]) == 4 and all(b.get("end_frame") for b in plan["beats"])
    rc, log, plan, _ctx = _e2e(ws, tmp_path, monkeypatch, [ef_plan(4)], n=4, panels=3,
                               story_id="s2")
    assert rc == 0
    assert [c["stage"] for c in log].count("plan") == 1
    assert len(plan["beats"]) == 4
    _assert_p22_clean(plan)


# --- CT1 (Task 3 part): the N23 constants and check ids (CE9, CE12) ------------------------------

END_FRAME_STOP_WORDS = frozenset("""
    a an the and or but nor of to in on at by for from with without into onto off over under up
    down out about across along around through toward towards behind beside between near past
    against as is are be being it its he she they him her them his hers their theirs this that
    these those there here who whom which what while where when one each both all every
    some""".split())
GENERATION_CHECKS = ("N1", "N2", "N3", "N4", "N5", "N6", "N7", "N8", "N9", "N10", "N11", "N12",
                     "N14", "N15", "N16", "N17", "N18", "T1", "T2", "T3", "N20", "N21", "N22",
                     "N23", "Q1", "N19")
RECHECK_IDS = ("N1", "N2", "N3", "N4", "N7", "N8", "N9", "N10", "N11", "N12", "N14", "N15", "N16",
               "N17", "N18", "T1", "T2", "T3", "N23", "Q1", "N19")


def test_ct1c_the_n23_constants_and_check_ids():
    assert se.END_FRAME_STOP_WORDS == END_FRAME_STOP_WORDS
    assert se.GENERATION_CHECKS == GENERATION_CHECKS
    assert se.GENERATION_CHECKS[16:20] == ("N18", "T1", "T2", "T3")
    assert se.GENERATION_CHECKS[-2:] == ("Q1", "N19") and se.GENERATION_CHECKS[-1] == "N19"
    assert se.RECHECK_IDS == RECHECK_IDS
    assert se.RECHECK_IDS[14:18] == ("N18", "T1", "T2", "T3")
    assert se.RECHECK_IDS[-2:] == ("Q1", "N19")
    assert se.FORMAT_IDS == ("N7", "N20", "N21", "N22")
    assert se.PLAN_FREE_IDS == ("N1", "N7", "N8", "N9", "N10", "N11", "N15")


# --- CT10: N23 detection (CE9, CK2) ---------------------------------------------------------------

E2 = END_FRAME % 2
E2_QUOTED = "'" + E2 + "'"
REF_MOTIONS = (
    "The old fishmonger drags a tall stack of empty herring crates across the wet concrete of the "
    "market hall toward the half-open shutter at real-time speed, her heavy steps splashing "
    "through shallow puddles that hold the first glow from the harbour doors. The camera tracks "
    "right alongside her — as the move completes, the old fishmonger stands beside the half-open "
    "shutter at frame centre, facing left toward the hall, seen from the knees up, the empty "
    "crates at her feet.",
    "The old fishmonger turns back from the shutter and walks to the zinc counter at real-time "
    "speed, laying her folded cloth beside the empty ice trays and lifting her face to the "
    "camera. The old fishmonger presses both palms flat on the folded cloth, her shoulders "
    "sinking. The camera pushes in — as the move completes, the old fishmonger stands behind the "
    "zinc counter at frame centre, facing forward, her face filling the frame from chin to brow. "
    "The old fishmonger faces the camera.",
    "The old fishmonger lowers her forehead onto her folded hands on the cold zinc counter at "
    "real-time speed, her breath fogging the metal as a thin trickle of meltwater runs past her "
    "knuckles and drips to the wet floor. The camera stays static, holding the old fishmonger as "
    "she rests her forehead on her folded hands at frame centre, eyes closed, her head and hands "
    "filling the frame.",
)


def _detail(ws, camera, plan=None):
    ctx = seu.make_ctx(se, ws)
    plan = plan or _normalized(ctx, ef_plan(3))
    return se.end_frame_detail(lib, plan, 2, "The courier runs. " + camera, ["the courier"])


def test_ct10_n23_detection_rows(ws):
    assert _detail(ws, "The camera tracks the movement.") == (
        "has no camera sentence whose words after 'as the move completes,' (or after 'holding' "
        "for a static camera) describe the planned end frame " + E2_QUOTED)
    assert _detail(ws, "The camera tracks him — as the move completes, he stands at frame centre "
                       "on the wet quay.") == (
        "the camera sentence ends 'he stands at frame centre on the wet quay', which does not "
        "name 'the courier', whom the planned end frame " + E2_QUOTED + " names")
    assert _detail(ws, "The camera tracks him — as the move completes, the courier waits by a "
                       "lamp.") == (
        "the camera sentence ends 'the courier waits by a lamp', which shares 0 of the 11 content "
        "words of the planned end frame " + E2_QUOTED + "; it needs at least 6")
    assert _detail(ws, "The camera tracks him — as the move completes, the courier stands at frame "
                       "centre on the wet quay, facing left.") is None
    assert _detail(ws, "The camera tracks him — as the move completes, the courier stands at frame "
                       "centre on the wet quay.") == (
        "the camera sentence ends 'the courier stands at frame centre on the wet quay', which "
        "shares 5 of the 11 content words of the planned end frame " + E2_QUOTED + "; it needs "
        "at least 6")
    assert _detail(ws, "The camera stays static, holding the courier at frame centre on the wet "
                       "quay, facing the camera.") is None
    ctx = seu.make_ctx(se, ws)
    raw = ef_plan(3)
    del raw["beats"][1]["end_frame"]
    assert _detail(ws, "The camera tracks the movement.", plan=_normalized(ctx, raw)) is None
    assert se.end_frame_landing_problems(ctx, _normalized(ctx, raw), seu.panel_json("chained", 2),
                                         2) == []
    for mode in ("shots", "no_stills"):
        other = seu.make_ctx(se, ws, mode=mode, story_id="n23-" + mode.replace("_", "-"))
        plan = _normalized(other, seu.plan_json(mode, 3))
        plan["beats"][1]["end_frame"] = E2
        assert se.end_frame_landing_problems(other, plan, seu.panel_json(mode, 2), 2) == [], mode
    mentions = se._mentions(_normalized(ctx, ef_plan(3))["cast"])
    assert sorted(se.end_frame_words(E2, set(w for _c, ws_ in mentions for w in ws_))) == [
        "2", "beat", "camera", "centre", "facing", "frame", "quay", "seen", "stands", "waist", "wet"]
    for k, motion in enumerate(REF_MOTIONS, start=1):
        assert se.end_frame_detail(lib, se.PLAN_REFERENCE_PLAN, k, motion,
                                   ["the old fishmonger"]) is None, k


def test_review_focus_3_curly_apostrophes_and_capitals_still_land(ws):
    ctx = seu.make_ctx(se, ws, panels=1)
    raw = seu.plan_json("chained", 1)
    raw["beats"][0]["end_frame"] = ("The courier's bicycle leans against the harbour wall at frame "
                                    "centre, the courier beside it facing left.")
    plan = _normalized(ctx, raw)
    text = ("The courier runs. The camera tracks him — as the move completes, THE COURIER’S "
            "bicycle leans against the Harbour Wall at frame centre, the courier beside it facing "
            "left!")
    assert se.end_frame_detail(lib, plan, 1, text, ["the courier"]) is None
    assert se.end_clause("The camera tracks him — as the move completes, THE COURIER’S bicycle "
                         "leans.") == "THE COURIER’S bicycle leans"


# --- CT11: N23 in round 0, end to end (CE9, CK2) -------------------------------------------------

def _clause(end_frame):
    """end_frame with a lower-case first letter and no full stop."""
    return end_frame[:1].lower() + end_frame[1:].rstrip(".")


def _miss(k):
    return seu.panel_json("chained", k)


def _land(k):
    """Panel k of EF_PLAN(2) (1 static, 2 tracking) with a camera sentence that lands."""
    part = seu.panel_json("chained", k)
    if k == 1:
        part["motion"] += " The camera stays static, holding " + _clause(END_FRAME % 1) + "."
    else:
        part["motion"] += (" The camera tracks the courier — as the move completes, "
                           + _clause(END_FRAME % 2) + ".")
    return part


def _ct11(ws, tmp_path, monkeypatch, panel1, panel2, story_id="s1"):
    panel = {"1": [p if "answer" in p else seu.answer(p) for p in panel1],
             "2": [seu.answer(p) for p in panel2]}
    rc, log, plan, ctx = _e2e(ws, tmp_path, monkeypatch, [ef_plan(2)], n=2, panel=panel,
                              story_id=story_id)
    checks = _read_json(os.path.join(ctx.story_dir, "story_checks.json"))
    return rc, log, ctx, checks


def _n23(messages):
    return [m for m in messages if " N23 " in m]


def test_ct11_one_re_ask_then_the_landing_reply(ws, tmp_path, monkeypatch):
    rc, log, ctx, checks = _ct11(ws, tmp_path, monkeypatch, [_miss(1), _land(1)], [_land(2)])
    assert rc == 0
    assert [c["stage"] for c in log] == ["plan", "panel", "panel", "panel"]
    with open(os.path.join(ctx.story_dir, "story_rounds", "round_0", "panel_01_prompt_2.txt"),
              encoding="utf-8") as f:
        assert "- panel 1: N23 end frame landing: Motion: " in f.read()
    assert _n23([m["message"] for m in checks["hard"] + checks["advisory"]]) == []


def test_ct11_a_writer_that_misses_twice_is_kept_with_an_advisory(ws, tmp_path, monkeypatch):
    rc, log, ctx, checks = _ct11(ws, tmp_path, monkeypatch, [_miss(1), _miss(1)], [_land(2)])
    assert rc == 0
    assert [c["stage"] for c in log] == ["plan", "panel", "panel", "panel"]
    advisory = [m["message"] for m in checks["advisory"]]
    assert len(_n23(advisory)) == 1
    assert _n23(advisory)[0].startswith("panel 1: N23 end frame landing: Motion: has no camera "
                                        "sentence whose words after 'as the move completes,'")
    assert _n23([m["message"] for m in checks["hard"]]) == []
    hard = checks["hard"]
    rc2, advisories = se.recheck(ctx, ltx_movie._validate_story_md)
    assert rc2 == 0
    assert _n23(advisories) == _n23(advisory)
    assert _read_json(os.path.join(ctx.story_dir, "story_checks.json"))["hard"] == hard


def test_ct11_no_re_ask_without_a_call_left(ws, tmp_path, monkeypatch):
    rc, log, ctx, checks = _ct11(ws, tmp_path, monkeypatch, [{"answer": "not json"}, _miss(1)],
                                 [_land(2)])
    assert rc == 0
    assert [(c["stage"], c["panel"]) for c in log] == [
        ("plan", None), ("panel", 1), ("panel", 1), ("panel", 2)]
    assert len(_n23([m["message"] for m in checks["advisory"]])) == 1


def test_ct11_writers_that_land_get_no_n23(ws, tmp_path, monkeypatch):
    rc, log, ctx, checks = _ct11(ws, tmp_path, monkeypatch, [_land(1)], [_land(2)])
    assert rc == 0
    assert [c["stage"] for c in log] == ["plan", "panel", "panel"]
    assert _n23([m["message"] for m in checks["hard"] + checks["advisory"]]) == []
    assert not any("N23" in " ".join(c["argv"]) for c in log)


# A 15-word spoken line (a hard T1 on a 6-second clip) and a 3-action Motion (a hard T2), as in
# tests/test_dialogue.py's OVER_CAP and BUSY; a parse-time repair never removes either.
T1_LINE = "I carry a sealed letter from the harbour master for the abbot of this temple."
T2_MOTION = ("The courier stops at the crates, then turns, then pedals on toward the far end of the "
             "wet road.")
LAND2 = " The camera tracks the courier — as the move completes, " + _clause(END_FRAME % 2) + "."


def _story_md(ctx):
    with open(os.path.join(ctx.story_dir, "story.md"), encoding="utf-8") as f:
        return f.read()


def test_ct11_a_re_ask_that_adds_a_hard_problem_keeps_reply_1(ws, tmp_path, monkeypatch):
    raw = ef_plan(2)
    raw["beats"][0]["speaker"] = "c1"
    first = dict(_miss(1), dialogue="Keep moving.")
    second = dict(_land(1), dialogue=T1_LINE)
    rc, log, _plan, ctx = _e2e(ws, tmp_path, monkeypatch, [raw], n=2, panel={
        "1": [seu.answer(first), seu.answer(second)], "2": [seu.answer(_land(2))]})
    checks = _read_json(os.path.join(ctx.story_dir, "story_checks.json"))
    assert rc == 0
    assert [c["stage"] for c in log] == ["plan", "panel", "panel", "panel"]
    assert not [m for m in checks["hard"] + checks["unresolved"] + checks["advisory"]
                if " T1 " in m["message"]]
    assert len(_n23([m["message"] for m in checks["advisory"]])) == 1
    assert "Dialogue: the courier: Keep moving." in _story_md(ctx)


def test_ct11_a_re_ask_with_an_equal_count_is_accepted(ws, tmp_path, monkeypatch):
    first = dict(_miss(2), motion=T2_MOTION)
    second = dict(_miss(2), motion=T2_MOTION + LAND2)
    rc, log, ctx, checks = _ct11(ws, tmp_path, monkeypatch, [_land(1)], [first, second])
    assert rc == 0
    assert [c["stage"] for c in log][:4] == ["plan", "panel", "panel", "panel"]
    assert _n23([m["message"] for m in checks["hard"] + checks["advisory"]]) == []
    assert [m["message"].split()[2] for m in checks["unresolved"]] == ["T2"]
    assert LAND2.strip() in _story_md(ctx)


def test_ct11_a_re_ask_with_more_format_and_n23_problems_is_rejected(ws, tmp_path, monkeypatch):
    first = dict(_miss(2), motion=T2_MOTION)
    second = dict(_miss(2), motion=_miss(2)["motion"] + " Herring crates line the quay.")
    rc, log, ctx, checks = _ct11(ws, tmp_path, monkeypatch, [_land(1)], [first, second])
    assert rc == 0
    assert [c["stage"] for c in log][:4] == ["plan", "panel", "panel", "panel"]
    assert len(_n23([m["message"] for m in checks["advisory"]])) == 1
    assert [m["message"].split()[2] for m in checks["unresolved"]] == ["T2"]
    assert "Herring crates" not in _story_md(ctx)


# --- CT15: old stories re-check exactly as before (D10, CK3) --------------------------------------

def _forbid_end_frame_steps(monkeypatch):
    def forbidden(*_args, **_kw):
        raise AssertionError("an old story ran an end-frame step")
    for name in ("end_frame_words", "plan_end_frame_problems", "plan_copy_problems",
                 "end_frame_advisories"):
        monkeypatch.setattr(se, name, forbidden)


def _recheck_twice(ctx, monkeypatch):
    """(rc, hard, advisory) of se.recheck with RECHECK_IDS, then without N23."""
    out = []
    for ids in (se.RECHECK_IDS, tuple(i for i in se.RECHECK_IDS if i != "N23")):
        monkeypatch.setattr(se, "RECHECK_IDS", ids)
        rc, advisory = se.recheck(ctx, ltx_movie._validate_story_md)
        hard = _read_json(os.path.join(ctx.story_dir, "story_checks.json"))["hard"]
        out.append((rc, hard, advisory))
    return out


def test_ct15_old_stories_recheck_as_before(ws, monkeypatch):
    fixture = os.path.join(WS, "tests", "fixtures", "writer_pacing", "hockey-2x145-f")
    plan = _read_json(os.path.join(fixture, "plan.json"))
    hockey = seu.make_ctx(se, ws, story_id="hockey-2x145-f", panels=2, seconds="6",
                          clip_seconds=145 / 24.0, narration="speech", narrative=plan["narrative"],
                          goal=plan["goal"])
    for name in ("plan.json", "story.md"):
        shutil.copy(os.path.join(fixture, name), os.path.join(hockey.story_dir, name))
    courier = seu.make_ctx(se, ws, story_id="old-courier")
    old_plan = _normalized(courier, seu.plan_json("chained", 3))
    parts = [seu.panel_json("chained", k) for k in (1, 2, 3)]
    with open(os.path.join(courier.story_dir, "plan.json"), "w", encoding="utf-8") as f:
        json.dump(old_plan, f)
    with open(os.path.join(courier.story_dir, "story.md"), "w", encoding="utf-8") as f:
        f.write(se.assemble(courier, old_plan, parts))
    _forbid_end_frame_steps(monkeypatch)
    for ctx in (hockey, courier):
        with open(os.path.join(ctx.story_dir, "story.md"), "rb") as f:
            before = f.read()
        with_n23, without = _recheck_twice(ctx, monkeypatch)
        assert with_n23 == without, ctx.story_id
        assert with_n23[0] == 0, ctx.story_id
        with open(os.path.join(ctx.story_dir, "story.md"), "rb") as f:
            assert f.read() == before, ctx.story_id
