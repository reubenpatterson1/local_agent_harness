"""Tests for the location library in movie-ui (docs/superpowers/specs/
2026-10-29-location-lora-design.md, Section 5, test table 6.8: LU1-LU14, with the plan's Review
Focus pin): the /api/locations routes and jobs, Compose's --location fields and V1 rule 12c, the
LoRAs & Models tab's --no-arch-check and WARN lines, and the static page.

Run from the workspace root: python3 -m pytest -q -p no:cacheprovider tests/test_location_ui.py
Stdlib plus pytest. No test reads the real HOME, renders, trains, contacts a model server or
touches port 8178: every server is an in-test movie-ui server on 127.0.0.1 under a temporary HOME
(movie_ui_testutil), every tool it runs is a stub in a temporary workspace, and no job is ever
dispatched.
"""

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

import movie_ui_lib as lib  # noqa: E402
import movie_ui_server as srv  # noqa: E402
import movie_ui_testutil as mt  # noqa: E402

DESC = ("a narrow cobbled harbour street lined with weathered stone warehouses, green wooden "
        "shutters, rusted mooring rings and faded red fishmonger signs above granite quays")
NEW_ROUTES = [("GET", "/api/locations"), ("POST", "/api/locations"),
              ("GET", "/api/locations/harbour-street"), ("PATCH", "/api/locations/harbour-street"),
              ("POST", "/api/locations/harbour-street/train"),
              ("POST", "/api/locations/harbour-street/regenerate")]


