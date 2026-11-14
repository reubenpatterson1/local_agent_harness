"""Tests for the movie-ui side of the Qwen edit models (docs/superpowers/specs/2026-11-03-qwen-edit-models-
design.md, Sections 8 and 9, test table 11.2: QET33-QET39, with the plan's Review Focus pins 4 and 5):
movie_ui_lib's fields, flags, argv, V1 rule 12d and phases; the server's 400/409 rules and forwarding for
Compose, Locations and Characters; the batch levels; and the static page.

Run from the workspace root: python3 -m pytest -q -p no:cacheprovider tests/test_movie_ui_qwen_edit.py

Rules (spec 11.1): the HTTP tests use the in-test server and the stub workspace of tests/movie_ui_testutil.py
under a temporary HOME (the env fixture). lib.seed_edit_check is a recorder that answers in seed models SQ18's
shape (every model and LoRA ok unless a test says otherwise) and lib.shared_checks a pass stub (one V2
record); the stub bin/ltx-movie --help prints the current help fixture, which lists the two seed-edit flags
(V1 rule 18; plan ruling R15). No test uses the real HOME,
renders, dispatches a job or contacts a server other than the in-test 127.0.0.1 one; none touches port 8177
or 8178. Stdlib plus pytest.
"""

import json
import os
import re
import shutil
import subprocess
import sys

import pytest

import movie_ui_testutil as mt
import movie_ui_batch as batch
import movie_ui_lib as lib
import movie_ui_seedgen as seedgen
import qwen_edit

WS = mt.WS
UP = "a" * 64 + ".png"
PASS_V2 = lib.check("V2", "render", "pass", "stub")
DESC = ("a narrow cobbled harbour street lined with weathered stone warehouses, green wooden "
        "shutters, rusted mooring rings and faded red fishmonger signs above granite quays")
SEL = {"qwen_model": "qwen21-q4", "loras": [{"id": "uncensored", "scale": 0.5}]}
PHOTO_ONLY = "qwen_model and loras apply only to photo locations"
SEED_ONLY = "qwen_model and loras apply only to seed-image characters"


def _probe(models=None, loras=None):
    """lib.seed_edit_check's models answer: every registry model and LoRA ok unless given."""
    found_models = dict((i, {"ok": True, "reason": None}) for i in seedgen.QWEN_MODEL_IDS)
    found_models.update(models or {})
    found_loras = dict((i, {"ok": True, "reason": None}) for i in seedgen.QWEN_LORA_IDS)
    found_loras.update(loras or {})
    return {"zimage": {"ok": True, "reason": None, "backend": "zimage"},
            "qwen": {"ok": True, "reason": None, "models": found_models, "loras": found_loras}}


def _clean_env(monkeypatch, tmp_path):
    """Spec 11.1: no HF_HUB_CACHE and no SEED_EDIT_* variable; HF_HOME and Z_IMAGE_HF_HOME under tmp_path."""
    for key in list(os.environ):
        if key.startswith("SEED_EDIT_"):
            monkeypatch.delenv(key)
    monkeypatch.delenv("HF_HUB_CACHE", raising=False)
    monkeypatch.setenv("HF_HOME", os.path.join(str(tmp_path), "hf"))
    monkeypatch.setenv("Z_IMAGE_HF_HOME", os.path.join(str(tmp_path), "zi"))


@pytest.fixture
def env(monkeypatch, tmp_path):
    monkeypatch.setenv("MOVIE_UI_VLM_LIFECYCLE", "0")
    monkeypatch.setenv("LOCATION_LIBRARY_DIR", str(tmp_path / "locations"))
    monkeypatch.setenv("CHARACTER_LIBRARY_DIR", str(tmp_path / "characters"))
    state = mt.set_home(monkeypatch, tmp_path)
    _clean_env(monkeypatch, tmp_path)
    ws = mt.make_stub_workspace(tmp_path)
    monkeypatch.setattr(lib, "shared_checks", lambda fields, ws_real, py=None: [PASS_V2])
    probes = {"answer": (_probe(), None), "calls": []}

    def seed_edit_check(ws_real, model_ids, lora_ids):
        probes["calls"].append(ws_real)
        return probes["answer"]

    monkeypatch.setattr(lib, "seed_edit_check", seed_edit_check)
    running = mt.Running(state)
    yield {"state": state, "ws": ws, "tmp": str(tmp_path), "srv": running, "probes": probes,
           "locations": str(tmp_path / "locations"), "characters": str(tmp_path / "characters")}
    running.close()
    mt.kill_everything(state)


