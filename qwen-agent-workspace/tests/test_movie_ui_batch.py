"""Tests for movie_ui_batch, the pure core of batch forks (docs/superpowers/specs/2026-10-30-batch-
forks-design.md, Section 7: BT1-BT12 and BT31, with the plan's Review Focus pin 5).

Run from the workspace root: python3 -m pytest -q -p no:cacheprovider tests/test_movie_ui_batch.py
Stdlib plus pytest. No test reads the real HOME, renders or contacts a server: the functions here
are pure or list a temporary directory, and V1 and the fork-directory check are passed in as fakes.
"""

import os
import re
import shutil
import subprocess
import sys

import pytest

WS = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
sys.path.insert(0, WS)

import movie_ui_batch as batch  # noqa: E402
import movie_ui_lib as lib  # noqa: E402

WSR = "/abs/ws"
STATE = "/abs/state"
BID = "20261030-120501-ab12"
NARRATIVE = "A ronin rescues a child from a burning village at dusk."
LORA = {"id": None, "path": "/loras/free.safetensors", "strength": 0.7, "kind": None}
SEED = "a" * 64 + ".png"
EXPECTED_LEVELS = {
    "model": "render", "gemma": "render", "video_loras": "render", "action_loras": "render",
    "frames": "render", "fps": "render", "no_low_ram": "render", "panel_timeout": "render",
    "width": "stills", "height": "stills", "stills_loras": "stills", "location_strength": "stills",
    "narrative": "replan", "goal": "replan", "panels": "replan", "length": "replan",
    "seed_upload": "replan", "mode": "replan", "characters": "replan", "locations": "replan",
    "narration": "replan", "story_legacy": "replan", "story_model": "replan", "judge": "replan",
    "auto_lora": "replan",
}


def saved(**overrides):
    """A saved job's fields (last_fields) of a movie of story ronin-rescue."""
    fields = lib.compose_fields({"ws": WSR, "action": "movie", "story_id": "ronin-rescue",
                                 "narrative": NARRATIVE})
    fields.update(overrides)
    return fields


def variant(settings=None, append="", replace=(), per_story=None, label="v1"):
    return {"label": label, "settings": dict(settings or {}),
            "prompt": {"append": append, "replace": [{"find": f, "with": w} for f, w in replace],
                       "per_story": dict(per_story or {})}}


def info(fields="saved", has_story=True, busy_job=None, code="job", batch_id=None, exists_dir=True):
    return {"dir": exists_dir, "has_story": has_story, "busy_job": busy_job,
            "fields": saved() if fields == "saved" else fields, "code": code, "batch": batch_id,
            "number": None}


def plan(stories, variants, originals=None, number=3, errors=(), existing=()):
    """plan_cells with V1 returning errors and the fork directories in existing."""
    originals = originals or dict((s, info()) for s in stories)
    return batch.plan_cells(stories, variants, number, WSR, STATE, originals,
                            lambda fields: list(errors), lambda fork: fork in existing)


def one(settings=None, base=None, **kw):
    """The single cell of a 1 x 1 plan of ronin-rescue."""
    originals = {"ronin-rescue": info(fields=saved(**(base or {})))}
    return plan(["ronin-rescue"], [variant(settings, **kw)], originals)[0]


# --- BT1 (BK1): the classification table (spec 2.1) -----------------------------------------

def test_bt1_every_default_field_is_classified():
    assert set(batch.FIELD_LEVELS) | set(batch.FIXED_KEYS) == set(lib.DEFAULT_FIELDS)
    assert not set(batch.FIELD_LEVELS) & set(batch.FIXED_KEYS)
    assert (len(batch.FIELD_LEVELS), len(batch.FIXED_KEYS), len(lib.DEFAULT_FIELDS)) == (25, 5, 30)
    assert batch.FIELD_LEVELS == EXPECTED_LEVELS
    assert batch.LEVELS == ("render", "stills", "replan")
    assert batch.LEVEL_LABELS == {"render": "Render", "stills": "New stills", "replan": "Re-plan"}


