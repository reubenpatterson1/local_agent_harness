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


# --- SDT10 (SD2): lib.shared_checks is V2-V5 of run_checks ----------------------------------------

def test_sdt10_shared_checks_split(monkeypatch, tmp_path):
    state = mt.set_home(monkeypatch, tmp_path)
    ws = mt.make_stub_workspace(tmp_path)
    tagged = []
    for name, check_id in (("host_checks", "V2"), ("model_checks", "V3"), ("lora_checks", "V4"),
                           ("compat_checks", "V5")):
        record = lib.check(check_id, name, "pass", "tagged " + name)
        tagged.append(record)
        monkeypatch.setattr(lib, name, (lambda r: lambda *args, **kwargs: [r])(record))
    dry = lib.check("V6", "dry run", "pass", "tagged dry_run_check")
    monkeypatch.setattr(lib, "dry_run_check", lambda fields, ws_real, st: dry)
    fields = mt.fields(ws)
    assert lib.run_checks(fields, ws, state) == [lib.check("V1", "fields", "pass", "")] + tagged + [dry]
    assert lib.shared_checks(fields, ws) == tagged
    assert lib.run_checks(mt.fields(ws, panels=0), ws, state) == (
        [lib.check("V1", "fields", "fail", "panels must be an integer from 1 to 200")]
        + [lib.check(i, n, "skip", "skipped: V1 failed") for i, n in lib.V_GROUP_NAMES])


# --- The HTTP tests: fixture and helpers (spec 6 rules) ---------------------------------------------

PASS_V2 = lib.check("V2", "render", "pass", "stub")


@pytest.fixture
def env(monkeypatch, tmp_path):
    monkeypatch.setenv("MOVIE_UI_VLM_LIFECYCLE", "0")
    monkeypatch.delenv("CHARACTER_LIBRARY_DIR", raising=False)
    state = mt.set_home(monkeypatch, tmp_path)
    ws = mt.make_stub_workspace(tmp_path)
    monkeypatch.setattr(lib, "shared_checks", lambda fields, ws_real, py=None: [PASS_V2])
    running = mt.Running(state)
    yield {"state": state, "ws": ws, "tmp": str(tmp_path), "srv": running}
    running.close()
    mt.kill_everything(state)


def _upload(s, data=mt.PNG):
    status, _h, payload = mt.api(s, "POST", "/api/uploads", raw=data,
                                 headers={"Content-Type": "image/png"})
    assert status == 201, payload
    return payload["upload_id"]


def _seeds(s, names, same=False):
    """[{"name", "upload_id"}], one upload per name: mt.PNG + bytes([i]), or mt.PNG for every
    name when same."""
    return [{"name": name, "upload_id": _upload(s, mt.PNG if same else mt.PNG + bytes([i]))}
            for i, name in enumerate(names)]


def _body(ws, seeds, preview, **overrides):
    """A seed-folder request: the stub workspace's valid Compose fields with no prefix."""
    body = dict(mt.fields(ws, story_id=""), seeds=seeds, preview=preview)
    body.update(overrides)
    return body


def _post(s, body):
    return mt.api(s, "POST", "/api/jobs/seed-folder", body=body)


def _job(state, job_id):
    return lib.read_job(lib.job_dir(state, job_id))


def _upload_path(state, seed):
    return os.path.join(state, "uploads", seed["upload_id"])


def _nothing_created(state):
    return lib.list_job_ids(state) == [] and os.listdir(os.path.join(state, "jobs")) == [] and \
        lib.read_queue(state) == []


# --- SDT12 (SD13): malformed requests get 400 and run nothing ----------------------------------------

def test_sdt12_malformed_requests_get_400(env):
    s, ws, state = env["srv"], env["ws"], env["state"]
    seeds = _seeds(s, ["a.png"])
    good = _body(ws, seeds, True)
    no_ws = dict(good)
    del no_ws["ws"]
    no_preview = dict(good)
    del no_preview["preview"]
    cases = [
        (no_ws, "missing ws"),
        (dict(good, ws="relative/ws"), "ws must be an absolute path"),
        (dict(good, ws=env["tmp"]), "not a harness workspace (no bin/ltx-movie): %s" % env["tmp"]),
        (dict(good, action="regenerate"), "action must be movie or story"),
        (dict(good, story_id="-x"), PREFIX_MSG),
        (dict(good, seeds=[]), SEEDS_MSG),
        (dict(good, seeds=["a.png"]), "seed 1 must be an object"),
        (dict(good, seeds=[{"name": "x/a.png", "upload_id": seeds[0]["upload_id"]}]),
         "seed 1: name must be a string without '/'"),
        (dict(good, preview="yes"), PREVIEW_MSG),
        (no_preview, PREVIEW_MSG),
    ]
    for body, message in cases:
        assert _post(s, body)[::2] == (400, {"error": message}), message
    assert _nothing_created(state)
    assert [c for c in mt.stub_calls(ws) if c["sub"] == "--dry-run"] == []


# --- SDT13 (SD14, SD19, SD21): a preview creates nothing ---------------------------------------------