def _upload(s, data=mt.PNG):
    status, _h, payload = mt.api(s, "POST", "/api/uploads", raw=data, headers={"Content-Type": "image/png"})
    assert status == 201, payload
    return payload["upload_id"]


def _job(state, payload):
    return lib.read_job(lib.job_dir(state, payload["job"]["id"]))


def _compose(ws, up, **overrides):
    body = mt.fields(ws, seed_upload=up, action="movie")
    body.update(overrides)
    return body


def _record(root, name, file_name, record):
    os.makedirs(os.path.join(root, name), exist_ok=True)
    with open(os.path.join(root, name, file_name), "w", encoding="utf-8") as f:
        json.dump(record, f)


# --- QET33 (QE52-QE54, QE69): fields, flags, argv, V1 rule 12d and the phases --------------------------------

def test_qet33_fields_flags_argv_rule_12d_and_phases(tmp_path, monkeypatch):
    state = mt.set_home(monkeypatch, tmp_path)
    _clean_env(monkeypatch, tmp_path)
    keys = list(lib.DEFAULT_FIELDS)
    assert keys[keys.index("seed_upload") + 1:keys.index("seed_upload") + 3] == ["seed_edit_model", "seed_edit_loras"]
    assert (lib.DEFAULT_FIELDS["seed_edit_model"], lib.DEFAULT_FIELDS["seed_edit_loras"]) == (None, None)
    assert lib.FIELD_FLAGS[-1] == ("seed_edit", ("--seed-edit-model", "--seed-edit-lora"))
    assert len(lib.FIELD_FLAGS) == 32
    seed_path = os.path.join(state, "uploads", UP)
    base = mt.fields(WS, seed_upload=UP, action="movie")
    argv = lib.build_argv(dict(base, seed_edit_model="qwen21-q4", seed_edit_loras=[{"id": "uncensored", "scale": 1}]),
                          WS, state)
    i = argv.index("--seed-image")
    assert argv[i - 4:i + 7] == ["--fps", "24", "--frames", "145", "--seed-image", seed_path, "--seed-edit-model",
                                 "qwen21-q4", "--seed-edit-lora", "uncensored=1.0", "--model"]
    argv = lib.build_argv(dict(base, seed_edit_model="as-is"), WS, state)
    i = argv.index("--seed-image")
    assert argv[i + 2:i + 5] == ["--seed-edit-model", "as-is", "--model"]
    assert "--seed-edit-model" not in lib.build_argv(base, WS, state)
    assert "--seed-edit-model" not in lib.build_argv(dict(base, seed_upload=None, width=704, height=448,
                                                          seed_edit_model="qwen21-q4"), WS, state)
    assert lib.qwen_edit_flags("--qwen-model", "--lora", "qwen21-q8", [{"id": "uncensored", "scale": 0.5},
                                                                     {"id": "viggle-turbo", "scale": 2}]) == [
        "--qwen-model", "qwen21-q8", "--lora", "uncensored=0.5", "--lora", "viggle-turbo=2.0"]
    py = sys.executable
    loc = {"name": "old-mill", "photo_uploads": [UP], "seed": 3, "force": True, "qwen_model": "qwen21-q4",
           "loras": [{"id": "uncensored", "scale": 0.5}]}
    assert lib.location_argv("location-create", loc, WS, state, py=py)[2:] == [
        "create", "old-mill", "--photo", seed_path, "--seed", "3", "--qwen-model", "qwen21-q4", "--lora",
        "uncensored=0.5", "--force"]
    old = dict((k, v) for k, v in loc.items() if k not in ("qwen_model", "loras"))
    assert lib.location_argv("location-create", old, WS, state, py=py)[2:] == [
        "create", "old-mill", "--photo", seed_path, "--seed", "3", "--force"]
    regen = {"name": "old-mill", "seed": None, "new_seed": True, "description": None, "force": True,
             "qwen_model": "qwen2511-bf16", "loras": []}
    assert lib.location_argv("location-regenerate", regen, WS, state, py=py)[2:] == [
        "create", "old-mill", "--regenerate", "--new-seed", "--qwen-model", "qwen2511-bf16", "--force"]
    char = {"name": "kyra", "phrase": "the woman", "seed_upload": UP, "class_noun": None, "trigger": None, "seed": 7,
            "force": False, "qwen_model": "qwen21-q4", "loras": [{"id": "uncensored", "scale": 1.0}]}
    assert lib.character_argv("character-create", char, WS, state, py=py)[2:] == [
        "create", "kyra", "--phrase", "the woman", "--seed-image", seed_path, "--seed", "7", "--qwen-model",
        "qwen21-q4", "--lora", "uncensored=1.0", "--no-review"]
    assert lib.character_argv("character-regenerate", {"name": "kyra", "seed": 4, "qwen_model": "qwen21-q8",
                                                       "loras": []}, WS, state, py=py)[2:] == [
        "create", "kyra", "--regenerate", "--no-review", "--seed", "4", "--qwen-model", "qwen21-q8"]
    assert lib.character_argv("character-regenerate", {"name": "kyra", "seed": None}, WS, state, py=py)[2:] == [
        "create", "kyra", "--regenerate", "--no-review"]
    rule = lib._rule_seed_edit
    ok = {"seed_upload": UP, "seed_edit_model": "qwen21-q4", "seed_edit_loras": [{"id": "uncensored", "scale": 1}]}
    assert rule(ok) == [] and rule({"seed_upload": None, "seed_edit_model": None, "seed_edit_loras": None}) == []
    assert rule(dict(ok, seed_edit_model="as-is", seed_edit_loras=None)) == []
    model_text = "seed edit model must be as-is or a Qwen model ID"
    loras_text = "seed edit LoRAs must be a list of at most 4 {id, scale} items"
    for model in ("Bad ID", 5, "-x", "a" * 33):
        assert rule(dict(ok, seed_edit_model=model)) == [model_text], model
    for loras in ("uncensored", [{"id": "uncensored"}], [{"id": "uncensored", "scale": "1"}],
                  [{"id": "Uncensored", "scale": 1}], [{"id": "uncensored", "scale": 1}] * 5):
        assert rule(dict(ok, seed_edit_loras=loras)) == [loras_text], loras
    assert rule(dict(ok, seed_upload=None, seed_edit_loras=None)) == ["a seed edit model needs a seed image"]
    assert rule(dict(ok, seed_edit_model="as-is", seed_edit_loras=[])) == [
        "seed edit LoRAs need a seed edit model other than as-is"]
    assert rule(dict(ok, seed_edit_model=None, seed_edit_loras=[])) == [
        "seed edit LoRAs need a seed edit model other than as-is"]
    movie = {"action": "movie", "mode": "chained", "seed_upload": UP}
    assert lib.job_phases("movie", dict(movie, seed_edit_model="qwen21-q4")) == ["0", "1", "1b", "1c", "2", "3", "4"]
    for model in (None, "as-is"):
        assert lib.job_phases("movie", dict(movie, seed_edit_model=model)) == ["0", "1", "1b", "2", "3", "4"]
    assert lib.job_phases("movie", dict(movie, seed_upload=None, seed_edit_model="qwen21-q4")) == [
        "1", "1b", "2", "3", "4"]
    assert lib.job_phases("story", dict(movie, seed_edit_model="qwen21-q4")) == ["0", "1"]
    found = lib.PHASE_RE.match("=== Phase 1c: seed edit ===")
    assert found and (found.group(1), found.group(2)) == ("1c", "seed edit")
    assert lib.PHASE_RE.match("=== Phase 1b: release the story server ===").group(1) == "1b"
    assert seedgen.qwen_selection(None, None) == ("qwen21-q4", [{"id": "uncensored", "scale": 1.0}], None)
    assert seedgen.qwen_selection("qwen21-q4", []) == ("qwen21-q4", [], None)
    assert seedgen.qwen_selection("flux", None, "seed_edit_model", "seed_edit_loras") == (
        None, None, "unknown seed_edit_model flux")
    assert seedgen.qwen_selection("qwen21-q4", "x", "seed_edit_model", "seed_edit_loras") == (
        None, None, "seed_edit_loras must be a list of {id, scale}")