ONE_KEY = [
    ("model", {"model": "/models/other"}, {}),
    ("gemma", {"gemma": "/models/gemma-other"}, {}),
    ("video_loras", {"video_loras": [LORA]}, {}),
    ("action_loras", {"action_loras": [{"name": "roundhouse-kick", "strength": None}]}, {}),
    ("frames", {"frames": 97}, {}),
    ("fps", {"fps": 30}, {}),
    ("no_low_ram", {"no_low_ram": True}, {}),
    ("panel_timeout", {"panel_timeout": 3600}, {}),
    ("width", {"width": 768}, {"width": 1024, "height": 576}),
    ("height", {"height": 512}, {"width": 1024, "height": 576}),
    ("stills_loras", {"stills_loras": [LORA]}, {}),
    ("location_strength", {"location_strength": 0.5}, {"locations": ["harbour-street"]}),
    ("narrative", None, {}),
    ("goal", {"goal": "Keep it tense."}, {}),
    ("panels", {"panels": 12}, {}),
    ("length", {"length": 60}, {}),
    ("seed_upload", {"seed_upload": SEED}, {}),
    ("mode", {"mode": "shots"}, {}),
    ("characters", {"characters": ["kyra"]}, {}),
    ("locations", {"locations": ["harbour-street"]}, {}),
    ("narration", {"narration": "none"}, {}),
    ("story_model", {"story_model": "qwen38"}, {}),
    ("story_legacy", {"story_legacy": True}, {}),
    ("judge", {"judge": True}, {}),
    ("auto_lora", {"auto_lora": False}, {}),
]


@pytest.mark.parametrize("key,settings,base", ONE_KEY, ids=[case[0] for case in ONE_KEY])
def test_bt1_a_one_key_change_gives_its_level(key, settings, base):
    cell = one(settings, base) if settings is not None else one(base=base, append="Snow falls.")
    assert cell["status"] == "ok", cell["reason"]
    assert key in [d["key"] for d in cell["diff"]]
    assert cell["level"] == EXPECTED_LEVELS[key]


# --- BT2: merge (spec 2.2) ------------------------------------------------------------------

def test_bt2_merge_defaults_fixed_keys_and_couplings():
    old = {"narrative": "N", "narration": False, "action": "story", "story_id": "x", "ws": "/elsewhere",
           "overwrite_movie": True, "redo": [3]}
    orig, fork, warnings = batch.merge(old, variant(), "ronin-rescue", "ronin-rescue-b3-v1", WSR)
    expected = lib.compose_fields({"narrative": "N"})
    expected.update(ws=WSR, action="movie", story_id="ronin-rescue", narration="none",
                    overwrite_movie=False, redo=[])
    assert (orig, warnings) == (expected, [])
    assert fork == dict(expected, story_id="ronin-rescue-b3-v1")
    assert batch.original_fields(old, "ronin-rescue", WSR) == expected
    assert batch.merge({"narration": True, "narrative": "N"}, variant(), "s1", None, WSR)[1]["narration"] == "full"
    assert batch.merge({"narrative": "N"}, variant(), "s1", None, WSR)[1]["story_id"] == "s1"
    sized = saved(width=1024, height=576)
    fork = batch.merge(sized, variant({"panels": 12}), "ronin-rescue", None, WSR)[1]
    assert (fork["panels"], fork["length"]) == (12, None)
    fork = batch.merge(sized, variant({"length": 60}), "ronin-rescue", None, WSR)[1]
    assert (fork["panels"], fork["length"]) == (None, 60)
    seeded = saved(seed_upload=SEED)
    fork = batch.merge(seeded, variant({"width": 768, "height": 512}), "ronin-rescue", None, WSR)[1]
    assert (fork["width"], fork["height"], fork["seed_upload"]) == (768, 512, None)
    fork = batch.merge(seeded, variant({"height": 512}), "ronin-rescue", None, WSR)[1]
    assert (fork["width"], fork["height"], fork["seed_upload"]) == (None, 512, None)
    fork = batch.merge(sized, variant({"seed_upload": SEED}), "ronin-rescue", None, WSR)[1]
    assert (fork["width"], fork["height"], fork["seed_upload"]) == (None, None, SEED)
    fork = batch.merge(sized, variant({"seed_upload": None}), "ronin-rescue", None, WSR)[1]
    assert (fork["width"], fork["height"], fork["seed_upload"]) == (1024, 576, None)
    loras = variant({"video_loras": [dict(LORA)]})
    fork = batch.merge(saved(), loras, "ronin-rescue", None, WSR)[1]
    loras["settings"]["video_loras"][0]["strength"] = 2
    assert fork["video_loras"] == [LORA]


