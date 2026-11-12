"""Tests for the shots Z-Image engine, movie-ui side (docs/superpowers/specs/2026-11-11-shots-zimage-engine-design.md,
SZ11-SZ16): with --shots, --seed-image and --seed-edit-model as-is, panel 1 is the seed and every other panel a
Z-Image still.

Run from the workspace root: python3 -m pytest -q -p no:cacheprovider tests/test_movie_ui_shots_zimage.py

No test loads a model, renders, dispatches a job or contacts a server other than the in-test 127.0.0.1 one; the
page tests evaluate app.js functions with node when it is installed. Stdlib and pytest.
"""

import json
import os
import re
import shutil
import subprocess

import pytest

import movie_ui_testutil as mt
import movie_ui_lib as lib
import test_movie_ui_shots_seed as uss
from test_movie_ui_shots_seed import v1_env  # noqa: F401
from test_movie_ui_qwen_edit import _compose, _function, _job, _upload, env  # noqa: F401

NEEDS_CHOICE = ("a seed image in shots mode needs a stills engine: a Qwen edit model (every panel's still is an edit "
                "of the seed) or as-is (panel 1 is the seed and Z-Image renders every other panel)")
SHOTS = dict(seed_upload=uss.UP, mode="shots")
STILLS = [{"id": None, "path": "/a.safetensors", "strength": 1, "kind": None}]
STATIC = os.path.join(mt.WS, "static", "movie-ui")
ENGINE_HTML = ('      <option value="no_stills" data-field="no_stills">no stills</option>\n    </select></label>\n'
               '    <label>Stills engine <select id="c-engine"></select></label> '
               '<span id="c-engine-note" class="muted"></span>\n')
BUTTONS_ENGINE = ('    show($("#c-check-seams-box"), mode === "chained");\n'
                  '    const engine = composeEngineUpdate(mode);\n'
                  '    COMPOSE_PICKER.update();\n')
BUTTONS_BOX = ('    const zimageSeed = shotsSeed && engine === "zimage";\n'
               '    show($("#c-sq-qwen-box"), seedEditOn && !zimageSeed);\n'
               '    const seedEditReason = seedEditOn && !zimageSeed ? COMPOSE_PICKER.reason() : "";\n')
FIELDS_AS_IS = ('    if (seedEdit && out.mode === "shots" && S.composeEngine === "zimage") {\n'
                '      out.seed_edit_model = "as-is";\n'
                '      out.seed_edit_loras = null;\n'
                '    }\n'
                '    return out;\n')
DEFAULT_RESET = '    S.composeEngine = "qwen";\n    S.seedOrigin = origin;\n'
FILL_LINE = ('    S.composeEngine = f.mode === "shots" && f.seed_upload && f.seed_edit_model === "as-is" ? "zimage" : '
             '"qwen";\n')
LISTEN_LINE = '    $("#c-engine").addEventListener("change", function () { S.composeEngine = $("#c-engine").value; });\n'
CHAINED = ('    if (mode === "chained") {\n'
           '      return [seeded ? ["seed", "The seed: panel 1 is the seed, as-is or a Qwen edit (below)"]\n')
VALUES = "].map(function (c) { return composeEngines(c[0], c[1]).map(function (o) { return o[0]; }); })));"
FAKE_DOM = (
    'function makeSelect() {\n'
    '  const s = {options: [], value: "", disabled: false};\n'
    '  Object.defineProperty(s, "textContent", {set: function () { s.options = []; }, get: function () { return ""; }});\n'
    '  s.appendChild = function (o) { s.options.push(o); };\n'
    '  return s;\n'
    '}\n'
    'const E = {"#c-res-seed": {checked: false}, "#c-res-folder": {checked: false}, "#c-engine": makeSelect(),\n'
    '  "#c-engine-note": {textContent: ""}};\n'
    'function $(selector) { return E[selector]; }\n'
    'const document = {createElement: function () { return {value: "", textContent: ""}; }};\n'
    'const S = {seedUpload: null, composeEngine: "qwen"};\n'
    'function run(mode, seedRadio, upload, folder, engine) {\n'
    '  E["#c-res-seed"].checked = seedRadio;\n'
    '  S.seedUpload = upload;\n'
    '  E["#c-res-folder"].checked = folder;\n'
    '  S.composeEngine = engine;\n'
    '  const value = composeEngineUpdate(mode);\n'
    '  const select = E["#c-engine"];\n'
    '  return [value, select.disabled, select.options.map(function (o) { return o.value; }),\n'
    '    E["#c-engine-note"].textContent === ZIMAGE_SEED_NOTE];\n'
    '}\n')