# --- QET34 (QE56, QE57): Compose over HTTP ----------------------------------------------------------------------

def test_qet34_compose_rules_and_forwarding(env):
    s, ws, state, probes = env["srv"], env["ws"], env["state"], env["probes"]
    up = _upload(s)
    q8 = ("mflux-community/qwen-image-2-1-mflux-q8@f5c8cc79a674 is not in /z or /h "
          "(run bin/seed-edit-setup --model qwen21-q8)")
    cases = [({"seed_edit_model": "flux"}, "unknown seed_edit_model flux"),
             ({"seed_edit_model": "qwen21-q4", "seed_edit_loras": "uncensored"},
              "seed_edit_loras must be a list of {id, scale}"),
             ({"seed_edit_model": "qwen21-q4", "seed_edit_loras": [{"id": "uncensored"}]},
              "seed_edit_loras must be a list of {id, scale}"),
             ({"seed_edit_model": "qwen21-q4", "seed_edit_loras": [{"id": "nope", "scale": 1}]}, "unknown LoRA nope"),
             ({"seed_edit_model": "qwen21-q4", "seed_edit_loras": [{"id": "uncensored", "scale": 1},
                                                                    {"id": "uncensored", "scale": 2}]},
              "LoRA uncensored is listed twice"),
             ({"seed_edit_model": "qwen2511-q4", "seed_edit_loras": [{"id": "uncensored", "scale": 1}]},
              "LoRA uncensored is for Qwen-Image-2.1, not Qwen-Image-Edit-2511 q4 (Lightning)"),
             ({"seed_edit_model": "qwen21-q4", "seed_edit_loras": [{"id": "uncensored", "scale": 0}]},
              "LoRA uncensored scale must be a number above 0 and at most 2")]
    for overrides, text in cases:
        for path in ("/api/preview", "/api/jobs"):
            status, _h, payload = mt.api(s, "POST", path, body=_compose(ws, up, **overrides))
            assert (status, payload) == (400, {"error": text}), (path, overrides)
    assert lib.list_job_ids(state) == [] and probes["calls"] == []
    status, _h, payload = mt.api(s, "POST", "/api/preview", body=_compose(ws, None, seed_edit_model="qwen21-q4"))
    assert status == 200 and "a seed edit model needs a seed image" in payload["errors"]
    for story_id, model in (("plain-seed", None), ("as-is-seed", "as-is")):
        status, _h, payload = mt.api(s, "POST", "/api/jobs", body=_compose(ws, up, story_id=story_id,
                                                                           seed_edit_model=model))
        assert status == 201, payload
        argv = _job(state, payload)["argv"]
        assert ("--seed-edit-model" in argv) == (model is not None)
        if model is not None:
            assert argv[argv.index("--seed-edit-model") + 1] == "as-is"
    assert probes["calls"] == []
    probes["answer"] = (_probe(models={"qwen21-q8": {"ok": False, "reason": q8}}), None)
    status, _h, payload = mt.api(s, "POST", "/api/jobs", body=_compose(ws, up, story_id="q8-seed",
                                                                       seed_edit_model="qwen21-q8"))
    assert (status, payload["error"]) == (409, "Qwen-Image-2.1 q8 is unavailable: " + q8)
    assert len(lib.list_job_ids(state)) == 2 and probes["calls"] == [ws]
    status, _h, payload = mt.api(s, "POST", "/api/jobs", body=_compose(ws, up, story_id="story-seed", action="story",
                                                                       seed_edit_model="qwen21-q8"))
    assert status == 201 and len(probes["calls"]) == 1
    status, _h, payload = mt.api(s, "POST", "/api/jobs", body=_compose(
        ws, up, story_id="q4-seed", seed_edit_model="qwen21-q4", seed_edit_loras=[{"id": "uncensored", "scale": 1}]))
    assert status == 201 and len(probes["calls"]) == 2
    job = _job(state, payload)
    assert (job["fields"]["seed_edit_model"], job["fields"]["seed_edit_loras"]) == (
        "qwen21-q4", [{"id": "uncensored", "scale": 1.0}])
    i = job["argv"].index("--seed-edit-model")
    assert job["argv"][i:i + 4] == ["--seed-edit-model", "qwen21-q4", "--seed-edit-lora", "uncensored=1.0"]
    assert job["argv"][i - 2] == "--seed-image"
    seeds = [{"name": "alpha.png", "upload_id": _upload(s, mt.PNG + b"a")},
             {"name": "beta.png", "upload_id": _upload(s, mt.PNG + b"b")}]
    folder = dict(mt.fields(ws, story_id="", action="movie", seed_edit_model="qwen21-q8"), seeds=seeds, preview=True)
    status, _h, payload = mt.api(s, "POST", "/api/jobs/seed-folder", body=folder)
    assert status == 200 and len(probes["calls"]) == 2, payload
    jobs = len(lib.list_job_ids(state))
    status, _h, payload = mt.api(s, "POST", "/api/jobs/seed-folder", body=dict(folder, preview=False))
    assert (status, payload["error"]) == (409, "Qwen-Image-2.1 q8 is unavailable: " + q8)
    assert len(probes["calls"]) == 3 and len(lib.list_job_ids(state)) == jobs