# --- BT3: prompt edits (spec 2.3) -----------------------------------------------------------

def test_bt3_prompt_edits():
    prompt = {"append": "", "replace": [{"find": "dusk", "with": "dawn"},
                                         {"find": "dawn gate", "with": "east gate"}], "per_story": {}}
    assert batch.edit_prompt("dusk at the dusk gate", prompt, "s1") == ("dawn at the east gate", [])
    per = {"append": "  Snow falls.  ", "replace": [{"find": "dusk", "with": "dawn"}],
           "per_story": {"s1": "Per story dusk, then dusk.  \n"}}
    assert batch.edit_prompt("The narrative at dusk.", per, "s1") == (
        "Per story dawn, then dawn.\n\nSnow falls.", [])
    assert batch.edit_prompt("The narrative at dusk.", per, "s2") == (
        "The narrative at dawn.\n\nSnow falls.", [])
    missing = {"append": "", "replace": [{"find": "fog", "with": "rain"}], "per_story": {}}
    assert batch.edit_prompt("Clear skies.", missing, "s1") == (
        "Clear skies.", ['find text not in this prompt: "fog"'])
    blank = {"append": " \n ", "replace": [], "per_story": {}}
    assert batch.edit_prompt("Clear skies.  ", blank, "s1") == ("Clear skies.  ", [])
    long = {"append": "y" * 20, "replace": [], "per_story": {}}
    text, warnings = batch.edit_prompt("x" * 19990, long, "s1")
    assert len(text) == 20012 and warnings == ["edited prompt is 20012 characters; the limit is 20000"]
    with pytest.raises(TypeError):
        batch.edit_prompt(None, blank, "s1")


# --- BT4, BT5: identical and duplicate variants, no-op keys (BF7, BF8, BF11) -----------------

def test_bt4_identical_and_duplicate_variants():
    assert one()["reason"] == batch.IDENTICAL
    assert one({"location_strength": 0.5})["reason"] == batch.IDENTICAL
    assert one({"goal": "Keep it tense."}, base={"goal": "Keep it tense"})["reason"] == batch.IDENTICAL
    assert one(per_story={"ronin-rescue": "  " + NARRATIVE + "  \n"})["reason"] == batch.IDENTICAL
    assert one(append="   ")["reason"] == batch.IDENTICAL
    for cell in (one(), one({"location_strength": 0.5})):
        assert (cell["status"], cell["level"], cell["diff"]) == ("refused", None, [])
    cells = plan(["s1", "s2"], [variant({"model": "/models/other"}, label="first"),
                                variant({"model": "/models/other"}, label="second"),
                                variant({"model": "/models/third"}, label="third")])
    assert [(c["status"], c["reason"]) for c in cells] == [
        ("ok", None), ("refused", "same settings and prompt as variant 1 (first) for this story"), ("ok", None),
        ("ok", None), ("refused", "same settings and prompt as variant 1 (first) for this story"), ("ok", None)]


def test_bt5_a_no_op_key_is_dropped_from_the_diff_and_the_level():
    cell = one({"model": "/models/other", "location_strength": 0.5})
    assert cell["status"] == "ok" and cell["level"] == "render"
    assert cell["diff"] == [{"key": "model", "from": lib.DEFAULT_MODEL, "to": "/models/other"}]
    cell = one({"model": "/models/other", "goal": "Keep it tense."}, base={"goal": "Keep it tense"})
    assert [d["key"] for d in cell["diff"]] == ["model"] and cell["level"] == "render"


# --- BT6: a length-sized story and shorter clips (BF8, BF10) ---------------------------------

def test_bt6_resolved_panels_and_shorter_clips():
    sized = {"panels": None, "length": 60}
    moved = one({"frames": 153}, base=sized)
    assert moved["level"] == "replan"
    assert moved["diff"] == [{"key": "frames", "from": 145, "to": 153},
                             {"key": "panels", "from": 10, "to": 9, "note": "resolved from length"}]
    assert moved["warnings"] == []
    kept = one({"fps": 25}, base=sized)
    assert kept["level"] == "render" and kept["diff"] == [{"key": "fps", "from": 24, "to": 25}]
    assert kept["warnings"] == ["shorter clips (5.80 s, was 6.04 s): the copied story.md is re-checked "
                                "and can fail its spoken-line timing"]
    panels = one({"frames": 97})
    assert panels["level"] == "render" and panels["warnings"] == [
        "shorter clips (4.04 s, was 6.04 s): the copied story.md is re-checked and can fail its "
        "spoken-line timing"]
    assert one({"frames": 153})["warnings"] == []


