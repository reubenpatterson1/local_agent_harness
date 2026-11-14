"""Tests for the movie-ui side of the extra reference images (docs/superpowers/specs/2026-11-13-extra-reference-
images-design.md, XR16-XR20, tests XR-T19-XR-T23): movie_ui_lib's field, flag, argv and V1 rule 12e; the server's
model cap; the batch level, group and merge; and the Compose control on the static page.

Run from the workspace root: python3 -m pytest -q -p no:cacheprovider tests/test_movie_ui_extra_refs.py

No test loads a model, renders, dispatches a job or contacts a server other than the in-test 127.0.0.1 one; the
page tests evaluate app.js functions with node when it is installed. Stdlib and pytest.
"""

import json
import os
import shutil

import pytest

import movie_ui_testutil as mt
import movie_ui_batch as batch
import movie_ui_lib as lib
from test_movie_ui_qwen_edit import _compose, _function, _page, _upload, env  # noqa: F401
from test_movie_ui_shots_zimage import _compose_page_code, _node

WS = mt.WS
UP = "a" * 64 + ".png"
U2 = "b" * 64 + ".png"
U3 = "c" * 64 + ".jpg"
UNC = [{"id": "uncensored", "scale": 1.0}]
XR = [{"upload_id": U2, "caption": "the sword"}, {"upload_id": U3, "caption": None}]
SHAPE = "extra references must be a list of at most 9 {upload_id, caption} items"
CAPTION = "extra reference %d: caption must be 1 to 60 characters with no ':' and no control characters"
DISTINCT = "extra references must be distinct images"
NEEDS_SEED = "extra references need a seed image and a Qwen seed edit model (not as-is)"
LOW_RAM = ("extra references need No low-RAM mode (--no-low-ram): in low-RAM mode a Qwen edit takes at most 2 "
           "pictures")


@pytest.fixture
def state(monkeypatch, tmp_path):
    """The state directory under a temporary HOME, with the uploads UP, U2 and U3 written."""
    home = mt.set_home(monkeypatch, tmp_path)
    for name in (UP, U2, U3):
        with open(os.path.join(home, "uploads", name), "wb") as f:
            f.write(mt.PNG)
    return home


def _base(**overrides):
    out = dict(seed_upload=UP, action="movie", seed_edit_model="qwen21-q4", seed_edit_loras=UNC, no_low_ram=True,
               extra_refs=[dict(i) for i in XR])
    out.update(overrides)
    return mt.fields(WS, **out)


# --- XR-T19 (XR16): the field, the flag and the argv ---------------------------------------------------------

def test_xrt19_fields_flags_and_argv(state):
    keys = list(lib.DEFAULT_FIELDS)
    assert keys[keys.index("seed_edit_loras") + 1] == "extra_refs"
    assert lib.DEFAULT_FIELDS["extra_refs"] == []
    assert len(lib.DEFAULT_FIELDS) == 33
    assert lib.FIELD_FLAGS[-2:] == (("extra_refs", ("--extra-ref",)),
                                    ("seed_edit", ("--seed-edit-model", "--seed-edit-lora")))
    assert len(lib.FIELD_FLAGS) == 32
    base = mt.fields(WS, seed_upload=UP, action="movie", seed_edit_model="qwen21-q4", seed_edit_loras=UNC,
                     no_low_ram=True, extra_refs=[{"upload_id": U2, "caption": " the sword "},
                                                  {"upload_id": U3, "caption": None}])
    argv = lib.build_argv(base, WS, state)
    i = argv.index("--seed-edit-lora")
    assert argv[i + 2:i + 6] == ["--extra-ref", os.path.join(state, "uploads", U2) + ":the sword", "--extra-ref",
                                 os.path.join(state, "uploads", U3)]
    assert lib.extra_ref_arg(state, {"upload_id": U2, "caption": "  "}) == os.path.join(state, "uploads", U2)
    assert "--extra-ref" not in lib.build_argv(dict(base, extra_refs=[]), WS, state)
    assert lib.compose_fields({})["extra_refs"] == []


# --- XR-T20 (XR17): V1 rule 12e ------------------------------------------------------------------------------