# --- QET35 (QE58): Locations over HTTP ---------------------------------------------------------------------------

def test_qet35_locations(env):
    s, ws, state, probes = env["srv"], env["ws"], env["state"], env["probes"]
    one, two = _upload(s, mt.PNG + b"1"), _upload(s, mt.PNG + b"2")
    body = {"ws": ws, "name": "old-mill", "photo_uploads": [one, two]}
    status, _h, payload = mt.api(s, "POST", "/api/locations", body=body)
    assert status == 201 and probes["calls"] == []
    job = _job(state, payload)
    assert job["argv"][2:] == ["create", "old-mill", "--photo", os.path.join(state, "uploads", one), "--photo",
                               os.path.join(state, "uploads", two)]
    assert "qwen_model" not in job["fields"] and "loras" not in job["fields"]
    status, _h, payload = mt.api(s, "POST", "/api/locations", body=dict(body, name="dock-one", **SEL))
    assert status == 201 and probes["calls"] == [ws]
    job = _job(state, payload)
    assert job["argv"][-4:] == ["--qwen-model", "qwen21-q4", "--lora", "uncensored=0.5"]
    assert (job["fields"]["qwen_model"], job["fields"]["loras"]) == ("qwen21-q4", [{"id": "uncensored", "scale": 0.5}])
    status, _h, payload = mt.api(s, "POST", "/api/locations", body=dict({"ws": ws, "name": "harbour-street",
                                                                         "description": DESC}, **SEL))
    assert (status, payload["errors"]) == (400, [PHOTO_ONLY])
    status, _h, payload = mt.api(s, "POST", "/api/locations", body=dict(body, name="bad-one", qwen_model="flux"))
    assert (status, payload["errors"]) == (400, ["unknown qwen_model flux"])
    probes["answer"] = (_probe(loras={"uncensored": {"ok": False, "reason": "gone"}}), None)
    status, _h, payload = mt.api(s, "POST", "/api/locations", body=dict(body, name="no-lora", **SEL))
    assert (status, payload["error"]) == (409, "LoRA Uncensored (abenzerps) is unavailable: gone")
    probes["answer"] = (_probe(), None)
    _record(env["locations"], "harbour-street", "location.json", {"source": "text", "photos": []})
    _record(env["locations"], "old-mill", "location.json",
            {"source": "photos", "photos": [{"path": None, "sha256": "0" * 64}] * 2})
    status, _h, payload = mt.api(s, "POST", "/api/locations/harbour-street/regenerate",
                                 body=dict({"ws": ws, "new_seed": True}, **SEL))
    assert (status, payload["errors"]) == (400, [PHOTO_ONLY])
    status, _h, payload = mt.api(s, "POST", "/api/locations/old-mill/regenerate",
                                 body=dict({"ws": ws, "new_seed": True}, **SEL))
    assert status == 201
    assert _job(state, payload)["argv"][2:] == ["create", "old-mill", "--regenerate", "--new-seed", "--qwen-model",
                                                "qwen21-q4", "--lora", "uncensored=0.5"]
    status, _h, payload = mt.api(s, "POST", "/api/locations/old-mill/regenerate", body={"ws": ws, "new_seed": True})
    assert status == 201 and _job(state, payload)["argv"][2:] == ["create", "old-mill", "--regenerate", "--new-seed"]
    probes["answer"] = (_probe(models={"qwen21-q4": {"ok": False, "reason": "not here"}}), None)
    status, _h, payload = mt.api(s, "POST", "/api/locations/old-mill/regenerate", body=dict({"ws": ws}, **SEL))
    assert (status, payload["error"]) == (409, "Qwen-Image-2.1 q4 is unavailable: not here")