def test_sdt13_a_preview_creates_nothing(env):
    s, ws, state = env["srv"], env["ws"], env["state"]
    names = ["shot10.png", "shot2.png", "Beach Day!.webp"]
    seeds = _seeds(s, names)
    uploads = sorted(os.listdir(os.path.join(state, "uploads")))
    status, _h, data = _post(s, _body(ws, seeds, True))
    assert status == 200, data
    assert set(data) == {"ok", "shared_checks", "queued", "refused", "run", "seeds"}
    assert (data["ok"], data["queued"], data["run"], data["refused"]) == (True, 0, None, 0)
    assert data["shared_checks"] == [PASS_V2]
    assert [r["name"] for r in data["seeds"]] == names
    assert [r["story_id"] for r in data["seeds"]] == ["shot10", "shot2", "Beach-Day"]
    for row, seed in zip(data["seeds"], seeds):
        assert set(row) == {"name", "upload_id", "story_id", "status", "reason", "checks", "job"}
        assert (row["upload_id"], row["status"], row["reason"], row["job"]) == (
            seed["upload_id"], "ok", None, None)
        assert [(c["id"], c["status"]) for c in row["checks"]] == [("V1", "pass"), ("V6", "pass")]
    assert _nothing_created(state)
    assert os.listdir(os.path.join(ws, "generated", "stories")) == []
    assert sorted(os.listdir(os.path.join(state, "uploads"))) == uploads


# --- SDT14 (SD14, SD15, SD20, SD21): queue story jobs in seed order ------------------------------------

def test_sdt14_queue_story_jobs_in_seed_order(env):
    s, ws, state = env["srv"], env["ws"], env["state"]
    seeds = _seeds(s, ["Beach Day!.webp", "shot2.png", "shot10.png"])
    status, _h, data = _post(s, _body(ws, seeds, False, action="story", story_id="temple"))
    assert status == 201, data
    assert (data["ok"], data["queued"], data["refused"]) == (True, 3, 0)
    ids = ["temple-Beach-Day", "temple-shot2", "temple-shot10"]
    assert [r["story_id"] for r in data["seeds"]] == ids
    queue = lib.read_queue(state)
    assert len(queue) == 3 and queue == [r["job"]["id"] for r in data["seeds"]]
    for job_id, story_id, seed in zip(queue, ids, seeds):
        job = _job(state, job_id)
        assert (job["kind"], job["story_id"]) == ("story", story_id)
        argv = job["argv"]
        assert argv[argv.index("--story-id") + 1] == story_id
        assert argv[argv.index("--seed-image") + 1] == _upload_path(state, seed)
        assert "--story-only" in argv
        assert job["fields"]["seed_upload"] == seed["upload_id"]
        assert job["fields"]["width"] is None and job["fields"]["height"] is None
    dry = [c for c in mt.stub_calls(ws) if c["tool"] == "ltx-movie" and c["sub"] == "--dry-run"]
    assert len(dry) == 3
    seen = dict((c["argv"][c["argv"].index("--story-id") + 1], c["argv"][c["argv"].index("--seed-image") + 1])
                for c in dry)
    assert seen == dict((story_id, _upload_path(state, seed)) for story_id, seed in zip(ids, seeds))


# --- SDT15 (SD15, SD18, SD20): refused rows and the one queued seed -----------------------------------

def test_sdt15_refused_rows_and_the_one_queued_seed(env, monkeypatch):
    s, ws, state = env["srv"], env["ws"], env["state"]
    seeds = _seeds(s, ["s1.png", "s2.png", "s3.png", "s4.png", "s5.png", "s6.png"])
    unknown = "f" * 64 + ".png"
    seeds[0]["upload_id"] = unknown
    seeds[1]["upload_id"] = 7
    seeds[5]["upload_id"] = ""
    timeout = "bin/ltx-movie --dry-run timed out after %d s" % lib.DRY_RUN_TIMEOUT

    def dry_run(fields, ws_real, st):
        detail = {"s3": "plan\n" + DEGENERATE + "\n", "s4": timeout}.get(fields["story_id"])
        return lib.check("V6", "dry run", "fail" if detail else "pass", detail or "")

    monkeypatch.setattr(lib, "dry_run_check", dry_run)
    status, _h, data = _post(s, _body(ws, seeds, False))
    assert status == 201, data
    assert (data["ok"], data["queued"], data["refused"]) == (True, 1, 5)
    assert [(r["status"], r["reason"]) for r in data["seeds"]] == [
        ("refused", "seed image upload %s not found" % unknown),
        ("refused", "seed image upload missing"),
        ("refused", "dry run failed: " + DEGENERATE),
        ("refused", "dry run timed out after 60 s"),
        ("ok", None),
        ("refused", "seed image upload missing")]
    assert (data["seeds"][1]["upload_id"], data["seeds"][5]["upload_id"]) == (7, "")
    assert data["seeds"][0]["checks"][1] == lib.check("V6", "dry run", "skip", "skipped: V1 failed")
    assert [r["job"] is None for r in data["seeds"]] == [True, True, True, True, False, True]
    assert lib.read_queue(state) == [data["seeds"][4]["job"]["id"]]
    assert len(lib.list_job_ids(state)) == 1


# --- SDT16 (SD16, SD20, SD21): a failed shared check skips every seed ----------------------------------

