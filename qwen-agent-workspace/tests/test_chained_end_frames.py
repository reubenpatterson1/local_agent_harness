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