# --- QET36 (QE59): Characters over HTTP --------------------------------------------------------------------------

def test_qet36_characters(env):
    s, ws, state, probes = env["srv"], env["ws"], env["state"], env["probes"]
    sel = {"qwen_model": "qwen21-q4", "loras": [{"id": "uncensored", "scale": 1}]}
    base = {"ws": ws, "name": "kyra", "phrase": "the woman in grey", "seed_upload": _upload(s)}
    status, _h, payload = mt.api(s, "POST", "/api/characters", body=dict(base, **sel))
    assert status == 201 and probes["calls"] == [ws]
    job = _job(state, payload)
    assert (job["fields"]["qwen_model"], job["fields"]["loras"]) == ("qwen21-q4", [{"id": "uncensored", "scale": 1.0}])
    assert job["argv"][-5:] == ["--qwen-model", "qwen21-q4", "--lora", "uncensored=1.0", "--no-review"]
    status, _h, payload = mt.api(s, "POST", "/api/characters", body=dict(
        {"ws": ws, "name": "ronin", "phrase": "the ronin", "descriptor": "a lean man with a topknot",
         "class_noun": "man"}, **sel))
    assert (status, payload["errors"]) == (400, [SEED_ONLY])
    probes["answer"] = (_probe(models={"qwen21-q4": {"ok": False, "reason": "not here"}}), None)
    status, _h, payload = mt.api(s, "POST", "/api/characters", body=dict(base, name="kyra-two", **sel))
    assert (status, payload["error"]) == (409, "Qwen-Image-2.1 q4 is unavailable: not here")
    probes["answer"] = (_probe(), None)
    seeds = [{"name": "alpha.png", "upload_id": _upload(s, mt.PNG + b"a")},
             {"name": "beta.png", "upload_id": _upload(s, mt.PNG + b"b")}]
    folder = {"ws": ws, "name": "", "phrase": "the stranger", "seed": 7, "seeds": seeds, "preview": False}
    status, _h, payload = mt.api(s, "POST", "/api/characters/seed-folder", body=dict(folder, qwen_model="qwen21-q8",
                                                                                     loras=[]))
    assert status == 201 and payload["queued"] == 2, payload
    for row in payload["seeds"]:
        job = lib.read_job(lib.job_dir(state, row["job"]["id"]))
        assert (job["fields"]["qwen_model"], job["fields"]["loras"]) == ("qwen21-q8", [])
        assert job["argv"][-3:] == ["--qwen-model", "qwen21-q8", "--no-review"]
    status, _h, payload = mt.api(s, "POST", "/api/characters/seed-folder", body=dict(folder, qwen_model="flux"))
    assert (status, payload) == (400, {"error": "unknown qwen_model flux"})
    status, _h, payload = mt.api(s, "POST", "/api/characters/seed-folder", body=dict(folder, phrase="the walker"))
    assert status == 201 and payload["queued"] == 2
    for row in payload["seeds"]:
        fields = lib.read_job(lib.job_dir(state, row["job"]["id"]))["fields"]
        assert set(fields) == {"name", "phrase", "class_noun", "descriptor", "trigger", "seed", "seed_upload",
                               "force", "ws", "seed_folder"}
    _record(env["characters"], "ronin", "character.json", {"name": "ronin", "source": {"type": "descriptor"}})
    _record(env["characters"], "kyra", "character.json",
            {"name": "kyra", "source": {"type": "seed_image", "path": "/x/seed.png"}})
    status, _h, payload = mt.api(s, "POST", "/api/characters/ronin/regenerate", body=dict({"ws": ws}, **sel))
    assert (status, payload["errors"]) == (400, [SEED_ONLY])
    status, _h, payload = mt.api(s, "POST", "/api/characters/kyra/regenerate", body=dict({"ws": ws, "seed": 4}, **sel))
    assert status == 201
    assert _job(state, payload)["argv"][2:] == ["create", "kyra", "--regenerate", "--no-review", "--seed", "4",
                                                "--qwen-model", "qwen21-q4", "--lora", "uncensored=1.0"]
    status, _h, payload = mt.api(s, "POST", "/api/characters/kyra/regenerate", body={"ws": ws})
    assert status == 201 and _job(state, payload)["argv"][2:] == ["create", "kyra", "--regenerate", "--no-review"]