def test_sdt16_a_failed_shared_check_skips_every_seed(env, monkeypatch):
    s, ws, state = env["srv"], env["ws"], env["state"]
    failing = [lib.check("V2", "render", "fail", "ffmpeg not found on PATH")]
    monkeypatch.setattr(lib, "shared_checks", lambda fields, ws_real, py=None: list(failing))
    calls = []

    def dry_run(fields, ws_real, st):
        calls.append(fields["story_id"])
        return lib.check("V6", "dry run", "pass")

    monkeypatch.setattr(lib, "dry_run_check", dry_run)
    seeds = _seeds(s, ["a.png", "b.png"])
    for preview, code in ((True, 200), (False, 409)):
        status, _h, data = _post(s, _body(ws, seeds, preview))
        assert status == code, data
        assert "error" not in data
        assert (data["ok"], data["queued"], data["run"], data["refused"]) == (False, 0, None, 2)
        assert data["shared_checks"] == failing
        assert [(r["status"], r["reason"]) for r in data["seeds"]] == [
            ("skipped", "skipped: shared checks failed")] * 2
        assert [r["checks"][1] for r in data["seeds"]] == [
            lib.check("V6", "dry run", "skip", "skipped: shared checks failed")] * 2
    assert calls == []
    assert _nothing_created(state)


# --- SDT17 (SD15, SD16, SD20): shots mode refuses every seed before the shared checks ------------------

def test_sdt17_shots_mode_refuses_every_seed(env, monkeypatch):
    s, ws, state = env["srv"], env["ws"], env["state"]
    calls = []

    def shared(fields, ws_real, py=None):
        calls.append(fields["story_id"])
        return [PASS_V2]

    monkeypatch.setattr(lib, "shared_checks", shared)
    seeds = _seeds(s, ["a.png", "b.png"])
    for preview, code in ((True, 200), (False, 409)):
        status, _h, data = _post(s, _body(ws, seeds, preview, action="movie", mode="shots"))
        assert status == code, data
        assert (data["ok"], data["queued"], data["shared_checks"]) == (False, 0, [])
        assert [(r["status"], r["reason"]) for r in data["seeds"]] == [
            ("refused", "a seed image cannot be used with shots mode")] * 2
    assert calls == []
    assert _nothing_created(state)


# --- SDT18 (SD20): seams jobs follow their movies ------------------------------------------------------

def test_sdt18_seams_jobs_follow_their_movies(env):
    s, ws, state = env["srv"], env["ws"], env["state"]
    seeds = _seeds(s, ["m1.png", "m2.png"])
    status, _h, data = _post(s, _body(ws, seeds, False, action="movie", mode="chained", check_seams=True))
    assert status == 201 and data["queued"] == 2, data
    m1, m2 = [r["job"]["id"] for r in data["seeds"]]
    queue = lib.read_queue(state)
    assert len(queue) == 4 and (queue[0], queue[2]) == (m1, m2)
    for movie, seams in ((m1, queue[1]), (m2, queue[3])):
        assert _job(state, movie)["kind"] == "movie"
        job = _job(state, seams)
        assert job["kind"] == "seams"
        assert job["fields"] == {"ws": ws, "story_id": _job(state, movie)["story_id"], "after": movie}
    before = lib.read_queue(state)
    status, _h, data = _post(s, _body(ws, seeds, False, action="movie", mode="chained", check_seams=False))
    assert status == 201, data
    assert lib.read_queue(state) == before + [r["job"]["id"] for r in data["seeds"]]
    before = lib.read_queue(state)
    status, _h, data = _post(s, _body(ws, seeds, False, action="story", check_seams=True))
    assert status == 201, data
    assert lib.read_queue(state) == before + [r["job"]["id"] for r in data["seeds"]]


# --- SDT19 (SD20, SD23, SD24): the seed-folder tag -----------------------------------------------------

def test_sdt19_the_seed_folder_tag(env):
    s, ws, state = env["srv"], env["ws"], env["state"]
    names = ["Beach Day!.webp", "shot2.png", "shot10.png"]
    status, _h, data = _post(s, _body(ws, _seeds(s, names), False, story_id="temple"))
    assert status == 201, data
    run = data["run"]
    assert seedfolder.RUN_ID_RE.fullmatch(run)
    for row, name in zip(data["seeds"], names):
        fields = _job(state, row["job"]["id"])["fields"]
        assert fields["seed_folder"] == {"run": run, "name": name}
        assert row["job"]["seed_folder"] == {"run": run, "name": name}
        bare = dict(fields)
        del bare["seed_folder"]
        assert "seed_folder" not in lib.compose_fields(fields)
        assert lib.compose_fields(fields) == lib.compose_fields(bare)
    other = mt.make_job(env["state"], ["true"], ws, story_id="other")
    queued = mt.api(s, "GET", "/api/jobs")[2]["queued"]
    tags = dict((j["id"], j["seed_folder"]) for j in queued)
    assert tags[other] is None
    assert [tags[r["job"]["id"]] for r in data["seeds"]] == [{"run": run, "name": n} for n in names]
    assert all(len(j) == 15 for j in queued)


# --- SDT20 (SD9, SD14, SD20): final IDs avoid new stories and busy jobs ---------------------------------

def test_sdt20a_a_story_made_between_preview_and_queue(env):
    s, ws, state = env["srv"], env["ws"], env["state"]
    seeds = _seeds(s, ["beach.png"])
    assert _post(s, _body(ws, seeds, True))[2]["seeds"][0]["story_id"] == "beach"
    os.makedirs(os.path.join(ws, "generated", "stories", "beach"))
    status, _h, data = _post(s, _body(ws, seeds, False))
    assert status == 201, data
    assert data["seeds"][0]["story_id"] == "beach-2"
    assert _job(state, data["seeds"][0]["job"]["id"])["story_id"] == "beach-2"


