"""Tests for seed-folder Compose and Characters (docs/superpowers/specs/2026-11-01-seed-folder-
compose-design.md, Section 6: SDT1-SDT37, with the plan's Review Focus pins 1-5): the pure module
movie_ui_seedfolder, lib.shared_checks, POST /api/jobs/seed-folder, POST
/api/characters/seed-folder and the static page.

Run from the workspace root: python3 -m pytest -q -p no:cacheprovider tests/test_movie_ui_seedfolder.py

Rules (spec Section 6):
- The HTTP tests use the env fixture: mt.set_home, mt.make_stub_workspace and the in-test
  mt.Running server on 127.0.0.1. Uploads go through POST /api/uploads with mt.PNG + bytes([i])
  (distinct IDs) or mt.PNG (the same ID).
- lib.shared_checks is replaced by a pass stub (one V2 record) in every HTTP test, except where
  a test replaces it otherwise. V1 runs for real (stub workspace, current help fixture). V6 runs
  the stub bin/ltx-movie --dry-run (exit 0) unless the test replaces lib.dry_run_check.
- The Characters tests use the same fixture, which removes CHARACTER_LIBRARY_DIR unless a test
  sets it, and the stub bin/character (never run, because no test dispatches a job).
- No test uses the real HOME, renders, or contacts a real server. None touches port 8177 or
  8178. The VLM lifecycle is off (conftest.py). No test ever starts a job.
Stdlib plus pytest.
"""

import json
import os
import random
import re
import shutil
import string
import subprocess
import threading
import time

import pytest

import movie_ui_testutil as mt
import movie_ui_lib as lib
import movie_ui_seedfolder as seedfolder
import movie_ui_server as srv

WS = mt.WS
P40 = "p" * 40
UP = "a" * 64 + ".png"
DEGENERATE = "Error: --seed-image is degenerate: 8x8 (each edge must be at least 64 px)"
PREFIX_MSG = "story ID prefix must be a valid story ID of at most 40 characters"
SEEDS_MSG = "seeds must be a list of 1 to 100 items"
PREVIEW_MSG = "preview must be true or false"
CPREFIX_MSG = "character name prefix must match [a-z][a-z0-9-]{1,23} and be at most 12 characters"


# --- SDT1 (SD5, SD7, SD8, SD10): the examples of spec 2.3 ---------------------------------------

# (names, prefix, taken, result); taken None stands for taken_names([], []) (row 13).
EXAMPLES = [
    (["beach.png"], "", set(), ["beach"]),
    (["beach.png", "beach.jpg"], "", set(), ["beach", "beach-2"]),
    (["Beach Day!.webp"], "temple", set(), ["temple-Beach-Day"]),
    (["__01.png"], "", set(), ["01"]),
    (["日本.png"], "", set(), ["seed"]),
    (["beach.png"], "", {"beach", "beach-2"}, ["beach-3"]),
    (["Beach.png"], "", {"beach"}, ["Beach-2"]),
    (["Beach Day.final.png"], "", set(), ["Beach-Day.final"]),
    (["Café.png"], "", set(), ["Cafe"]),
    (["a..b.png", "a -- b.png"], "", set(), ["a.b", "a-b"]),
    ([".png"], "", set(), ["png"]),
    (["Beach.png", "beach.jpg"], "", set(), ["Beach", "beach-2"]),
    (["movie-ui-smoke.png"], "", None, ["movie-ui-smoke-2"]),
    (["a" * 100 + ".png"], P40, set(), [P40 + "-" + "a" * 39]),
    (["a" * 100 + ".png"], P40, {(P40 + "-" + "a" * 39).lower()}, [P40 + "-" + "a" * 37 + "-2"]),
    (["a" * 77 + "-bc.png"], "", {("a" * 77 + "-bc").lower()}, ["a" * 77 + "-2"]),
    (["x.png"], "", {"x"} | set("x-%d" % k for k in range(2, 1000)), ["x-1000"]),
]


@pytest.mark.parametrize("names,prefix,taken,want", EXAMPLES,
                         ids=["row%d" % (i + 1) for i in range(len(EXAMPLES))])
def test_sdt1_the_story_id_examples(names, prefix, taken, want):
    taken = seedfolder.taken_names([], []) if taken is None else taken
    assert seedfolder.assign_story_ids(names, prefix, taken) == want


# --- SDT2 (SD5): seed_stem edge cases --------------------------------------------------------------