# --- QET37 (QE60): the batch levels, groups and merge ------------------------------------------------------------

def test_qet37_the_batch_levels_groups_and_merge():
    assert set(batch.FIELD_LEVELS) | set(batch.FIXED_KEYS) == set(lib.DEFAULT_FIELDS)
    assert (len(batch.FIELD_LEVELS), len(batch.FIXED_KEYS), len(lib.DEFAULT_FIELDS)) == (28, 5, 33)
    assert (batch.FIELD_LEVELS["seed_edit_model"], batch.FIELD_LEVELS["seed_edit_loras"]) == ("stills", "stills")
    assert batch.GROUPS == (("panels", "length"),
                            ("width", "height", "seed_upload", "seed_edit_model", "seed_edit_loras", "extra_refs"))
    seeded = lib.compose_fields({"ws": "/ws", "action": "movie", "story_id": "s1", "narrative": "N", "seed_upload": UP,
                                 "seed_edit_model": "qwen21-q4", "seed_edit_loras": [{"id": "uncensored", "scale": 1.0}]})

    def variant(settings):
        return {"label": "v1", "settings": settings, "prompt": {"append": "", "replace": [], "per_story": {}}}

    for settings in ({"width": 768, "height": 512}, {"height": 512}, {"seed_upload": None}):
        fork = batch.merge(seeded, variant(settings), "s1", None, "/ws")[1]
        assert (fork["seed_edit_model"], fork["seed_edit_loras"]) == (None, None), settings
    fork = batch.merge(seeded, variant({"panels": 12}), "s1", None, "/ws")[1]
    assert (fork["seed_edit_model"], fork["seed_upload"]) == ("qwen21-q4", UP)