def test_sdt20b_a_story_made_during_the_dry_run(env, monkeypatch):
    s, ws, state = env["srv"], env["ws"], env["state"]
    seen = []

    def dry_run(fields, ws_real, st):
        seen.append(fields["story_id"])
        os.makedirs(os.path.join(ws_real, "generated", "stories", "Beach"), exist_ok=True)
        return lib.check("V6", "dry run", "pass")

    monkeypatch.setattr(lib, "dry_run_check", dry_run)
    status, _h, data = _post(s, _body(ws, _seeds(s, ["beach.png"]), False))
    assert status == 201, data
    assert seen == ["beach"]
    assert data["seeds"][0]["story_id"] == "beach-2"
    assert _job(state, data["seeds"][0]["job"]["id"])["story_id"] == "beach-2"


def test_sdt20c_busy_jobs_take_their_story_ids(env):
    s, ws, state = env["srv"], env["ws"], env["state"]
    mt.make_job(state, ["true"], ws, story_id="BEACH")
    mt.make_job(state, ["true"], ws, story_id="shore",
                status={"state": "running", "dispatched": lib.utc_now()})
    status, _h, data = _post(s, _body(ws, _seeds(s, ["beach.png", "shore.png"]), False))
    assert status == 201, data
    assert [r["story_id"] for r in data["seeds"]] == ["beach-2", "shore-2"]


# --- SDT21 (SD17): four dry runs at a time, with no lock held ---------------------------------------

def test_sdt21_four_dry_runs_at_a_time_with_no_lock_held(env, monkeypatch):
    s, ws = env["srv"], env["ws"]
    guard = threading.Lock()
    counts = {"now": 0, "max": 0, "ran": 0}
    locks = []

    def probe():
        got = []
        for lock in (srv.STORE_LOCK, srv.BATCH_LOCK):
            ok = lock.acquire(timeout=1)
            if ok:
                lock.release()
            got.append(ok)
        locks.append(got)

    def dry_run(fields, ws_real, st):
        with guard:
            counts["now"] += 1
            counts["max"] = max(counts["max"], counts["now"])
        other = threading.Thread(target=probe)
        other.start()
        other.join()
        time.sleep(0.3)
        with guard:
            counts["now"] -= 1
            counts["ran"] += 1
        return lib.check("V6", "dry run", "pass")

    monkeypatch.setattr(lib, "dry_run_check", dry_run)
    status, _h, data = _post(s, _body(ws, _seeds(s, ["s%d.png" % i for i in range(10)]), True))
    assert status == 200, data
    assert (counts["max"], counts["ran"]) == (4, 10)
    assert locks == [[True, True]] * 10


# --- SDT22 (SD8, SD20): the same image twice -----------------------------------------------------------

def test_sdt22_the_same_image_twice(env):
    s, ws, state = env["srv"], env["ws"], env["state"]
    seeds = _seeds(s, ["a.png", "a.png"], same=True)
    assert seeds[0]["upload_id"] == seeds[1]["upload_id"]
    status, _h, data = _post(s, _body(ws, seeds, False))
    assert status == 201 and data["queued"] == 2, data
    assert [r["story_id"] for r in data["seeds"]] == ["a", "a-2"]
    argvs = [_job(state, r["job"]["id"])["argv"] for r in data["seeds"]]
    assert [a[a.index("--seed-image") + 1] for a in argvs] == [_upload_path(state, seeds[0])] * 2


# --- SDT23 (SD25): a failure mid-queue keeps the earlier jobs ------------------------------------------

def test_sdt23_a_failure_mid_queue_keeps_the_earlier_jobs(env, monkeypatch):
    s, ws, state = env["srv"], env["ws"], env["state"]
    seeds = _seeds(s, ["a.png", "b.png", "c.png"])
    real = lib.create_job
    calls = []

    def flaky(*args, **kwargs):
        calls.append(args[1])
        if len(calls) == 2:
            raise OSError(28, "No space left on device")
        return real(*args, **kwargs)

    monkeypatch.setattr(lib, "create_job", flaky)
    assert _post(s, _body(ws, seeds, False))[::2] == (500, {"error": "internal error"})
    first = calls[0]
    assert _job(state, first)["story_id"] == "a"
    assert lib.read_queue(state) == [first] and lib.list_job_ids(state) == [first]
    assert srv.STORE_LOCK.acquire(timeout=1)
    srv.STORE_LOCK.release()


# --- SDT24 (SD24): the compose routes ignore seed-folder keys ------------------------------------------

def test_sdt24_the_compose_routes_ignore_seed_folder_keys(env):
    s, ws, state = env["srv"], env["ws"], env["state"]
    upload = _upload(s)
    plain = mt.fields(ws, seed_upload=upload)
    extra = dict(plain, seeds=[{"name": "a.png", "upload_id": upload}],
                 seed_folder={"run": "sf-20261101-120000-ab12", "name": "a.png"})
    status, _h, created = mt.api(s, "POST", "/api/jobs", body=extra)
    assert status == 201, created
    fields = _job(state, created["job"]["id"])["fields"]
    assert "seeds" not in fields and "seed_folder" not in fields
    assert created["job"]["seed_folder"] is None
    assert mt.api(s, "POST", "/api/validate", body=extra)[::2] == mt.api(
        s, "POST", "/api/validate", body=plain)[::2]