def test_sdt2_seed_stem_edge_cases():
    for name, want in (("", "seed"), ("...", "seed"), ("-_-.png", "seed"), ("a\tb.png", "a-b"),
                       ("x.tar.gz", "x.tar")):
        assert seedfolder.seed_stem(name) == want, name


# --- SDT3 (SD6, SD7): prefixes and the 80-character cut ---------------------------------------------

def test_sdt3_prefixes_and_the_80_character_cut():
    for prefix in ("", "temple", P40):
        assert seedfolder.valid_prefix(prefix) is True, prefix
    for prefix in ("p" * 41, "-x", "a..b", "a/b", 5):
        assert seedfolder.valid_prefix(prefix) is False, prefix
    story_id = seedfolder.story_id_for(seedfolder.seed_stem("b" * 120 + ".png"), "", set())
    assert story_id == "b" * 80 and len(story_id) == 80


# --- SDT4 (SD7, SD9): case-insensitive collisions keep the file's case -------------------------------

def test_sdt4_case_insensitive_collisions_keep_the_file_case():
    assert seedfolder.assign_story_ids(["beach.png"], "", seedfolder.taken_names(["BEACH"], [])) == [
        "beach-2"]
    assert seedfolder.assign_story_ids(["BEACH.png"], "", {"beach"}) == ["BEACH-2"]


# --- SDT5 (SD9): the taken set from a listing and the busy jobs --------------------------------------

def test_sdt5_the_taken_set_from_a_listing(tmp_path):
    stories = os.path.join(str(tmp_path), "generated", "stories")
    os.makedirs(os.path.join(stories, "d1"))
    with open(os.path.join(stories, "f1"), "w") as f:
        f.write("x")
    os.symlink(os.path.join(stories, "missing"), os.path.join(stories, "l1"))
    os.symlink(os.path.join(stories, "d1"), os.path.join(stories, "l2"))
    got = seedfolder.taken_names(os.listdir(stories), {"Busy": "j", None: "k"})
    assert got == {"d1", "f1", "l1", "l2", "busy", "movie-ui-smoke"}


# --- SDT6 (SD8): taken is not modified; the loop bound holds ------------------------------------------

def test_sdt6_taken_is_not_modified_and_the_loop_bound_holds():
    taken = {"beach"}
    assert seedfolder.assign_story_ids(["beach.png", "beach.png"], "", taken) == ["beach-2", "beach-3"]
    assert taken == {"beach"}
    many = {"x"} | set("x-%d" % k for k in range(2, 1000))
    assert len(many) == 999
    assert seedfolder.story_id_for("x", "", many) == "x-1000"
    assert seedfolder.first_free("", "ab", {"ab"}, 4, "-") == "ab-2"
    assert seedfolder.first_free("p-", "abcdef", set(), 6, "-") == "p-abcd"


# --- SDT7 (SD5-SD8): a random property check -----------------------------------------------------

ALPHABET = string.ascii_letters + string.digits + " ._-!/\t" + "é日ßﬁ"
PREFIX_HEAD = string.ascii_letters + string.digits
PREFIX_TAIL = PREFIX_HEAD + "._-"


def _random_prefix(rng):
    while True:
        prefix = rng.choice(PREFIX_HEAD) + "".join(rng.choice(PREFIX_TAIL)
                                                   for _ in range(rng.randint(0, 39)))
        if seedfolder.valid_prefix(prefix):
            return prefix


def test_sdt7_random_names_always_give_valid_distinct_ids():
    rng = random.Random(20261101)
    outputs = []
    for _case in range(3000):
        names = ["".join(rng.choice(ALPHABET) for _ in range(rng.randint(0, 120)))
                 for _ in range(rng.randint(1, 5))]
        prefix = "" if rng.random() < 0.5 else _random_prefix(rng)
        taken = set(s.lower() for s in rng.sample(outputs, min(len(outputs), rng.randint(0, 20))))
        ids = seedfolder.assign_story_ids(names, prefix, taken)
        assert len(ids) == len(names)
        folded = [s.lower() for s in ids]
        assert len(set(folded)) == len(folded), ids
        for story_id in ids:
            assert lib.valid_story_id(story_id), story_id
            assert ".." not in story_id and len(story_id) <= 80, story_id
            assert story_id.lower() not in taken, story_id
            if prefix:
                assert story_id.startswith(prefix + "-"), (prefix, story_id)
        outputs.extend(ids)