def test_xrt20_v1_rule_12e(state):
    def errors(**overrides):
        return lib._rule_extra_refs(_base(**overrides), state)

    assert errors() == []
    assert errors(extra_refs="x") == [SHAPE]
    assert errors(extra_refs=[{"upload_id": U2, "caption": None}] * 10) == [SHAPE]
    assert errors(extra_refs=[{"upload_id": U2}]) == [SHAPE]
    missing = "d" * 64 + ".png"
    assert errors(extra_refs=[{"upload_id": missing, "caption": None}]) == [
        "extra reference 1: upload %s not found" % missing]
    for caption in ("", "a:b", "x" * 61, "a\nb"):
        assert errors(extra_refs=[{"upload_id": U2, "caption": caption}]) == [CAPTION % 1], repr(caption)
    assert errors(extra_refs=[{"upload_id": U2, "caption": None}, {"upload_id": U2, "caption": None}]) == [DISTINCT]
    assert errors(seed_upload=None) == [NEEDS_SEED]
    assert errors(seed_edit_model="as-is") == [NEEDS_SEED]
    assert errors(seed_edit_model=None) == [NEEDS_SEED]
    assert errors(no_low_ram=False) == [LOW_RAM]
    found = lib.validate_fields(dict(_base(), no_low_ram=False), WS, state)
    assert LOW_RAM in found


# --- XR-T21 (XR18): the server's model cap and the preview ---------------------------------------------------

def test_xrt21_the_server_cap_and_preview(env):
    s, ws, state = env["srv"], env["ws"], env["state"]
    up = _upload(s)
    ids = [_upload(s, mt.PNG + bytes([n])) for n in (1, 2, 3)]

    def items(k):
        return [{"upload_id": i, "caption": None} for i in ids[:k]]

    cap3 = ("Qwen-Image-Edit-2511 bf16 (Lightning, diffusers) takes at most 3 reference images per edit (the seed "
            "and 2 extra references); this request has 3 extra references")
    body = _compose(ws, up, seed_edit_model="qwen2511-bf16", seed_edit_loras=[], no_low_ram=True,
                    extra_refs=items(3))
    assert mt.api(s, "POST", "/api/preview", body=body)[::2] == (400, {"error": cap3})
    status, _h, payload = mt.api(s, "POST", "/api/preview", body=dict(body, extra_refs=items(2)))
    assert status == 200 and payload["errors"] == []
    assert payload["command"].count("--extra-ref ") == 2
    one = _compose(ws, up, seed_edit_model="qwen2511-q4", seed_edit_loras=[], no_low_ram=True, extra_refs=items(1))
    assert mt.api(s, "POST", "/api/preview", body=one)[::2] == (400, {"error": (
        "Qwen-Image-Edit-2511 q4 (Lightning) reads only the first picture, so it takes no extra references")})
    assert mt.api(s, "POST", "/api/jobs", body=body)[::2] == (400, {"error": cap3})
    assert lib.list_job_ids(state) == []
    low = _compose(ws, up, seed_edit_model="qwen21-q4", seed_edit_loras=[], no_low_ram=False, extra_refs=items(2))
    status, _h, payload = mt.api(s, "POST", "/api/preview", body=low)
    assert status == 200 and payload["errors"] == [LOW_RAM]


# --- XR-T22 (XR20): the batch level, group and merge ---------------------------------------------------------

def test_xrt22_batch_levels_groups_and_merge(state):
    assert batch.FIELD_LEVELS["extra_refs"] == "stills"
    assert batch.GROUPS[1] == ("width", "height", "seed_upload", "seed_edit_model", "seed_edit_loras", "extra_refs")
    seeded = lib.compose_fields({"ws": "/ws", "action": "movie", "story_id": "s1", "narrative": "N",
                                 "seed_upload": UP, "seed_edit_model": "qwen21-q4", "seed_edit_loras": UNC,
                                 "no_low_ram": True, "extra_refs": XR})

    def variant(settings):
        return {"label": "v1", "settings": settings, "prompt": {"append": "", "replace": [], "per_story": {}}}

    assert batch.merge(seeded, variant({"panels": 12}), "s1", None, "/ws")[1]["extra_refs"] == XR
    for settings in ({"width": 768, "height": 512}, {"seed_upload": None}):
        assert batch.merge(seeded, variant(settings), "s1", None, "/ws")[1]["extra_refs"] == [], settings
    chained = dict(seeded, mode="chained", seed_edit_model="as-is")
    fork = batch.merge(chained, variant({"mode": "shots"}), "s1", None, "/ws")[1]
    assert fork["seed_edit_model"] is None and fork["extra_refs"] == []
    _clean, errors = batch.validate_request({"stories": ["s1"], "variants": [{"label": "v1",
                                                                              "settings": {"extra_refs": []}}]})
    assert not [e for e in errors if "cannot be changed" in e]
    assert batch.classify(seeded, dict(seeded, extra_refs=[]), "s1", "/ws", state, True)[0] == "stills"