# --- BT7: fork IDs (spec 2.5) ---------------------------------------------------------------

def test_bt7_fork_ids_numbers_and_collisions():
    assert batch.fork_id("ronin-rescue", 3, 2) == "ronin-rescue-b3-v2"
    records = [{"workspace": WSR, "number": 4}, {"workspace": "/other", "number": 9},
               {"workspace": WSR, "number": True}, None]
    assert batch.next_number(records, ["plain"], WSR) == 5
    assert batch.next_number([], ["a-b7-v1", "b-b2-v3", "plain", "c-b12x-v1"], WSR) == 8
    assert batch.next_number([], [], WSR) == 1
    long = "a" * 70 + "-" + "b" * 7
    assert len(long) == 78 and batch.fork_id(long, 3, 1) == "a" * 70 + "-bbb-b3-v1"
    assert len(batch.fork_id(long, 3, 1)) == 80 and lib.valid_story_id(batch.fork_id(long, 3, 1))
    cut = "a" * 72 + "-._" + "ccc"
    assert len(cut) == 78 and batch.fork_id(cut, 3, 1) == "a" * 72 + "-b3-v1"
    assert lib.valid_story_id(batch.fork_id(cut, 3, 1))
    bad = plan(["s1"], [variant({"model": "/models/other"})], number=10 ** 80)[0]
    assert bad["reason"] == "the fork ID would not be a valid story ID: %s" % batch.fork_id("s1", 10 ** 80, 1)
    cells = plan(["Ronin", "ronin"], [variant({"model": "/models/other"})])
    assert [(c["fork_id"], c["status"], c["reason"]) for c in cells] == [
        ("Ronin-b3-v1", "ok", None),
        ("ronin-b3-v1", "refused", "fork ID ronin-b3-v1 is also the fork ID of story Ronin in this batch")]
    taken = plan(["ronin-rescue"], [variant({"model": "/models/other"})], existing=("ronin-rescue-b3-v1",))
    assert taken[0]["reason"] == "fork ID ronin-rescue-b3-v1 already exists; it is never overwritten"


# --- BT8: the copy plan (spec 2.6) ----------------------------------------------------------

NEVER = ("movie.mp4", ".movie.lock", "movie.log", "iterate-story.log", "runs/r1/story_summary.json",
         "redo/1/panel_01.mp4", "story_rounds/round_0/story.md", "story_rounds-old/round_0/story.md",
         "story.md.bak-20261030T120000Z", "plan.stale-1.json", "seed_downscaled.png", "fork.json",
         "clips/panel_01.chainseed.png", "notes.txt", "images/seed.png", "images/panel_1.png",
         "clips/panel_02.mp4", "clips/panel_03.mp4.provenance.json")
ALLOWED = ("story.md", "plan.json", "story_checks.json", "story_prompt.txt", "catalog_loras.json",
           "manifest.json", "images/panel_01.png", "images/panel_02.png", "images/images.json",
           "clips/panel_01.mp4", "clips/panel_01.mp4.provenance.json")