# --- SDT8 (SD12, SD13): validate_request ------------------------------------------------------------

def _req(**overrides):
    body = {"ws": "/abs/ws", "action": "story", "story_id": "", "narrative": "A courier crosses a quay.",
            "seeds": [{"name": "a.png", "upload_id": UP}], "preview": True}
    body.update(overrides)
    return body


def test_sdt8_validate_request_refusals():
    without_preview = _req()
    del without_preview["preview"]
    cases = [
        (_req(action="smoke"), "action must be movie or story"),
        (_req(action=None), "action must be movie or story"),
        (_req(action="redo", seeds=[]), "action must be movie or story"),
        (_req(story_id=5), PREFIX_MSG),
        (_req(story_id="-x"), PREFIX_MSG),
        (_req(story_id="p" * 41), PREFIX_MSG),
        (_req(seeds="a.png"), SEEDS_MSG),
        (_req(seeds=[]), SEEDS_MSG),
        (_req(seeds=[{"name": "a.png"}] * 101), SEEDS_MSG),
        (_req(seeds=[{"name": "a.png"}, "b.png"]), "seed 2 must be an object"),
        (_req(seeds=[{"name": 5}, "x"]), "seed 2 must be an object"),
        (_req(seeds=[{"name": 5}, {"name": "b.png"}]), "seed 1: name must be a string without '/'"),
        (_req(seeds=[{"upload_id": UP}]), "seed 1: name must be a string without '/'"),
        (_req(seeds=[{"name": "a.png"}, {"name": "sub/b.png"}]),
         "seed 2: name must be a string without '/'"),
        (_req(preview="true"), PREVIEW_MSG),
        (_req(preview=None), PREVIEW_MSG),
        (_req(preview=1), PREVIEW_MSG),
        (without_preview, PREVIEW_MSG),
    ]
    for body, message in cases:
        assert seedfolder.validate_request(body) == (None, message), (body, message)


def test_sdt8_validate_request_accepts():
    no_prefix = _req()
    del no_prefix["story_id"]
    for body in (no_prefix, _req(story_id=None), _req(story_id="")):
        clean, error = seedfolder.validate_request(body)
        assert error is None and clean["prefix"] == ""
    seeds = [{"name": "s%d.png" % i, "upload_id": UP, "extra": 1} for i in range(100)]
    clean, error = seedfolder.validate_request(_req(story_id="temple", action="movie", seeds=seeds,
                                                    preview=False, check_seams=True))
    assert error is None
    assert clean == {"prefix": "temple", "action": "movie",
                     "seeds": [{"name": "s%d.png" % i, "upload_id": UP} for i in range(100)],
                     "preview": False, "check_seams": True}
    assert seedfolder.validate_request(_req(check_seams="yes"))[0]["check_seams"] is False
    assert seedfolder.validate_request(_req(seeds=[{"name": "a.png"}]))[0]["seeds"] == [
        {"name": "a.png", "upload_id": None}]
    no_action = _req()
    del no_action["action"]
    assert seedfolder.validate_request(no_action)[0]["action"] == "story"


# --- SDT9 (SD1, SD18, SD22, SD23): imports, reasons, the run ID and the tag -------------------------

def test_sdt9_the_module_imports():
    with open(os.path.join(WS, "movie_ui_seedfolder.py"), encoding="utf-8") as f:
        source = f.read()
    assert sorted(re.findall(r"^(?:import|from)\s+([A-Za-z_][\w.]*)", source, re.M)) == [
        "movie_ui_lib", "re", "secrets", "time", "unicodedata"]


def _v6(status, detail):
    return lib.check("V6", "dry run", status, detail)


def test_sdt9_row_reasons():
    v1_pass = lib.check("V1", "fields", "pass", "")
    v1_fail = lib.check("V1", "fields", "fail", "narrative is required\nfps must be an integer from 1 to 120")
    timeout = "bin/ltx-movie --dry-run timed out after %d s" % lib.DRY_RUN_TIMEOUT
    assert seedfolder.row_reason(v1_fail, _v6("skip", "skipped: V1 failed")) == (
        "refused", "narrative is required; fps must be an integer from 1 to 120")
    assert seedfolder.row_reason(v1_pass, _v6("skip", "skipped: shared checks failed")) == (
        "skipped", "skipped: shared checks failed")
    assert seedfolder.row_reason(v1_pass, _v6("fail", timeout)) == (
        "refused", "dry run timed out after %d s" % lib.DRY_RUN_TIMEOUT)
    assert seedfolder.row_reason(v1_pass, _v6("fail", "plan\n" + DEGENERATE + "\n")) == (
        "refused", "dry run failed: " + DEGENERATE)
    assert seedfolder.row_reason(v1_pass, _v6("fail", "")) == ("refused", "dry run failed")
    assert seedfolder.row_reason(v1_pass, _v6("pass", "")) == ("ok", None)