def _page():
    with open(os.path.join(STATIC, "index.html"), encoding="utf-8") as f:
        html = f.read()
    with open(os.path.join(STATIC, "app.js"), encoding="utf-8") as f:
        js = f.read()
    return html, js


def _node(script):
    """node -e script's stdout parsed as JSON (60 s); asserts a zero exit."""
    proc = subprocess.run([shutil.which("node"), "-e", script], capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


# --- SZ11 (ZE11): V1 rule 8 ---------------------------------------------------------------------------------

def test_sz11_v1_rule_8(v1_env):
    assert uss._errors(v1_env, seed_edit_model="as-is", **SHOTS) == []
    assert uss._errors(v1_env, seed_edit_model="as-is", stills_loras=STILLS, **SHOTS) == []
    assert uss._errors(v1_env, seed_edit_model=None, **SHOTS) == [NEEDS_CHOICE]
    assert uss._errors(v1_env, seed_edit_model="as-is", story_legacy=True, **SHOTS) == [uss.NEEDS_ENGINE]
    assert uss._errors(v1_env, seed_edit_model="qwen21-q4", stills_loras=STILLS, **SHOTS) == [uss.NO_STILLS_LORAS]
    assert uss._errors(v1_env, seed_edit_model="as-is", seed_edit_loras=uss.UNC, **SHOTS) == [
        "seed edit LoRAs need a seed edit model other than as-is"]


# --- SZ12 (ZE11): the argv and the phases are unchanged code -------------------------------------------------

def test_sz12_argv_and_phases(v1_env):
    state = v1_env["state"]
    f = mt.fields(mt.WS, action="movie", seed_edit_model="as-is", **SHOTS)
    argv = lib.build_argv(f, mt.WS, state)
    i = argv.index("--seed-image")
    assert argv[i:i + 4] == ["--seed-image", os.path.join(state, "uploads", uss.UP), "--seed-edit-model", "as-is"]
    assert "--seed-edit-lora" not in argv
    assert argv.count("--shots") == 1
    assert lib.job_phases("movie", f) == ["0", "1", "1b", "2", "3", "4"]


# --- SZ13 (ZE11): a job and a seed folder on the Z-Image engine ---------------------------------------------

def test_sz13_jobs_and_seed_folders(env):
    s, ws, state, probes = env["srv"], env["ws"], env["state"], env["probes"]
    up = _upload(s)
    status, _h, payload = mt.api(s, "POST", "/api/jobs",
                                 body=_compose(ws, up, story_id="shots-z", mode="shots", seed_edit_model="as-is"))
    assert status == 201, payload
    argv = _job(state, payload)["argv"]
    assert "--shots" in argv and argv[argv.index("--seed-edit-model") + 1] == "as-is"
    assert probes["calls"] == []
    seeds = [{"name": "alpha.png", "upload_id": _upload(s, mt.PNG + b"a")},
             {"name": "beta.png", "upload_id": _upload(s, mt.PNG + b"b")}]
    folder = dict(mt.fields(ws, story_id="", action="movie", mode="shots", seed_edit_model="as-is"), seeds=seeds,
                  preview=False)
    jobs = len(lib.list_job_ids(state))
    status, _h, payload = mt.api(s, "POST", "/api/jobs/seed-folder", body=folder)
    assert status == 201, payload
    assert [r["status"] for r in payload["seeds"]] == ["ok", "ok"] and payload["queued"] == 2
    assert len(lib.list_job_ids(state)) == jobs + 2
    for row in payload["seeds"]:
        argv = lib.read_job(lib.job_dir(state, row["job"]["id"]))["argv"]
        assert "--shots" in argv and argv[argv.index("--seed-edit-model") + 1] == "as-is"
    status, _h, payload = mt.api(s, "POST", "/api/jobs/seed-folder", body=dict(folder, seed_edit_model=None))
    assert status == 409, payload
    assert [(r["status"], r["reason"]) for r in payload["seeds"]] == [("refused", NEEDS_CHOICE)] * 2
    assert len(lib.list_job_ids(state)) == jobs + 2
    assert probes["calls"] == []


# --- SZ14 (ZE12-ZE14): the static page -------------------------------------------------------------------------

def test_sz14_the_page():
    html, js = _page()
    assert html.count(ENGINE_HTML) == 1
    for text in ("function composeEngines(mode, seeded) {", "function composeEngineUpdate(mode) {",
                 'seedOrigin: null, composeEngine: "qwen", '):
        assert js.count(text) == 1, text
    buttons = _function(js, "  function updateComposeButtons() {")
    assert BUTTONS_ENGINE in buttons and BUTTONS_BOX in buttons
    assert FIELDS_AS_IS in _function(js, "  function composeFields(action) {")
    assert DEFAULT_RESET in _function(js, "  function composeSeedDefault(origin) {")
    assert FILL_LINE in _function(js, "  function fillCompose(fields) {")
    assert LISTEN_LINE in _function(js, "  function setupCompose() {")
    for name, text in (("index.html", html), ("app.js", js)):
        for pattern in (r"https?://", r"\son[a-z]+=", r"style=", r"\balert\(", r"\bconfirm\(", r"\bprompt\(",
                        r"\beval\(", r"new Function"):
            assert not re.search(pattern, text), (name, pattern)
    node = shutil.which("node")
    if node:
        proc = subprocess.run([node, "--check", os.path.join(STATIC, "app.js")], capture_output=True, text=True,
                              timeout=60)
        assert proc.returncode == 0, proc.stderr


# --- SZ15 (ZE12): the engines of each cell, evaluated ----------------------------------------------------------

def test_sz15_the_engine_cells():
    if not shutil.which("node"):
        pytest.skip("node is not installed")
    body = _function(_page()[1], "  function composeEngines(mode, seeded) {")
    script = body + ('console.log(JSON.stringify([["no_stills",false],["chained",false],["chained",true],'
                     '["shots",false],["shots",true]' + VALUES)
    assert _node(script) == [["none"], ["zimage"], ["seed"], ["zimage"], ["qwen", "zimage"]]


# --- SZ16 (ZE12, ZE13; Section 9 Q2): no Z-Image where a seed is edited outside shots mode --------------------

def test_sz16_no_zimage_where_a_seed_is_edited():
    js = _page()[1]
    body = _function(js, "  function composeEngines(mode, seeded) {")
    assert CHAINED in body
    assert body.count('"zimage"') == 3
    assert body.count('["zimage", "Z-Image: panel 1 is the seed') == 1
    assert body.index('return seeded ? [["qwen"') < body.index('["zimage", "Z-Image: panel 1 is the seed')
    assert 'out.mode === "shots" && S.composeEngine === "zimage"' in _function(js, "  function composeFields(action) {")
    assert ('f.mode === "shots" && f.seed_upload && f.seed_edit_model === "as-is"'
            in _function(js, "  function fillCompose(fields) {"))
    if shutil.which("node"):
        cells = _node(body + 'console.log(JSON.stringify([["chained",true],["no_stills",true],["shots",true]' + VALUES)
        assert cells == [["seed"], ["none"], ["qwen", "zimage"]]
        assert [c for c in cells if "zimage" in c and len(c) > 1] == [["qwen", "zimage"]]


# --- Review Focus 4: a redo job queued with the Z-Image engine ------------------------------------------------

def test_sz_review_focus_4_a_redo_job_on_the_zimage_engine(env):
    s, ws, state, probes = env["srv"], env["ws"], env["state"], env["probes"]
    up = _upload(s)
    sdir = os.path.join(ws, "generated", "stories", "shots-z-redo")
    os.makedirs(sdir)
    with open(os.path.join(sdir, "story.md"), "w", encoding="utf-8") as f:
        f.write("x")
    body = _compose(ws, up, story_id="shots-z-redo", action="redo", redo=[2], mode="shots", seed_edit_model="as-is")
    status, _h, payload = mt.api(s, "POST", "/api/jobs", body=body)
    assert status == 201, payload
    argv = _job(state, payload)["argv"]
    assert argv[argv.index("--redo") + 1] == "2" and argv[argv.index("--seed-edit-model") + 1] == "as-is"
    assert "--seed-edit-lora" not in argv and "--shots" in argv
    assert probes["calls"] == []
    assert lib.job_phases("movie", body) == ["0", "1", "1b", "redo", "2", "3", "4"]
    assert lib.job_phases("story", body) == ["0", "1"]


# --- Review Focus 5: the engine select follows the cell, whatever the remembered choice -----------------------

def test_sz_review_focus_5_the_engine_select_follows_the_cell():
    if not shutil.which("node"):
        pytest.skip("node is not installed")
    js = _page()[1]
    update = _function(js, "  function composeEngineUpdate(mode) {")
    start = js.index("  const ZIMAGE_SEED_NOTE = ")
    code = js[start:js.index(update) + len(update)]
    runs = [["shots", True, "u.png", False, "qwen"], ["shots", True, "u.png", False, "zimage"],
            ["chained", True, "u.png", False, "zimage"], ["shots", False, None, True, "zimage"],
            ["shots", True, None, False, "zimage"], ["no_stills", False, None, False, "zimage"],
            ["shots", True, "u.png", False, "zimage"]]
    script = FAKE_DOM + code + (
        "console.log(JSON.stringify(%s.map(function (r) { return run.apply(null, r); })));" % json.dumps(runs))
    assert _node(script) == [["qwen", False, ["qwen", "zimage"], False],
                             ["zimage", False, ["qwen", "zimage"], True],
                             ["seed", True, ["seed"], False],
                             ["zimage", False, ["qwen", "zimage"], True],
                             ["zimage", True, ["zimage"], False],
                             ["none", True, ["none"], False],
                             ["zimage", False, ["qwen", "zimage"], True]]


# --- SZ17 / SZ18: the real composeFields override and fillCompose restore, run in node ----------------------

FAKE_COMPOSE = (
    'const E = {};\n'
    'function $(selector) {\n'
    '  if (!E[selector]) { E[selector] = {value: "", checked: false, options: [], selectedOptions: []}; }\n'
    '  return E[selector];\n'
    '}\n'
    'const S = {ws: "w", seedUpload: null, composeEngine: "qwen"};\n'
    'const PICKED = {model: "qwen-edit-x", loras: [{id: "l"}]};\n'
    'const COMPOSE_PICKER = {selection: function () { return PICKED; }, select: function () {}};\n'
    'function composeSeedEditActive() { return true; }\n'
    'function textOrNull() { return null; }\n'
    'function numberOrNull() { return null; }\n'
    'function collectLoras() { return []; }\n'
    'function clear(x) { return x; }\n'
    'function syncResPreset() {}\n'
    'function fillModelSelect() {}\n'
    'function loraRow() {}\n'
    'function updateComposeButtons() {}\n'
    'function preview() {}\n')


def _compose_page_code():
    js = _page()[1]
    return (FAKE_COMPOSE + _function(js, "  function composeFields(action) {")
            + _function(js, "  function fillCompose(fields) {"))


def test_sz17_compose_fields_sends_as_is_for_zimage_shots_only():
    if not shutil.which("node"):
        pytest.skip("node is not installed")
    script = _compose_page_code() + (
        'function run(mode, engine) {\n'
        '  $("#c-mode").value = mode;\n'
        '  $("#c-res-seed").checked = true;\n'
        '  S.seedUpload = "up1";\n'
        '  S.composeEngine = engine;\n'
        '  const out = composeFields("story");\n'
        '  return [out.mode, out.seed_upload, out.seed_edit_model, out.seed_edit_loras];\n'
        '}\n'
        'console.log(JSON.stringify([run("shots", "zimage"), run("chained", "zimage"), run("shots", "qwen")]));')
    assert _node(script) == [["shots", "up1", "as-is", None],
                             ["chained", "up1", "qwen-edit-x", [{"id": "l"}]],
                             ["shots", "up1", "qwen-edit-x", [{"id": "l"}]]]


def test_sz18_fill_compose_restores_zimage_only_for_shots_with_seed():
    if not shutil.which("node"):
        pytest.skip("node is not installed")
    script = _compose_page_code() + (
        'function run(fields) {\n'
        '  S.composeEngine = "qwen";\n'
        '  fillCompose(fields);\n'
        '  return S.composeEngine;\n'
        '}\n'
        'console.log(JSON.stringify([\n'
        '  run({mode: "shots", seed_upload: "up1", seed_edit_model: "as-is"}),\n'
        '  run({mode: "chained", seed_upload: "up1", seed_edit_model: "as-is"}),\n'
        '  run({mode: "shots", seed_upload: null, seed_edit_model: "as-is"}),\n'
        '  run({mode: "shots", seed_upload: "up1", seed_edit_model: "qwen-edit-x"})]));')
    assert _node(script) == ["zimage", "qwen", "qwen", "qwen"]