# --- Review Focus 4: a photo location made before this feature regenerates on its old model ------------------

def test_qe_review_focus_4_a_legacy_photo_location_keeps_its_model(env):
    s, ws, state, probes = env["srv"], env["ws"], env["state"], env["probes"]
    _record(env["locations"], "old-mill", "location.json",
            {"source": "photos", "photos": [{"path": None, "sha256": "0" * 64}] * 2})
    legacy = {"ws": ws, "new_seed": True, "qwen_model": "qwen2511-bf16", "loras": []}
    bf16 = "needs a host with at least 64 GiB of memory (this host has 48.0 GiB)"
    probes["answer"] = (_probe(models={"qwen2511-bf16": {"ok": False, "reason": bf16}}), None)
    status, _h, payload = mt.api(s, "POST", "/api/locations/old-mill/regenerate", body=legacy)
    assert (status, payload["error"]) == (409, "Qwen-Image-Edit-2511 bf16 (Lightning, diffusers) is unavailable: " + bf16)
    probes["answer"] = (_probe(), None)
    status, _h, payload = mt.api(s, "POST", "/api/locations/old-mill/regenerate", body=legacy)
    assert status == 201
    job = _job(state, payload)
    assert job["argv"][2:] == ["create", "old-mill", "--regenerate", "--new-seed", "--qwen-model", "qwen2511-bf16"]
    assert (job["fields"]["qwen_model"], job["fields"]["loras"]) == ("qwen2511-bf16", [])
    status, _h, payload = mt.api(s, "POST", "/api/locations/old-mill/regenerate",
                                 body=dict(legacy, loras=[{"id": "uncensored", "scale": 1}]))
    assert (status, payload["errors"]) == (400, [
        "LoRA uncensored is for Qwen-Image-2.1, not Qwen-Image-Edit-2511 bf16 (Lightning, diffusers)"])


# --- Review Focus 5: the selection survives the request -> argv -> tool round trip ------------------------------

ROUND_TRIPS = [("qwen21-q4", [{"id": "viggle-turbo", "scale": 2}, {"id": "uncensored", "scale": 1e-06}]),
               ("qwen21-q8", [{"id": "uncensored", "scale": 0.1 + 0.2}]), ("qwen21-bf16", []), ("qwen2511-q4", []),
               ("qwen2511-bf16", []), ("qwen21-q4", None), (None, None)]


def _flags(argv, model_flag, lora_flag):
    i = argv.index(model_flag)
    return argv[i + 1], [argv[k + 1] for k in range(i, len(argv) - 1) if argv[k] == lora_flag]


def test_qe_review_focus_5_the_selection_round_trip(tmp_path, monkeypatch):
    state = mt.set_home(monkeypatch, tmp_path)
    _clean_env(monkeypatch, tmp_path)
    for model_id, loras in ROUND_TRIPS:
        clean_model, clean_loras, error = seedgen.qwen_selection(model_id, loras)
        assert error is None, (model_id, loras)
        want = qwen_edit.settings(clean_model, clean_loras)
        builders = [
            (lib.location_argv("location-create", {"name": "old-mill", "photo_uploads": [UP], "seed": None,
                                                   "qwen_model": clean_model, "loras": clean_loras}, WS, state),
             "--qwen-model", "--lora"),
            (lib.character_argv("character-create", {"name": "kyra", "phrase": "the woman", "seed_upload": UP,
                                                     "qwen_model": clean_model, "loras": clean_loras}, WS, state),
             "--qwen-model", "--lora"),
            (lib.build_argv(mt.fields(WS, seed_upload=UP, action="movie", seed_edit_model=clean_model,
                                      seed_edit_loras=clean_loras), WS, state), "--seed-edit-model", "--seed-edit-lora")]
        for argv, model_flag, lora_flag in builders:
            model_arg, lora_args = _flags(argv, model_flag, lora_flag)
            got = qwen_edit.cli_selection(model_arg, lora_args, model_flag, lora_flag)
            assert qwen_edit.settings(*got) == want, (model_id, loras, model_flag)


# --- QET38, QET39 (QE61-QE63, QE67, QE68): the picker on the static page ------------------------------------