def test_sdt9_the_run_id_and_the_seed_tag():
    assert seedfolder.RUN_ID_RE.fullmatch(seedfolder.new_run_id())
    tag = {"run": "sf-20261101-120000-ab12", "name": "a.png"}
    assert seedfolder.seed_tag({"seed_folder": dict(tag, extra=1)}) == tag
    for fields in (None, "x", {}, {"seed_folder": None}, {"seed_folder": "x"},
                   {"seed_folder": {"name": "a.png"}}, {"seed_folder": {"run": 5, "name": "a.png"}},
                   {"seed_folder": {"run": "r"}}, {"seed_folder": {"run": "r", "name": None}}):
        assert seedfolder.seed_tag(fields) is None, fields


# --- SDT26 (SD36, SD38, SD40): the character-name examples of spec 2.4 ---------------------------

CHAR_EXAMPLES = [
    (["Kyra.png"], "", set(), ["kyra"]),
    (["Kyra.png", "kyra.jpg"], "", set(), ["kyra", "kyra-2"]),
    (["Old Man #2.webp"], "temple", set(), ["temple-old-man-2"]),
    (["01_hero.png"], "", set(), ["hero"]),
    (["日本.png"], "", set(), ["char"]),
    (["a.png"], "", set(), ["a-char"]),
    (["kyra.png"], "", {"kyra", "kyra-2"}, ["kyra-3"]),
    (["Café Owner.png"], "", set(), ["cafe-owner"]),
    (["x" * 30 + ".png"], "", set(), ["x" * 24]),
    (["x" * 30 + ".png"], "", {"x" * 24}, ["x" * 22 + "-2"]),
    (["abcdefghij-klm.png"], "p" * 12, set(), ["p" * 12 + "-abcdefghij"]),
    (["2049.png"], "", set(), ["char"]),
    (["shot_01.png", "Shot 01.png"], "", set(), ["shot-01", "shot-01-2"]),
]


@pytest.mark.parametrize("names,prefix,taken,want", CHAR_EXAMPLES,
                         ids=["row%d" % (i + 1) for i in range(len(CHAR_EXAMPLES))])
def test_sdt26_the_character_name_examples(names, prefix, taken, want):
    assert seedfolder.assign_character_names(names, prefix, taken) == want


# --- SDT27 (SD36-SD38): character prefixes and a random property check ---------------------------

def test_sdt27_character_prefixes():
    for prefix in ("", "temple", "p" * 12):
        assert seedfolder.valid_character_prefix(prefix) is True, prefix
    for prefix in ("p" * 13, "a", "1ab", "Ab", "a_b", 5):
        assert seedfolder.valid_character_prefix(prefix) is False, prefix


CHAR_ALPHABET = ALPHABET + string.ascii_uppercase
CHAR_PREFIX_TAIL = string.ascii_lowercase + string.digits + "-"


def test_sdt27_random_names_always_give_valid_character_names():
    rng = random.Random(20261102)
    outputs = []
    for _case in range(3000):
        names = ["".join(rng.choice(CHAR_ALPHABET) for _ in range(rng.randint(0, 120)))
                 for _ in range(rng.randint(1, 5))]
        prefix = "" if rng.random() < 0.5 else rng.choice(string.ascii_lowercase) + "".join(
            rng.choice(CHAR_PREFIX_TAIL) for _ in range(rng.randint(1, 11)))
        assert seedfolder.valid_character_prefix(prefix), prefix
        taken = set(rng.sample(outputs, min(len(outputs), rng.randint(0, 20))))
        got = seedfolder.assign_character_names(names, prefix, taken)
        assert len(got) == len(names) and len(set(got)) == len(got), got
        for name in got:
            assert lib.CHARACTER_NAME_RE.fullmatch(name), name
            assert name not in taken, name
            if prefix:
                assert name.startswith(prefix + "-"), (prefix, name)
        outputs.extend(got)