# --- XR-T23 (XR19): the Compose control on the page ----------------------------------------------------------

U15 = ('          <div id="c-xr-box" data-field="extra_refs">\n'
       '            <h3>Extra references <button id="c-xr-add" type="button">Add image…</button></h3>\n'
       '            <input id="c-xr-file" type="file" accept="image/png,image/jpeg,image/webp" hidden>\n'
       '            <span id="c-xr-status" class="muted"></span>\n'
       '            <p id="c-xr-note" class="muted"></p>\n'
       '            <ol id="c-xr-list"></ol>\n'
       '          </div>\n')
FIELDS_LINE = ('      extra_refs: S.extrasOn ? S.extraRefs.map(function (x) { return {upload_id: x.upload_id, '
               'caption: x.caption.trim() || null}; }) : [],\n')
BUTTONS = '    composeExtrasUpdate();\n    // Seed-folder spec SD29: the folder mode of the Compose buttons.\n'
FILL = ('    S.extraRefs = (f.extra_refs || []).map(function (x) { return {upload_id: x.upload_id, caption: x.caption '
        '|| ""}; });\n    S.extraKey = "";\n')
SETUP = ('    $("#c-xr-add").addEventListener("click", function () { $("#c-xr-file").click(); });\n'
         '    $("#c-xr-file").addEventListener("change", onExtraFile);\n')


def test_xrt23_the_compose_control():
    static, html, js = _page()
    assert html.count(U15) == 1
    assert html.index('id="c-sq-shots-note"') < html.index('id="c-xr-box"') < html.index('id="c-sq-reason"')
    for head in ("function composeExtrasModel() {", "function composeExtrasUpdate() {",
                 "async function onExtraFile() {"):
        assert js.count(head) == 1, head
    assert js.count('composeEngine: "qwen", extraRefs: [], extraKey: "", extrasOn: false, ') == 1
    assert js.count(FIELDS_LINE) == 1
    assert _function(js, "  function updateComposeButtons() {").count(BUTTONS) == 1 and js.count(BUTTONS) == 1
    assert js.count(FILL) == 1 and js.count(SETUP) == 1
    assert ('const XR_LOW_RAM_NOTE = "Extra references need No low-RAM mode (under Advanced): in low-RAM mode every '
            'Qwen edit " +\n    "takes at most 2 pictures. Tick it only on a host with at least 96 GiB of memory.";'
            ) in js
    assert 'const XR_AS_IS_NOTE = "Extra references need a Qwen edit of the seed; the seed as-is is not edited.";' in js
    import re
    for name, text in (("index.html", html), ("app.js", js)):
        for pattern in (r"https?://", r"\son[a-z]+=", r"style=", r"\balert\(", r"\bconfirm\(", r"\bprompt\(",
                        r"\beval\(", r"new Function"):
            assert not re.search(pattern, text), (name, pattern)
    if not shutil.which("node"):
        pytest.skip("node is not installed")
    import subprocess
    proc = subprocess.run([shutil.which("node"), "--check", os.path.join(static, "app.js")], capture_output=True,
                          text=True, timeout=60)
    assert proc.returncode == 0, proc.stderr
    script = _compose_page_code() + (
        'S.extraRefs = [{upload_id: "u1", caption: " the sword "}, {upload_id: "u2", caption: ""}];\n'
        'S.extrasOn = true;\n'
        'const on = composeFields("story").extra_refs;\n'
        'S.extrasOn = false;\n'
        'const off = composeFields("story").extra_refs;\n'
        'fillCompose({extra_refs: [{upload_id: "u3", caption: null}]});\n'
        'console.log(JSON.stringify([on, off, S.extraRefs, S.extraKey]));')
    assert _node(script) == [[{"upload_id": "u1", "caption": "the sword"}, {"upload_id": "u2", "caption": None}], [],
                             [{"upload_id": "u3", "caption": ""}], ""]