PREFIXES = ("lo-cq", "lo-rq", "ch-cq", "ch-rq", "c-sq")
SUFFIXES = ("qwen-box", "qwen-model", "steps", "loras", "qwen-note", "reason")
QWEN_BOX = ('      <div id="se-qwen-box" class="wide" hidden>\n'
            '        <label>Qwen model <select id="se-qwen-model"></select></label>\n'
            '        <span id="se-steps" class="muted"></span>\n'
            '        <div id="se-loras" class="se-loras"></div>\n'
            '        <p id="se-qwen-note" class="muted"></p>\n'
            '      </div>\n')   # SQT22's Seeds box, unchanged
MOUNTS = ('const SEED_PICKER = qwenPicker("se", false);', 'const LOCATION_PICKER = qwenPicker("lo-cq", false);',
          'const LOCATION_REGEN_PICKER = qwenPicker("lo-rq", false);',
          'const CHARACTER_PICKER = qwenPicker("ch-cq", false);',
          'const CHARACTER_REGEN_PICKER = qwenPicker("ch-rq", false);', 'const COMPOSE_PICKER = qwenPicker("c-sq", true);')


def _page():
    static = os.path.join(WS, "static", "movie-ui")
    with open(os.path.join(static, "index.html"), encoding="utf-8") as f:
        html = f.read()
    with open(os.path.join(static, "app.js"), encoding="utf-8") as f:
        js = f.read()
    return static, html, js


def _function(js, head):
    """The text of the app.js function starting with head, through its closing line."""
    start = js.index(head)
    return js[start:js.index("\n  }\n", start) + len("\n  }\n")]


def test_qet38_the_picker_on_the_page():
    static, html, js = _page()
    for prefix in PREFIXES:
        for suffix in SUFFIXES:
            assert html.count('id="%s-%s"' % (prefix, suffix)) == 1, (prefix, suffix)
    wrapper = html.index('<div data-field="seed_edit" class="wide">')
    assert html.index('id="c-folder-list"') < wrapper < html.index('id="c-sq-qwen-box"') < html.index(
        "</fieldset>", wrapper)
    assert '<span id="se-model-note" class="muted"></span>\n' + QWEN_BOX in html
    assert js.count("function qwenPicker(prefix, asIs) {") == 1 and '"Seed as-is (no edit)"' in js
    assert js.index("  function seedModelText(view) {") < js.index("  function qwenPicker(prefix, asIs) {")
    for line in MOUNTS:
        assert js.count(line) == 1, line
    assert 'function enabled(id) { return id === "as-is" || (Boolean(seedQwenEntry(id)) && !(probe(id) && probe(id).ok === false)); }' in js
    assert js.index('S.seeds = {source: null, natural: null, run: null, view: null, rows: {}, busy: false};') < js.index(
        MOUNTS[0])
    for gone in ("function renderSeedQwen(", "function readSeedQwen(", "function seedLoraBody(", "S.seeds.qwen",
                 "qwenKey"):
        assert gone not in js, gone
    for name, text in (("index.html", html), ("app.js", js)):
        for pattern in (r"https?://", r"\son[a-z]+=", r"style=", r"\balert\(", r"\bconfirm\(", r"\bprompt\(",
                        r"\beval\(", r"new Function"):
            assert not re.search(pattern, text), (name, pattern)
    node = shutil.which("node")
    if node:
        proc = subprocess.run([node, "--check", os.path.join(static, "app.js")], capture_output=True, text=True,
                              timeout=60)
        assert proc.returncode == 0, proc.stderr


def test_qet39_the_compose_defaults_and_fields():
    _static, _html, js = _page()
    assert 'composeSeedDefault("seeds");' in _function(js, "  async function useSeed(run, n, status) {")
    assert 'composeSeedDefault("upload");' in _function(js, "  async function onSeedFile() {")
    assert 'composeSeedDefault("folder")' in _function(js, "  function onFolderPick(box) {")
    assert ('COMPOSE_PICKER.select(f.seed_edit_model || "as-is", f.seed_edit_loras || []);'
            in _function(js, "  function fillCompose(fields) {"))
    body = _function(js, "  function composeFields(action) {")
    assert "const seedEdit = composeSeedEditActive() ? COMPOSE_PICKER.selection() : null;" in body
    assert ('seed_edit_model: seedEdit ? seedEdit.model : null, seed_edit_loras: seedEdit && seedEdit.model !== '
            '"as-is" ? seedEdit.loras : null,') in body
    assert js.count("function composeSeedDefault(origin) {") == 1
    assert js.count("function composeSeedEditActive() {") == 1