def _story_fixture(root):
    for rel in ALLOWED + NEVER:
        path = os.path.join(root, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            f.write(rel.encode("utf-8"))
    os.symlink(os.path.join(root, "story.md"), os.path.join(root, "images", "panel_03.png"))
    return root


def test_bt8_the_copy_plan_of_every_level(tmp_path):
    sdir = _story_fixture(str(tmp_path / "story"))
    render = batch.copy_plan(sdir, "render")
    assert render == sorted((rel, len(rel.encode("utf-8"))) for rel in ALLOWED)
    assert [rel for rel, _n in render] == [
        "catalog_loras.json", "clips/panel_01.mp4", "clips/panel_01.mp4.provenance.json",
        "images/images.json", "images/panel_01.png", "images/panel_02.png", "manifest.json", "plan.json",
        "story.md", "story_checks.json", "story_prompt.txt"]
    assert [rel for rel, _n in batch.copy_plan(sdir, "stills")] == [
        "plan.json", "story.md", "story_checks.json", "story_prompt.txt"]
    assert batch.copy_plan(sdir, "replan") == []
    listed = set(rel for rel, _n in render)
    assert not listed & set(NEVER) and "images/panel_03.png" not in listed
    os.unlink(os.path.join(sdir, "story.md"))
    os.symlink(os.path.join(sdir, "plan.json"), os.path.join(sdir, "story.md"))
    assert "story.md" not in [rel for rel, _n in batch.copy_plan(sdir, "stills")]


def test_batch_review_focus_5_symlinked_images_and_clips_directories(tmp_path):
    """Review Focus 5: an original whose images/ and clips/ are symlinks to a shared folder."""
    shared = _story_fixture(str(tmp_path / "shared"))
    sdir = str(tmp_path / "story")
    os.makedirs(sdir)
    with open(os.path.join(sdir, "story.md"), "w", encoding="utf-8") as f:
        f.write("## Panel 1 -- Shot 1\n")
    os.symlink(os.path.join(shared, "images"), os.path.join(sdir, "images"))
    os.symlink(os.path.join(shared, "clips"), os.path.join(sdir, "clips"))
    assert batch.copy_plan(sdir, "render") == [("story.md", 21)]


# --- BT9: the 400 messages of spec 6, exact and in order -----------------------------------

def _errors(body):
    return batch.validate_request(body)[1]


def test_bt9_every_400_message_in_table_order():
    assert _errors({"stories": [], "variants": []}) == [
        "stories must be a list of 1 to 24 distinct story IDs", "variants must be a list of 1 to 6 variants"]
    for stories in (None, "s1", ["s1", "s1"], ["a..b"], ["-x"], [5], ["s%d" % i for i in range(25)]):
        assert _errors({"stories": stories, "variants": [variant()]}) == [
            "stories must be a list of 1 to 24 distinct story IDs"], stories
    for variants in (None, [variant()] * 7, ["v1"]):
        assert _errors({"stories": ["s1"], "variants": variants}) == [
            "variants must be a list of 1 to 6 variants"], variants
    assert _errors({"stories": ["s%d" % i for i in range(5)], "variants": [variant()] * 5}) == [
        "a batch has at most 24 cells; this one has 25 (5 stories x 5 variants)"]
    first = {"label": "", "settings": {"ws": "/x", "narrative": "n", "bogus": 1, "panels": 3, "length": 9,
                                       "width": 64},
             "prompt": {"append": 5, "replace": [{"find": "", "with": 7}, {"find": "ok", "with": "x" * 20001}],
                        "per_story": {"ronin-rescue": ""}}}
    second = {"label": "two\nlines", "settings": {"seed_upload": SEED, "width": 64, "height": 64},
              "prompt": {"replace": [{"find": "a", "with": "b"}] * 11, "per_story": {"other": "x"}}}
    assert _errors({"stories": ["ronin-rescue"], "variants": [first, second]}) == [
        "variant 1: label must be 1 to 24 characters with no line breaks",
        "variant 2: label must be 1 to 24 characters with no line breaks",
        "variant 1: setting ws cannot be changed in a variant",
        "variant 1: setting bogus cannot be changed in a variant",
        "variant 1: change the prompt with append, replace or per-story text",
        "variant 1: give panels or length, not both",
        "variant 1: give width and height together",
        "variant 2: give a seed image or a resolution, not both",
        "variant 1: append must be a string of at most 20000 characters",
        "variant 2: replace must be a list of at most 10 {find, with} pairs",
        "variant 1: replace pair 1: find must be 1 to 20000 characters",
        "variant 1: replace pair 1: with must be a string of at most 20000 characters",
        "variant 1: replace pair 2: with must be a string of at most 20000 characters",
        "variant 2: per_story must map story IDs of this batch to text",
        "variant 1: per-story prompt for ronin-rescue must be 1 to 20000 characters"]
    assert _errors({"stories": ["s1"], "variants": [{"label": "v1", "settings": [], "prompt": "x"}]}) == [
        "variant 1: settings must be an object", "variant 1: prompt must be an object"]
    assert _errors({"stories": ["s1"], "variants": [{"settings": {}}]}) == [
        "variant 1: label must be 1 to 24 characters with no line breaks"]
    for replace in ([{"find": "a"}], [{"find": "a", "with": "b", "x": 1}], ["a"], {"find": "a"}):
        assert _errors({"stories": ["s1"], "variants": [{"label": "v1", "prompt": {"replace": replace}}]}) == [
            "variant 1: replace must be a list of at most 10 {find, with} pairs"], replace
    assert _errors({"stories": ["s1"], "variants": [{"label": "v1", "prompt": {"per_story": {"s1": 5}}}]}) == [
        "variant 1: per_story must map story IDs of this batch to text"]
    assert _errors({"stories": ["s1"], "variants": [{"label": "v1", "settings": {"seed_upload": None,
                                                                                    "width": 64,
                                                                                    "height": 64}}]}) == []


def test_bt9_a_valid_request_is_cleaned():
    body = {"ws": "/ignored", "stories": ["s1", "s2"],
            "variants": [{"label": "v1", "settings": {"model": "/models/other"}},
                         {"label": "v2", "prompt": {"append": "Snow.", "replace": [{"find": "a", "with": "b"}],
                                                    "per_story": {"s2": "Text."}}}]}
    clean, errors = batch.validate_request(body)
    assert errors == []
    assert clean == {"stories": ["s1", "s2"], "variants": [
        {"label": "v1", "settings": {"model": "/models/other"},
         "prompt": {"append": "", "replace": [], "per_story": {}}},
        {"label": "v2", "settings": {},
         "prompt": {"append": "Snow.", "replace": [{"find": "a", "with": "b"}], "per_story": {"s2": "Text."}}}]}


# --- BT10 (BK4 unit), BT11: the submit order and the totals ---------------------------------

def test_bt10_the_submit_order():
    cells = [{"story_id": s, "variant": m, "status": "pending", "level": level}
             for s in ("s1", "s2") for m, level in ((1, "render"), (2, "replan"), (3, "stills"))]
    assert batch.submit_order(cells, ["s1", "s2"]) == [1, 4, 2, 5, 0, 3]
    cells[4]["status"] = "refused"
    assert batch.submit_order(cells, ["s1", "s2"]) == [1, 2, 5, 0, 3]


def test_bt11_the_totals_text():
    cells = [{"status": "ok", "level": level} for level in ("render", "replan", "stills", "render")]
    assert batch.totals(cells) == {"jobs": 4, "replan": 1, "stills": 1, "render": 2, "refused": 0,
                                   "text": "4 jobs: 1 re-plan, 1 new stills, 2 render-only"}
    cells += [{"status": "refused", "level": None}, {"status": "invalid", "level": None}]
    assert batch.totals(cells)["text"] == "4 jobs: 1 re-plan, 1 new stills, 2 render-only; 2 refused"
    assert batch.totals(cells)["refused"] == 2


# --- BT12: originals without story.md, a directory or saved settings (BF9, spec 3.6) --------

def test_bt12_an_original_without_story_md_is_replan():
    originals = {"ronin-rescue": info(has_story=False)}
    cell = plan(["ronin-rescue"], [variant({"model": "/models/other"})], originals)[0]
    assert (cell["status"], cell["level"]) == ("ok", "replan")
    assert cell["warnings"] == ["the original has no story.md; this fork writes a new story"]
    gone = plan(["ronin-rescue"], [variant({"model": "/models/other"})],
                {"ronin-rescue": info(exists_dir=False)})[0]
    assert gone["reason"] == "story ronin-rescue no longer exists in this workspace"
    busy = plan(["ronin-rescue"], [variant({"model": "/models/other"})],
                {"ronin-rescue": info(busy_job="20261030-120000-0a0a")})[0]
    assert busy["reason"] == "story ronin-rescue has a job queued or running (job 20261030-120000-0a0a)"
    for code, text in (("none", "story ronin-rescue has no saved Compose settings (it was started from "
                                "the command line)"),
                       ("gone", "story ronin-rescue has no saved Compose settings (its job and its batch "
                                "%s were deleted)" % BID),
                       ("mismatch", "story ronin-rescue has no saved Compose settings (its job was deleted "
                                    "and batch %s has no matching record of it)" % BID)):
        cell = plan(["ronin-rescue"], [variant({"model": "/models/other"})],
                    {"ronin-rescue": info(fields=None, code=code, batch_id=BID)})[0]
        assert (cell["status"], cell["reason"]) == ("refused", text)
    invalid = plan(["ronin-rescue"], [variant({"model": "/models/other"})], errors=["a", "b"])[0]
    assert (invalid["status"], invalid["reason"], invalid["level"]) == ("invalid", "a\nb", None)
    broken = plan(["ronin-rescue"], [variant({"model": "/models/other"})],
                  {"ronin-rescue": info(fields=saved(narrative=None))})[0]
    assert broken["reason"] == ("the saved settings of story ronin-rescue cannot be used: TypeError: the "
                                "saved narrative is not a string")
    zero = plan(["ronin-rescue"], [variant({"fps": 24})],
                {"ronin-rescue": info(fields=saved(fps=0))})[0]
    assert zero["reason"].startswith("the saved settings of story ronin-rescue cannot be used: "
                                     "ZeroDivisionError: ")
    assert batch.eligibility_reason(None, "job", None) is None
    assert batch.eligibility_reason(None, "ok", BID) is None


# --- BT31 (BK8 unit): the batch-record field fallback (BF41c) -------------------------------

def _pair():
    fields = saved(story_id="ronin-rescue-b1-v1", model="/models/other")
    fork_rec = {"schema": batch.FORK_SCHEMA, "fork_id": "ronin-rescue-b1-v1", "source_story": "ronin-rescue",
                "batch": BID, "variant": 1, "label": "v1", "level": "render", "diff": [],
                "created": "2026-10-30T12:05:09Z"}
    batch_rec = {"schema": batch.BATCH_SCHEMA, "id": BID, "number": 1, "workspace": WSR,
                 "cells": [{"story_id": "ronin-rescue", "variant": 1, "fork_id": "ronin-rescue-b1-v1",
                            "status": "queued", "job_id": "20261030-120509-0a0b", "fields": fields}]}
    return fork_rec, batch_rec


def test_bt31_a_matching_pair_gives_the_cell_fields():
    fork_rec, batch_rec = _pair()
    code, fields, batch_id, number = batch.fork_fallback(fork_rec, batch_rec, "ronin-rescue-b1-v1", WSR)
    assert (code, batch_id, number) == ("ok", BID, 1)
    assert fields == batch_rec["cells"][0]["fields"] and fields is not batch_rec["cells"][0]["fields"]


def test_bt31_none_and_gone():
    fork_rec, batch_rec = _pair()
    for bad in (None, [], dict(fork_rec, schema="x"), dict(fork_rec, fork_id="other"),
                dict(fork_rec, batch="../x"), dict(fork_rec, batch=5), dict(fork_rec, batch=None)):
        assert batch.fork_fallback(bad, batch_rec, "ronin-rescue-b1-v1", WSR) == ("none", None, None, None)
    assert batch.fork_fallback(fork_rec, None, "ronin-rescue-b1-v1", WSR) == ("gone", None, BID, None)


MISMATCH = [
    ("schema", lambda f, b: b.update(schema="x")),
    ("id", lambda f, b: b.update(id="20261030-120501-ffff")),
    ("workspace", lambda f, b: b.update(workspace="/other")),
    ("no-cell", lambda f, b: b.update(cells=[])),
    ("two-cells", lambda f, b: b["cells"].append(dict(b["cells"][0], fork_id="Ronin-Rescue-b1-v1"))),
    ("cell-case", lambda f, b: b["cells"][0].update(fork_id="Ronin-rescue-b1-v1")),
    ("source", lambda f, b: f.update(source_story="harbour-chase")),
    ("variant", lambda f, b: f.update(variant=2)),
    ("cancelled", lambda f, b: b["cells"][0].update(status="cancelled")),
    ("job", lambda f, b: b["cells"][0].update(job_id=None)),
    ("fields", lambda f, b: b["cells"][0].update(fields=None)),
    ("fields-id", lambda f, b: b["cells"][0]["fields"].update(story_id="ronin-rescue")),
]


@pytest.mark.parametrize("name,change", MISMATCH, ids=[case[0] for case in MISMATCH])
def test_bt31_mismatch(name, change):
    fork_rec, batch_rec = _pair()
    change(fork_rec, batch_rec)
    assert batch.fork_fallback(fork_rec, batch_rec, "ronin-rescue-b1-v1", WSR) == ("mismatch", None, BID, None)