# --- Review Focus 2-4 (the plan's Review Focus section) -------------------------------------------------

def test_sf_review_focus_2_a_refused_seed_does_not_push_a_later_seed_to_a_suffix(env):
    s, ws, state = env["srv"], env["ws"], env["state"]
    seeds = [{"name": "beach.png", "upload_id": "f" * 64 + ".png"},
             {"name": "beach.jpg", "upload_id": _upload(s)}]
    preview = _post(s, _body(ws, seeds, True))[2]
    assert [(r["story_id"], r["status"]) for r in preview["seeds"]] == [("beach", "refused"), ("beach-2", "ok")]
    status, _h, data = _post(s, _body(ws, seeds, False))
    assert status == 201, data
    assert [(r["story_id"], r["status"]) for r in data["seeds"]] == [("beach", "refused"), ("beach", "ok")]
    assert _job(state, data["seeds"][1]["job"]["id"])["story_id"] == "beach"


def test_sf_review_focus_3_two_queue_requests_at_once(env):
    s, ws, state = env["srv"], env["ws"], env["state"]
    seeds = _seeds(s, ["a.png", "b.png"])
    results = []

    def post():
        results.append(_post(s, _body(ws, seeds, False)))

    threads = [threading.Thread(target=post) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(r[0] for r in results) == [201, 201]
    assert sorted([row["story_id"] for row in r[2]["seeds"]] for r in results) == [["a", "b"], ["a-2", "b-2"]]
    assert sorted(_job(state, i)["story_id"] for i in lib.list_job_ids(state)) == ["a", "a-2", "b", "b-2"]
    for _status, _h, data in results:
        assert set(row["job"]["seed_folder"]["run"] for row in data["seeds"]) == {data["run"]}


def test_sf_review_focus_4_a_too_small_image_refused_by_the_real_dry_run(env):
    s, ws, state = env["srv"], env["ws"], env["state"]
    mt.stub_config(ws, {"ltx-movie --dry-run": {"exit": 2, "stdout": "", "stderr": DEGENERATE + "\n"}})
    seeds = _seeds(s, ["thumb.png", "icon.png"])
    status, _h, data = _post(s, _body(ws, seeds, True))
    assert status == 200, data
    assert (data["ok"], data["refused"]) == (False, 2)
    assert [(r["status"], r["reason"]) for r in data["seeds"]] == [("refused", "dry run failed: " + DEGENERATE)] * 2
    assert [r["checks"][1]["status"] for r in data["seeds"]] == ["fail", "fail"]
    status, _h, data = _post(s, _body(ws, seeds, False))
    assert status == 409, data
    assert _nothing_created(state)


# --- SDT25 (SD26-SD35, SD50): the static page, Compose and the shared folder code ------------------

NEW_IDS = ("c-story-id-label", "c-res-folder", "c-folder-choose", "c-folder-file", "c-folder-status",
           "c-folder-list", "c-folder-confirm", "c-folder-shared", "c-folder-summary", "c-folder-table",
           "c-folder-queue", "c-folder-cancel")
JS_TEXTS = ('"/api/jobs/seed-folder"', 'new Intl.Collator("en", {numeric: true})',
            "function sampleStoryId(name, prefix)", '"Story ID prefix (optional)"',
            '"not available for a seed folder"', '"upload failed: "', '"seed folder "', '" · "', '"Queue "',
            "const FOLDER_BOXES = {", "function part(box, name)")
SHARED_FUNCTIONS = ("onFolderPick", "openFolderConfirm", "queueFolder", "closeFolderConfirm",
                    "renderFolderTable", "renderFolderList")


def _static_texts():
    static = os.path.join(WS, "static", "movie-ui")
    texts = {}
    for name in ("index.html", "app.js", "app.css"):
        with open(os.path.join(static, name), encoding="utf-8") as f:
            texts[name] = f.read()
    return static, texts


def test_sdt25_the_static_page():
    static, texts = _static_texts()
    html, js = texts["index.html"], texts["app.js"]
    for element in NEW_IDS:
        assert html.count('id="%s"' % element) == 1, element
    for element in ("c-story-id-label", "c-res-folder"):
        assert '"#%s' % element in js, element
    assert 'ids: "c-folder"' in js and 'ids: "ch-folder"' in js
    assert "webkitdirectory" in html
    assert "<th>File</th><th>Story ID</th><th>Result</th><th>Job</th>" in html
    for text in JS_TEXTS:
        assert text in js, text
    for name in SHARED_FUNCTIONS:
        assert js.count("function %s(box" % name) == 1, name
        assert js.count("function %s(" % name) == 1, name
    for name, text in texts.items():
        for pattern in (r"https?://", r"\son[a-z]+=", r"style=", r"\balert\(", r"\bconfirm\(",
                        r"\bprompt\(", r"\beval\(", r"new Function"):
            assert not re.search(pattern, text), (name, pattern)
    node = shutil.which("node")
    if node:
        proc = subprocess.run([node, "--check", os.path.join(static, "app.js")],
                              capture_output=True, text=True, timeout=60)
        assert proc.returncode == 0, proc.stderr


# --- Review Focus 5: the page's sample story ID matches the server's rules ------------------------------

SAMPLE_CASES = [("beach.png", ""), ("Beach Day!.webp", "temple"), ("__01.png", ""), ("日本.png", ""),
                ("Beach Day.final.png", ""), ("Café.png", ""), ("a..b.png", ""), ("a -- b.png", ""),
                (".png", ""), ("a" * 100 + ".png", P40), ("a" * 77 + "-bc.png", ""), ("ﬁx.png", "Temple"),
                ("a\tb.png", ""), ("", ""), ("...", ""), ("-_-.png", "x"), ("x.tar.gz", ""),
                ("Straße ☕.jpg", ""), ("\U0001F600 smile.png", ""), ("Café ☕ día.png", "temple")]


def test_sf_review_focus_5_the_page_sample_id_matches_the_server(tmp_path):
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed")
    with open(os.path.join(WS, "static", "movie-ui", "app.js"), encoding="utf-8") as f:
        js = f.read()
    start = js.index("  function sampleStoryId(name, prefix) {")
    end = js.index("\n  }\n", start) + len("\n  }\n")
    script = js[start:end] + (
        "process.stdout.write(JSON.stringify(%s.map(function (c) { return sampleStoryId(c[0], c[1]); })));\n"
        % json.dumps(SAMPLE_CASES))
    path = os.path.join(str(tmp_path), "sample.js")
    with open(path, "w", encoding="utf-8") as f:
        f.write(script)
    proc = subprocess.run([node, path], capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stderr
    want = [seedfolder.story_id_for(seedfolder.seed_stem(name), prefix, set()) for name, prefix in SAMPLE_CASES]
    assert json.loads(proc.stdout) == want


# --- The Characters HTTP tests: helpers (spec 6 rules) ---------------------------------------------

def _cbody(ws, seeds, preview, **overrides):
    """A Characters seed-folder request: no prefix, phrase "the stranger", seed 7."""
    body = {"ws": ws, "name": "", "phrase": "the stranger", "seed": 7, "seeds": seeds, "preview": preview}
    body.update(overrides)
    return body


def _cpost(s, body):
    return mt.api(s, "POST", "/api/characters/seed-folder", body=body)


def _character_job(state, ws, kind, name, job_state=None):
    """A job naming a character, made as SDT28 says: queued, or with job_state written and the job
    removed from the queue (as mt.make_job does)."""
    job_id = lib.new_job_id(state)
    lib.create_job(state, job_id, kind, ws, None, name, ["true"], {})
    if job_state is not None:
        lib.write_queue(state, [i for i in lib.read_queue(state) if i != job_id])
        lib.write_status(lib.job_dir(state, job_id), {"state": job_state})
    return job_id


# --- SDT11 (SD11): the Compose route and its token-----------------------------------------------------

def test_sdt11_the_route_and_its_token(env):
    s = env["srv"]
    routes = list(srv.ROUTES)
    i = routes.index(("POST", r"/api/jobs", "h_job_create", "/api/jobs"))
    assert routes[i + 1] == ("POST", r"/api/jobs/seed-folder", "h_seed_folder", "/api/jobs/seed-folder")
    assert len(srv.ROUTES) == 57
    assert srv.MovieUIHandler.h_seed_folder is srv._h_seed_folder
    for token in (None, "wrong-token"):
        assert mt.api(s, "POST", "/api/jobs/seed-folder", body={}, token=token)[::2] == (
            401, {"error": "missing or invalid token"})
    assert mt.api(s, "GET", "/api/jobs/seed-folder")[::2] == (405, {"error": "method not allowed"})


# --- SDT28 (SD39): the character taken set --------------------------------------------------------

def test_sdt28_the_character_taken_set(env, monkeypatch):
    s, ws, state = env["srv"], env["ws"], env["state"]
    assert seedfolder.character_taken_names(["Kyra", ".triggers"], ["Zed", None]) == {"kyra", ".triggers", "zed"}
    library = os.path.join(ws, "generated", "characters")
    os.makedirs(os.path.join(library, "kyra"))
    with open(os.path.join(library, "nova"), "w") as f:
        f.write("x")
    os.symlink(os.path.join(library, "missing"), os.path.join(library, "ghost"))
    _character_job(state, ws, "character-create", "zed")
    _character_job(state, ws, "character-train", "yon", "running")
    _character_job(state, ws, "character-create", "old", "done")
    _character_job(state, env["tmp"], "character-create", "far")
    assert srv.character_taken(s.server, ws) == {"kyra", "nova", "ghost", "zed", "yon"}
    other = os.path.join(env["tmp"], "lib")
    os.makedirs(os.path.join(other, "lena"))
    monkeypatch.setenv("CHARACTER_LIBRARY_DIR", other)
    assert srv.character_taken(s.server, ws) == {"lena", "zed", "yon"}


# --- SDT29 (SD41): the Characters route and its token -----------------------------------------------

def test_sdt29_the_characters_route_and_its_token(env):
    s, ws = env["srv"], env["ws"]
    routes = list(srv.ROUTES)
    i = routes.index(("POST", r"/api/characters", "h_character_create", "/api/characters"))
    assert routes[i + 1] == ("POST", r"/api/characters/seed-folder", "h_character_seed_folder",
                             "/api/characters/seed-folder")
    assert len(srv.ROUTES) == 57
    assert srv.MovieUIHandler.h_character_seed_folder is srv._h_character_seed_folder
    for token in (None, "wrong-token"):
        assert mt.api(s, "POST", "/api/characters/seed-folder", body={}, token=token)[::2] == (
            401, {"error": "missing or invalid token"})
    status, _h, data = mt.api(s, "GET", "/api/characters/seed-folder?ws=" + ws)
    assert (status, data["error"]) == (502, "character printed unparsable output")


# --- SDT30 (SD43): malformed Characters requests get 400 ------------------------------------------

def test_sdt30_malformed_character_requests_get_400(env):
    s, ws, state = env["srv"], env["ws"], env["state"]
    seeds = _seeds(s, ["a.png"])
    good = _cbody(ws, seeds, True)
    no_ws = dict(good)
    del no_ws["ws"]
    cases = [
        (no_ws, "missing ws"),
        (dict(good, phrase=""), "phrase is required"),
        (dict(good, seed=-1), "seed must be an integer from 0 to 2147483647"),
        (dict(good, name="Temple"), CPREFIX_MSG),
        (dict(good, name="p" * 13), CPREFIX_MSG),
        (dict(good, seeds=[]), SEEDS_MSG),
        (dict(good, seeds=["a.png"]), "seed 1 must be an object"),
        (dict(good, seeds=[{"name": "x/a.png", "upload_id": seeds[0]["upload_id"]}]),
         "seed 1: name must be a string without '/'"),
        (dict(good, preview="yes"), PREVIEW_MSG),
        (dict(good, phrase="", seeds=[]), "phrase is required"),
    ]
    for body, message in cases:
        assert _cpost(s, body)[::2] == (400, {"error": message}), message
    assert _nothing_created(state)


# --- SDT31 (SD44, SD46): a Characters preview creates nothing ----------------------------------------

def test_sdt31_a_characters_preview_creates_nothing(env):
    s, ws, state = env["srv"], env["ws"], env["state"]
    seeds = _seeds(s, ["Kyra.png", "Old Man #2.webp", "01_hero.png"])
    status, _h, data = _cpost(s, _cbody(ws, seeds, True))
    assert status == 200, data
    assert set(data) == {"ok", "shared_checks", "queued", "refused", "run", "seeds"}
    assert (data["ok"], data["queued"], data["run"], data["shared_checks"], data["refused"]) == (
        True, 0, None, [], 0)
    assert [r["character"] for r in data["seeds"]] == ["kyra", "old-man-2", "hero"]
    for row in data["seeds"]:
        assert set(row) == {"name", "upload_id", "character", "status", "reason", "checks", "job"}
        assert [c["id"] for c in row["checks"]] == ["V1"]
        assert (row["status"], row["job"]) == ("ok", None)
    assert _nothing_created(state)
    assert not os.path.exists(os.path.join(ws, "generated", "characters"))


# --- SDT32 (SD42, SD44, SD45): queue character-create jobs in seed order -----------------------------

def _queue_three_characters(env):
    s, ws = env["srv"], env["ws"]
    names = ["Kyra.png", "Old Man #2.webp", "01_hero.png"]
    seeds = _seeds(s, names)
    status, _h, data = _cpost(s, _cbody(ws, seeds, False, class_noun="woman", descriptor="x",
                                        trigger="kyrax", force=True))
    assert status == 201, data
    return names, seeds, data


def test_sdt32_queue_character_create_jobs_in_seed_order(env):
    ws, state = env["ws"], env["state"]
    _names, seeds, data = _queue_three_characters(env)
    assert data["queued"] == 3
    queue = lib.read_queue(state)
    assert len(queue) == 3 and queue == [r["job"]["id"] for r in data["seeds"]]
    for job_id, name, seed in zip(queue, ["kyra", "old-man-2", "hero"], seeds):
        job = _job(state, job_id)
        assert (job["kind"], job["story_id"], job["character"]) == ("character-create", None, name)
        fields = job["fields"]
        assert set(fields) == {"name", "phrase", "class_noun", "descriptor", "trigger", "seed", "seed_upload",
                               "force", "ws", "seed_folder"}
        assert (fields["class_noun"], fields["descriptor"], fields["trigger"], fields["force"]) == (
            None, None, None, False)
        argv = job["argv"]
        assert argv == lib.character_argv("character-create", fields, ws, state)
        assert argv[argv.index("--phrase") + 1] == "the stranger"
        assert argv[argv.index("--seed-image") + 1] == _upload_path(state, seed)
        assert argv[argv.index("--seed") + 1] == "7"
        for flag in ("--class", "--descriptor", "--trigger", "--force"):
            assert flag not in argv, flag


# --- SDT33 (SD44, SD46): refused Characters rows ------------------------------------------------------

def test_sdt33_refused_character_rows(env):
    s, ws, state = env["srv"], env["ws"], env["state"]
    unknown = "f" * 64 + ".png"
    bad = [{"name": "a.png", "upload_id": unknown}, {"name": "b.png", "upload_id": ""},
           {"name": "c.png", "upload_id": 7}]
    want = [("refused", "seed image upload %s not found" % unknown), ("refused", "seed image upload missing"),
            ("refused", "seed image upload missing")]
    status, _h, data = _cpost(s, _cbody(ws, bad, False))
    assert status == 409, data
    assert (data["run"], data["queued"], data["refused"]) == (None, 0, 3)
    assert [(r["status"], r["reason"]) for r in data["seeds"]] == want
    assert _nothing_created(state)
    good = _seeds(s, ["d.png"])
    status, _h, data = _cpost(s, _cbody(ws, bad + good, False))
    assert status == 201, data
    assert (data["queued"], data["refused"]) == (1, 3)
    assert [(r["status"], r["reason"]) for r in data["seeds"]] == want + [("ok", None)]
    assert lib.read_queue(state) == [data["seeds"][3]["job"]["id"]]


# --- SDT34 (SD39, SD44): final names avoid new characters and busy jobs --------------------------------

def test_sdt34a_a_character_made_between_preview_and_queue(env):
    s, ws, state = env["srv"], env["ws"], env["state"]
    seeds = _seeds(s, ["kyra.png"])
    assert _cpost(s, _cbody(ws, seeds, True))[2]["seeds"][0]["character"] == "kyra"
    os.makedirs(os.path.join(ws, "generated", "characters", "kyra"))
    status, _h, data = _cpost(s, _cbody(ws, seeds, False))
    assert status == 201, data
    assert data["seeds"][0]["character"] == "kyra-2"
    assert _job(state, data["seeds"][0]["job"]["id"])["character"] == "kyra-2"


def test_sdt34b_a_queued_character_job_takes_its_name(env):
    s, ws, state = env["srv"], env["ws"], env["state"]
    _character_job(state, ws, "character-create", "nova")
    status, _h, data = _cpost(s, _cbody(ws, _seeds(s, ["nova.png"]), False))
    assert status == 201, data
    assert data["seeds"][0]["character"] == "nova-2"


def test_sdt34c_the_same_image_twice(env):
    s, ws, state = env["srv"], env["ws"], env["state"]
    seeds = _seeds(s, ["kyra.png", "kyra.png"], same=True)
    status, _h, data = _cpost(s, _cbody(ws, seeds, False))
    assert status == 201, data
    assert [r["character"] for r in data["seeds"]] == ["kyra", "kyra-2"]
    assert len(lib.read_queue(state)) == 2


# --- SDT35 (SD23, SD46): the tag on character jobs -----------------------------------------------------

def test_sdt35_the_seed_folder_tag_on_character_jobs(env):
    s, state = env["srv"], env["state"]
    names, _seeds_sent, data = _queue_three_characters(env)
    run = data["run"]
    assert seedfolder.RUN_ID_RE.fullmatch(run)
    for row, name in zip(data["seeds"], names):
        assert _job(state, row["job"]["id"])["fields"]["seed_folder"] == {"run": run, "name": name}
    queued = mt.api(s, "GET", "/api/jobs")[2]["queued"]
    assert [(j["seed_folder"], j["character"]) for j in queued] == [
        ({"run": run, "name": n}, c) for n, c in zip(names, ["kyra", "old-man-2", "hero"])]


# --- SDT36 (SD43, SD45, SD46): POST /api/characters is unchanged ----------------------------------------

def test_sdt36_post_api_characters_is_unchanged(env):
    s, ws, state = env["srv"], env["ws"], env["state"]
    body = {"ws": ws, "name": "kyra", "phrase": "", "seed": -1, "descriptor": "a tall man", "class_noun": "man"}
    status, _h, data = mt.api(s, "POST", "/api/characters", body=body)
    assert (status, data["error"], data["errors"]) == (
        400, "invalid fields", ["phrase is required", "seed must be an integer from 0 to 2147483647"])
    status, _h, data = mt.api(s, "POST", "/api/characters", body=dict(body, phrase="the stranger", seed=7))
    assert status == 201, data
    assert data["job"]["kind"] == "character-create"
    status, _h, data = _cpost(s, _cbody(ws, _seeds(s, ["nova.png"]), False))
    assert status == 201, data
    fields = _job(state, data["seeds"][0]["job"]["id"])["fields"]
    status, _h, data = mt.api(s, "POST", "/api/characters", body=dict(fields, force=True))
    assert status == 201, data
    forced = _job(state, data["job"]["id"])["fields"]
    assert "seed_folder" not in forced and forced["force"] is True


# --- Review Focus 1: phone and camera exports in Characters folder mode ---------------------------------

def test_sf_review_focus_1_timestamp_and_non_latin_names_as_characters(env):
    s, ws, state = env["srv"], env["ws"], env["state"]
    names = ["20241101_123456.jpg", "20241101_123457.jpg", "日本.png", "Café ☕ día.png"]
    status, _h, data = _cpost(s, _cbody(ws, _seeds(s, names), False))
    assert status == 201, data
    assert [r["character"] for r in data["seeds"]] == ["char", "char-2", "char-3", "cafe-dia"]
    for row, name in zip(data["seeds"], names):
        job = _job(state, row["job"]["id"])
        assert job["argv"][job["argv"].index("create") + 1] == row["character"]
        assert job["fields"]["seed_folder"]["name"] == name
    queued = mt.api(s, "GET", "/api/jobs")[2]["queued"]
    assert [j["seed_folder"]["name"] for j in queued] == names