@pytest.fixture
def env(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCATION_LIBRARY_DIR", str(tmp_path / "locations"))
    monkeypatch.setenv("CHARACTER_LIBRARY_DIR", str(tmp_path / "characters"))
    monkeypatch.setenv("LORA_CATALOG_DIR", str(tmp_path / "loras"))
    state = mt.set_home(monkeypatch, tmp_path)
    ws = mt.make_stub_workspace(tmp_path)
    running = mt.Running(state)
    yield {"state": state, "ws": ws, "tmp": str(tmp_path), "srv": running}
    running.close()
    mt.kill_everything(state)


def _job_argv(state, payload):
    return lib.read_job(lib.job_dir(state, payload["job"]["id"]))["argv"]


def _upload(s, data):
    status, _h, payload = mt.api(s, "POST", "/api/uploads", raw=data,
                                 headers={"Content-Type": "image/png"})
    assert status == 201
    return payload["upload_id"]


# --- LU1, LU2: the routes, the token and PATCH bodies (L4.1) -----------------------------------

def test_lu1_the_location_routes_need_the_token(env):
    s = env["srv"]
    assert len(srv.ROUTES) == 55
    assert [(m, sample) for m, _r, _n, sample in srv.ROUTES if "/locations" in sample] == NEW_ROUTES
    for method, regex, name, sample in srv.ROUTES:
        if (method, sample) not in NEW_ROUTES:
            continue
        assert re.fullmatch(regex, sample) and hasattr(srv.MovieUIHandler, name), name
        body = {} if method in ("POST", "PUT", "PATCH") else None
        for token in (None, "wrong-token"):
            status, _h, payload = mt.api(s, method, sample, body=body, token=token)
            assert (status, payload) == (401, {"error": "missing or invalid token"}), (method, sample)
    assert mt.api(s, "DELETE", "/api/locations/harbour-street")[0] == 405


def test_lu2_patch_bodies_are_read(env):
    s, ws = env["srv"], env["ws"]
    status, _h, payload = mt.api(s, "PATCH", "/api/locations/harbour-street")
    assert (status, payload) == (411, {"error": "Content-Length required"})
    status, _h, payload = mt.api(s, "PATCH", "/api/locations/harbour-street", raw=b"{bad",
                                 headers={"Content-Type": "application/json"})
    assert (status, payload) == (400, {"error": "invalid JSON body"})
    status, _h, payload = mt.api(s, "PATCH", "/api/locations/harbour-street",
                                 body={"ws": ws, "description": DESC})
    assert status == 200 and payload["run"]["exit_code"] == 0


# --- LU3, LU4: the list and the detail (L4.2) --------------------------------------------------

def test_lu3_the_location_list(env):
    s, ws = env["srv"], env["ws"]
    assert mt.api(s, "GET", "/api/locations?ws=" + ws)[2] == {"locations": []}
    mt.stub_config(ws, {"location list": {"stdout": (
        "NAME             TRIGGER          STATUS    SOURCE VIDEO STILLS DESCRIPTION\n"
        "bad-one          (invalid: invalid location.json for bad-one: top level: x)\n"
        "harbour-street   harboplc         trained   text   yes   no     " + DESC + "\n"
        "old-mill         oldmiplc         untrained photos no    no     an old mill by a weir\n")}})
    assert mt.api(s, "GET", "/api/locations?ws=" + ws)[2] == {"locations": [
        {"name": "bad-one", "invalid": "invalid location.json for bad-one: top level: x"},
        {"name": "harbour-street", "trigger": "harboplc", "status": "trained", "source": "text",
         "video": True, "stills": False, "description": DESC, "invalid": None},
        {"name": "old-mill", "trigger": "oldmiplc", "status": "untrained", "source": "photos",
         "video": False, "stills": False, "description": "an old mill by a weir", "invalid": None}]}
    mt.stub_config(ws, {"location list": {"exit": 1, "stderr": "Traceback\n"}})
    assert mt.api(s, "GET", "/api/locations?ws=" + ws)[0] == 502


def test_lu4_the_location_detail(env):
    s, ws, state = env["srv"], env["ws"], env["state"]
    ldir = os.path.join(env["tmp"], "locations", "harbour-street")
    for sub in ("stills", "tests"):
        os.makedirs(os.path.join(ldir, sub))
    items = [{"n": n, "source": "generated", "kept": n != 2} for n in (1, 2, 3)]
    with open(os.path.join(ldir, "manifest.json"), "w") as f:
        json.dump({"items": items}, f)
    for rel in ("stills/loc_01.png", "stills/loc_03.png", "contact_sheet.jpg",
                "tests/video_lora.mp4"):
        open(os.path.join(ldir, rel), "wb").close()
    record = {"name": "harbour-street", "status": "trained", "source": "text"}
    files = "files:\n  ok       %s\n  MISSING  %s\n" % (os.path.join(ldir, "location.json"),
                                                       os.path.join(ldir, "lora", "x.safetensors"))
    mt.stub_config(ws, {"location show harbour-street": {
        "stdout": json.dumps(record, indent=2) + "\n" + files}})
    detail = mt.api(s, "GET", "/api/locations/harbour-street?ws=" + ws)[2]
    assert detail == {
        "location": record,
        "files": [{"status": "ok", "path": os.path.join(ldir, "location.json")},
                  {"status": "MISSING", "path": os.path.join(ldir, "lora", "x.safetensors")}],
        "manifest": items,
        "contact_sheet": os.path.join(ldir, "contact_sheet.jpg"),
        "stills": [os.path.join(ldir, "stills", "loc_01.png"),
                   os.path.join(ldir, "stills", "loc_03.png")],
        "tests": {"video_lora": os.path.join(ldir, "tests", "video_lora.mp4"),
                  "video_control": None},
        "last_create_fields": None}
    status, _h, payload = mt.api(s, "POST", "/api/locations",
                                 body={"ws": ws, "name": "harbour-street", "description": DESC})
    assert status == 201
    detail = mt.api(s, "GET", "/api/locations/harbour-street?ws=" + ws)[2]
    assert detail["last_create_fields"]["description"] == DESC
    os.remove(os.path.join(ldir, "manifest.json"))
    detail = mt.api(s, "GET", "/api/locations/harbour-street?ws=" + ws)[2]
    assert (detail["manifest"], detail["stills"]) == (None, [])
    mt.stub_config(ws, {"location show harbour-street": {"exit": 2,
                                                         "stderr": "Error: unknown location\n"}})
    assert mt.api(s, "GET", "/api/locations/harbour-street?ws=" + ws)[0] == 502


# --- LU5-LU9: create, edit, regenerate and train jobs (L4.1, L4.2) -----------------------------

def test_lu5_create_argv_and_errors(env):
    s, ws, state = env["srv"], env["ws"], env["state"]
    status, _h, payload = mt.api(s, "POST", "/api/locations",
                                 body={"ws": ws, "name": "harbour-street", "description": DESC,
                                       "trigger": "harbtrg", "seed": 7, "force": True})
    assert status == 201 and payload["job"]["kind"] == "location-create"
    assert payload["job"]["character"] == "harbour-street"
    argv = _job_argv(state, payload)
    assert os.path.basename(argv[1]) == "location"
    assert argv[2:] == ["create", "harbour-street", "--description", DESC, "--trigger", "harbtrg",
                        "--seed", "7", "--force"]
    one, two = _upload(s, mt.PNG), _upload(s, mt.PNG + b"x")
    status, _h, payload = mt.api(s, "POST", "/api/locations",
                                 body={"ws": ws, "name": "old-mill", "photo_uploads": [one, two],
                                       "description": "", "trigger": "", "seed": None})
    assert status == 201
    assert _job_argv(state, payload)[2:] == [
        "create", "old-mill", "--photo", os.path.join(state, "uploads", one),
        "--photo", os.path.join(state, "uploads", two)]
    missing = "0" * 64 + ".png"
    status, _h, payload = mt.api(s, "POST", "/api/locations", body={
        "ws": ws, "name": "Bad", "photo_uploads": [missing], "description": "a short one",
        "trigger": "Bad", "seed": -1, "force": "yes"})
    assert (status, payload["error"]) == (400, "invalid fields")
    assert payload["errors"] == ["location name must match [a-z][a-z0-9-]{1,23}",
                                 "photo upload %s not found" % missing,
                                 "description must be 15 to 40 words",
                                 "trigger must match [a-z][a-z0-9]{3,15}",
                                 "seed must be an integer from 0 to 2147483647",
                                 "force must be true or false"]
    for body, errors in (({"photo_uploads": [one] * 25}, ["give at most 24 photos"]),
                         ({"photo_uploads": "x"}, ["photo_uploads must be a list of upload IDs",
                                                   "give a description or at least one photo"]),
                         ({}, ["give a description or at least one photo"]),
                         ({"description": "-" + DESC}, ["description must not start with '-'"]),
                         ({"description": DESC.replace(" shutters,", "\nshutters,")},
                          ["description must be one line"]),
                         ({"description": DESC + "\x00"}, ["description contains invalid characters"]),
                         ({"description": 5}, ["description must be a string"])):
        status, _h, payload = mt.api(s, "POST", "/api/locations",
                                     body=dict({"ws": ws, "name": "old-mill"}, **body))
        assert (status, payload["errors"]) == (400, errors), body


def test_lu6_patch_saves_a_photo_description(env):
    s, ws = env["srv"], env["ws"]
    status, _h, payload = mt.api(s, "PATCH", "/api/locations/old-mill",
                                 body={"ws": ws, "description": DESC})
    assert status == 200 and mt.stub_calls(ws)[-1]["argv"] == ["edit", "old-mill",
                                                                "--description", DESC]
    text = ("Error: location harbour-street is a text location: its stills are drawn from its "
            "description; run bin/location create harbour-street --regenerate --description TEXT "
            "(add --force when it is trained)\n")
    mt.stub_config(ws, {"location edit": {"exit": 2, "stderr": text}})
    status, _h, payload = mt.api(s, "PATCH", "/api/locations/harbour-street",
                                 body={"ws": ws, "description": DESC})
    assert (status, payload["error"]) == (400, text[len("Error: "):].strip())
    assert payload["run"]["exit_code"] == 2
    mt.stub_config(ws, {"location edit": {"exit": 1, "stderr": "Traceback\n"}})
    status, _h, payload = mt.api(s, "PATCH", "/api/locations/harbour-street",
                                 body={"ws": ws, "description": DESC})
    assert (status, payload["error"]) == (502, "location exited 1")
    status, _h, payload = mt.api(s, "PATCH", "/api/locations/harbour-street",
                                 body={"ws": ws, "description": "a quay"})
    assert (status, payload) == (400, {"error": "invalid fields",
                                       "errors": ["description must be 15 to 40 words"]})


def test_lu7_regenerate_argv(env):
    s, ws, state = env["srv"], env["ws"], env["state"]
    for body, tail in (({"new_seed": True}, ["--new-seed"]), ({"seed": 9}, ["--seed", "9"]),
                       ({"description": DESC, "force": True}, ["--description", DESC, "--force"]),
                       ({}, [])):
        status, _h, payload = mt.api(s, "POST", "/api/locations/harbour-street/regenerate",
                                     body=dict({"ws": ws}, **body))
        assert status == 201 and payload["job"]["kind"] == "location-regenerate", body
        assert _job_argv(state, payload)[2:] == ["create", "harbour-street", "--regenerate"] + tail
    for body, errors in (({"seed": 3, "new_seed": True}, ["give seed or new_seed, not both"]),
                         ({"seed": True}, ["seed must be an integer from 0 to 2147483647"]),
                         ({"new_seed": "yes"}, ["new_seed must be true or false"]),
                         ({"force": 1}, ["force must be true or false"]),
                         ({"description": "a quay"}, ["description must be 15 to 40 words"])):
        status, _h, payload = mt.api(s, "POST", "/api/locations/harbour-street/regenerate",
                                     body=dict({"ws": ws}, **body))
        assert (status, payload) == (400, {"error": "invalid fields", "errors": errors}), body


def test_lu8_train_argv(env):
    s, ws, state = env["srv"], env["ws"], env["state"]
    status, _h, payload = mt.api(s, "POST", "/api/locations/harbour-street/train", body={"ws": ws})
    assert (status, payload) == (400, {"error": "invalid fields",
                                       "errors": ["choose video, stills or both"]})
    status, _h, payload = mt.api(s, "POST", "/api/locations/harbour-street/train",
                                 body={"ws": ws, "video": True, "stills": True, "force": True})
    argv = _job_argv(state, payload)
    assert status == 201 and payload["job"]["kind"] == "location-train"
    assert argv[0] == os.path.join(ws, "bin", "location-train-vlm")
    assert argv[2:] == ["harbour-street", "--video", "--stills", "--force"]
    status, _h, payload = mt.api(s, "POST", "/api/locations/harbour-street/train",
                                 body={"ws": ws, "video": "yes"})
    assert (status, payload["errors"]) == (400, ["video must be true or false"])


def test_lu9_job_vlm_policy(tmp_path):
    for kind, policy in (("location-create", "required"), ("location-regenerate", "required"),
                         ("location-train", "forbidden")):
        assert lib.job_vlm(kind, {}, str(tmp_path), None) == policy, kind


# --- LU10, Review Focus 5: Compose (L4.3) ------------------------------------------------------

def test_lu10_compose_fields_flags_and_rule_12c(env):
    state = env["state"]
    assert len(lib.FIELD_FLAGS) == 30
    keys = [k for k, _flags in lib.FIELD_FLAGS]
    assert keys[keys.index("characters") + 1:keys.index("characters") + 3] == [
        "locations", "location_strength"]
    assert dict(lib.FIELD_FLAGS)["locations"] == ("--location",)
    assert dict(lib.FIELD_FLAGS)["location_strength"] == ("--location-strength",)
    assert (lib.DEFAULT_FIELDS["locations"], lib.DEFAULT_FIELDS["location_strength"]) == ([], None)
    fields = mt.fields(mt.WS, characters=["kyra"], locations=["harbour-street", "temple-gate"],
                       location_strength=0.6)
    argv = lib.build_argv(fields, mt.WS, state)
    at = argv.index("--character")
    assert argv[at:at + 7] == ["--character", "kyra", "--location", "harbour-street",
                               "--location", "temple-gate", "--location-strength"]
    assert argv[at + 7] == "0.6"
    assert lib.validate_fields(fields, mt.WS, state) == []
    no_strength = lib.build_argv(mt.fields(mt.WS, locations=["harbour-street"]), mt.WS, state)
    assert "--location-strength" not in no_strength and "--location" in no_strength
    for overrides, errors in (
            (dict(locations=["a1", "b1", "c1", "d1"]), ["locations must be at most 3 distinct location names"]),
            (dict(locations=["a1", "a1"]), ["locations must be at most 3 distinct location names"]),
            (dict(locations=["Bad"]), ["locations must be at most 3 distinct location names"]),
            (dict(locations="harbour-street"), ["locations must be at most 3 distinct location names",
                                                ]),
            (dict(locations=["a1"], location_strength=1.5), ["location strength must be a number in (0, 1]"]),
            (dict(locations=["a1"], location_strength=True), ["location strength must be a number in (0, 1]"]),
            (dict(location_strength=0.5), ["location strength needs at least one location"]),
            (dict(locations=["a1"], mode="no_stills"), ["locations need chained or shots mode"])):
        found = lib.validate_fields(mt.fields(mt.WS, **overrides), mt.WS, state)
        assert [e for e in found if "location" in e] == errors, overrides


def test_review_focus_5_fields_saved_before_the_upgrade(env):
    state = env["state"]
    old = dict(mt.fields(mt.WS, characters=["kyra"]))
    del old["locations"], old["location_strength"]
    composed = lib.compose_fields(old)
    assert (composed["locations"], composed["location_strength"]) == ([], None)
    assert lib.validate_fields(composed, mt.WS, state) == []
    assert "--location" not in lib.build_argv(composed, mt.WS, state)
    assert "--location-strength" not in lib.build_argv(composed, mt.WS, state)


# --- LU11, LU12: the LoRAs & Models tab (L4.5) -------------------------------------------------

def test_lu11_lora_add_no_arch_check(env):
    s, ws = env["srv"], env["ws"]
    add = {"ws": ws, "path": "/l/pan.safetensors", "id": "pan", "kind": "motion", "target": "video",
           "base_models": ["M1"], "triggers": [], "description": "a pan", "use_when": "pans",
           "avoid_when": "", "default_strength": 0.8, "strength_range": [0.5, 1], "rank": None,
           "alpha": 8}
    for value, tail in ((True, ["--alpha", "8", "--no-arch-check"]), (False, ["--alpha", "8"]),
                        (None, ["--alpha", "8"])):
        body = dict(add) if value is None else dict(add, no_arch_check=value)
        assert mt.api(s, "POST", "/api/loras", body=body)[0] == 200
        assert mt.stub_calls(ws)[-1]["argv"][-len(tail):] == tail, value
    assert mt.api(s, "POST", "/api/loras", body=dict(add, no_arch_check="yes"))[:3:2] == (
        400, {"error": "no_arch_check must be true or false"})


def test_lu12_parse_verify_collects_warnings():
    assert srv.parse_verify(
        "OK ink\nFAIL pan: sha256 changed\nWARN pan: 44 of 1724 modules are outside the "
        "transformer blocks and are skipped in low-RAM mode; render with --no-low-ram to use "
        "them\nOK comfy\nWARN comfy: 2 of 9 modules are outside\nverified 3 entries: 1 problem(s)\n") == [
        {"id": "ink", "ok": True, "problems": []},
        {"id": "pan", "ok": False, "problems": ["sha256 changed"],
         "warnings": ["44 of 1724 modules are outside the transformer blocks and are skipped in "
                      "low-RAM mode; render with --no-low-ram to use them"]},
        {"id": "comfy", "ok": True, "problems": [], "warnings": ["2 of 9 modules are outside"]}]


# --- LU14: a location job's progress (L4.1) ----------------------------------------------------

def test_lu14_a_location_job_reports_elapsed_and_last_line(env):
    parser = lib.ProgressParser("location-create", {"name": "harbour-street"})
    parser.feed(b"=== generate: 24 stills ===\n=== check ===\n")
    started = "2026-10-29T10:00:00Z"
    snap = parser.snapshot({"id": "x", "kind": "location-create", "workspace": env["ws"],
                            "story_id": None}, {"started": started}, env["state"],
                           now=lib.parse_utc(started) + 5)
    assert (snap["kind"], snap["elapsed_s"], snap["last_line"]) == ("location-create", 5,
                                                                   "=== check ===")


# --- LU13: the static page (L4.4, L4.5) --------------------------------------------------------

LO_IDS = ("lo-list", "lo-name", "lo-description", "lo-words", "lo-trigger", "lo-seed", "lo-photos",
          "lo-angles-note", "lo-create", "lo-create-status", "lo-detail", "lo-title", "lo-sheet",
          "lo-stills", "lo-desc-edit", "lo-desc-save", "lo-regen", "lo-force", "lo-accept",
          "lo-status", "lo-train-form", "lo-train-video", "lo-train-stills", "lo-train-force",
          "lo-train", "lo-train-reason", "lo-tests")


def test_lu13_the_static_page():
    static = os.path.join(WS, "static", "movie-ui")
    with open(os.path.join(static, "index.html"), encoding="utf-8") as f:
        html = f.read()
    with open(os.path.join(static, "app.js"), encoding="utf-8") as f:
        js = f.read()
    for element in ("tab-locations", "panel-locations", "c-locations", "c-locations-note",
                    "c-location-strength", "l-no-arch-check") + LO_IDS:
        assert html.count('id="%s"' % element) == 1, element
        if element not in ("panel-locations", "tab-locations", "lo-angles-note"):
            assert '"#%s' % element in js, element
    assert html.index('id="tab-characters"') < html.index('id="tab-locations"') < html.index(
        'id="tab-actions"')
    assert html.index('id="c-characters"') < html.index('id="c-locations"') < html.index(
        'id="c-actions"')
    assert ('<p id="lo-angles-note" class="muted">Every extra still re-shoots one of your photos '
            "from a new viewpoint at a new time of day, weather or season. Edits can only guess "
            "at what your photos do not show, so for a varied dataset, upload 3-5 photos taken "
            "from different spots. Without photos, the 24 stills are drawn from the "
            "description.</p>") in html
    assert '<select id="c-locations" multiple size="3"></select>' in html
    assert ('<input id="c-location-strength" type="number" min="0.05" max="1" step="0.05" '
            'placeholder="0.8">') in html
    assert '<textarea id="lo-description" rows="3" cols="70"></textarea>' in html
    assert ('<input id="lo-photos" type="file" multiple accept="image/png,image/jpeg,image/webp">'
            in html)
    assert ('<label><input id="l-no-arch-check" type="checkbox"> Skip architecture check</label> '
            '<span class="muted">The LoRA is cataloged even if bin/lora-check says it does not fit '
            'the base model; a mismatched LoRA fails or does nothing at render.</span>') in html
    assert ('const TABS = ["compose", "stories", "batches", "characters", "locations", "actions", "loras", '
            '"jobs", "traces"];') in js
    assert ("loadCatalog(), loadCharacters(), loadLocations(), loadActions(), loadStories(), "
            "loadModels()") in js
    for text in ('"at most 3 locations"', '"with the LoRA"', '"without (control)"',
                 '"Save description"', '"Regenerate with this description"',
                 '"fewer than 12 stills kept; regenerate the dataset"', '" words (15-40)"',
                 "no_arch_check: $(\"#l-no-arch-check\").checked",
                 'location_strength: numberOrNull("#c-location-strength")',
                 '(r.ok ? "ok" : r.problems.join("; ")) + (r.warnings && r.warnings.length ? " | '
                 'warning: " + r.warnings.join("; ") : "")', "setupLocations();",
                 'if (name === "locations") { loadLocations(); }'):
        assert text in js, text
    for pattern in (r"\son[a-z]+=", r"style=", r"<script>"):
        assert not re.search(pattern, html), pattern
    node = shutil.which("node")
    if node:
        proc = subprocess.run([node, "--check", os.path.join(static, "app.js")],
                              capture_output=True, text=True, timeout=60)
        assert proc.returncode == 0, proc.stderr


def test_lu13b_force_resets_and_regenerate_confirms_lora_loss():
    with open(os.path.join(WS, "static", "movie-ui", "app.js"), encoding="utf-8") as f:
        app = f.read()
    assert app.count('$("#lo-force").checked = false;') == 1
    assert app.count('$("#lo-train-force").checked = false;') == 1
    assert app.count('" Its LoRAs are deleted."') == 1
    assert app.count("loraLossNote(") == 3
    assert 'with this description?" + loraLossNote(loc)' in app


def test_lu15_locations_refuse_story_legacy():
    base = {"locations": ["harbour-street"], "location_strength": None, "mode": "chained"}
    assert "locations need the story engine; turn off story legacy" in lib._rule_locations(
        dict(base, story_legacy=True))
    assert lib._rule_locations(dict(base, story_legacy=False)) == []
