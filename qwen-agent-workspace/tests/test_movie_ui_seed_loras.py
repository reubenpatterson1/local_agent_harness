"""Tests for the custom edit LoRAs' server routes and page (docs/superpowers/specs/2026-11-17-custom-edit-loras-
design.md, Section 5.1: CL-T25-CL-T34, with the plan's Review Focus pin 5): POST and DELETE /api/seed-loras, the
seed_edit capability refresh, the triggered initial run.json prompt, old records after a remove, main's
environment, the "Add custom LoRA" form and the picker rows in app.js, and the unchanged batch forks.

Run from the workspace root: python3 -m pytest -q -p no:cacheprovider tests/test_movie_ui_seed_loras.py

Rules (spec 5.1): the HTTP tests use the env fixture (tests/test_movie_ui_seedgen.py's pattern): mt.set_home,
mt.make_stub_workspace and the in-test mt.Running server on 127.0.0.1, whose probe_ws is the stub workspace. The
workspace's bin/seed-edit is stub_seed_edit's (it counts its --probe runs in <ws>/probe_calls.txt). The registry
file is conftest's per-test isolation file. seed_lora_registry.fetch_model_info is patched (slr.fake_fetch), so
nothing contacts the Hugging Face API; node runs only where it is installed. No test loads a model, dispatches a
job or uses the real HOME.
Stdlib and pytest.
"""

import json
import os
import re
import shutil
import subprocess
import sys
import threading

import pytest

import movie_ui_testutil as mt
import movie_ui_batch as batch
import movie_ui_lib as lib
import movie_ui_seedgen as seedgen
import movie_ui_server as srv
import qwen_edit as qe
import test_seed_lora_registry as slr

WS = mt.WS
OK = {"ok": True, "reason": None}
OK_Z = {"ok": True, "reason": None, "backend": "zimage"}
LORA_ID = "user-anything-to-real-charact"
NO_LORAS = ("LoRA user-local: qwen2511-bf16 runs without LoRAs (its diffusers child loads only the built-in "
            "Lightning LoRA); use qwen2511-q4")
STUB = '''#!{python}
import sys
if sys.argv[1:] == ["--probe"]:
    with open({calls!r}, "a", encoding="utf-8") as f:
        f.write("probe\\n")
    sys.stdout.write({out!r} + "\\n")
'''


def qwen_probe(lora_ids):
    """A probe qwen entry: every registry model ok, and one ok entry per id of lora_ids."""
    return {"ok": True, "reason": None, "models": dict((i, OK) for i in seedgen.QWEN_MODEL_IDS),
            "loras": dict((i, OK) for i in lora_ids)}


OK_MODELS = {"zimage": OK_Z, "qwen": qwen_probe(seedgen.BUILTIN_QWEN_LORA_IDS)}


def stub_seed_edit(ws, models):
    """<ws>/bin/seed-edit as a stub: for --probe it appends one line to <ws>/probe_calls.txt and prints
    json.dumps(models). Returns its path."""
    path = os.path.join(ws, "bin", "seed-edit")
    with open(path, "w", encoding="utf-8") as f:
        f.write(STUB.format(python=sys.executable, calls=os.path.join(ws, "probe_calls.txt"), out=json.dumps(models)))
    os.chmod(path, 0o755)
    return path


def probe_count(ws):
    try:
        with open(os.path.join(ws, "probe_calls.txt"), encoding="utf-8") as f:
            return len(f.read().splitlines())
    except OSError:
        return 0


def clean_env(monkeypatch, tmp_path):
    """No HF_HUB_CACHE and no SEED_EDIT_* variable but SEED_EDIT_USER_LORAS (spec E2); HF_HOME and
    Z_IMAGE_HF_HOME under tmp_path."""
    for key in list(os.environ):
        if key.startswith("SEED_EDIT_") and key != "SEED_EDIT_USER_LORAS":
            monkeypatch.delenv(key)
    monkeypatch.delenv("HF_HUB_CACHE", raising=False)
    monkeypatch.setenv("HF_HOME", os.path.join(str(tmp_path), "hf"))
    monkeypatch.setenv("Z_IMAGE_HF_HOME", os.path.join(str(tmp_path), "zi"))


@pytest.fixture
def env(monkeypatch, tmp_path):
    monkeypatch.setenv("MOVIE_UI_VLM_LIFECYCLE", "0")
    monkeypatch.delenv("CHARACTER_LIBRARY_DIR", raising=False)
    state = mt.set_home(monkeypatch, tmp_path)
    clean_env(monkeypatch, tmp_path)
    ws = mt.make_stub_workspace(tmp_path)
    stub_seed_edit(ws, OK_MODELS)
    monkeypatch.setattr(srv, "seed_free_gib", lambda path: 100.0)
    asked = slr.fake_fetch(monkeypatch)
    running = mt.Running(state)
    running.server.probe_ws = ws
    yield {"state": state, "ws": ws, "tmp": str(tmp_path), "srv": running, "mp": monkeypatch, "asked": asked,
           "registry": seedgen.user_loras_path()}
    running.close()
    mt.kill_everything(state)


def _upload(s):
    status, _h, payload = mt.api(s, "POST", "/api/uploads", raw=mt.PNG + b"src", headers={"Content-Type": "image/png"})
    assert status == 201, payload
    return payload["upload_id"]


def _run_body(ws, up, model_id, lora_ids):
    return {"ws": ws, "source": {"upload_id": up}, "prompt": "make it night", "model": "qwen", "qwen_model": model_id,
            "loras": [{"id": i, "scale": 1.0} for i in lora_ids], "candidates": 1, "seed": 7}


# --- CL-T25 (CL35): the routes ---------------------------------------------------------------------------------------

NEW_ROUTES = [("POST", r"/api/seed-loras", "h_seed_lora_add", "/api/seed-loras"),
              ("DELETE", r"/api/seed-loras/(user-[a-z0-9-]{1,24})", "h_seed_lora_remove",
               "/api/seed-loras/user-anything-to-real")]


def test_cl_t25_the_routes(env):
    s = env["srv"]
    routes = list(srv.ROUTES)
    i = routes.index(("GET", r"/api/seeds/folders", "h_seed_folders", "/api/seeds/folders"))
    assert routes[i + 1:i + 3] == NEW_ROUTES
    assert len(srv.ROUTES) == 67
    for method, regex, name, sample in NEW_ROUTES:
        assert re.fullmatch(regex, sample), sample
        assert getattr(srv.MovieUIHandler, name) is getattr(srv, "_" + name), name
        for token in (None, "wrong-token"):
            assert mt.api(s, method, sample, body={} if method == "POST" else None, token=token)[::2] == (
                401, {"error": "missing or invalid token"}), (sample, token)
    assert mt.api(s, "GET", "/api/seed-loras")[::2] == (405, {"error": "method not allowed"})
    assert mt.api(s, "DELETE", "/api/seed-loras/uncensored")[::2] == (404, {"error": "not found"})
    assert srv.SEED_LORA_DELETE_BODY == "DELETE /api/seed-loras/<id> takes no body"
    assert probe_count(env["ws"]) == 0


# --- CL-T26 (CL38, R1-R12): bad bodies get the CLI's texts ----------------------------------------------------------

BAD_BODIES = [({"repo": slr.REPO, "ws": "/abs/ws"}, slr.FIELDS_TEXT % "ws"),
              ({"repo": slr.REPO, "scale": "x"}, slr.SCALE_TEXT),
              ({"repo": slr.REPO, "scale": True}, slr.SCALE_TEXT),
              ({"repo": slr.REPO, "steps": 2.5}, slr.STEPS_TEXT),
              ({"repo": slr.REPO, "path": "/abs/x.safetensors"}, slr.ONE_SOURCE),
              ({"path": "rel/x.safetensors", "family": "qwen2511"},
               "path must be an absolute path or start with ~ (got rel/x.safetensors)")]


def test_cl_t26_bad_bodies_get_the_cli_texts(env):
    for body, message in BAD_BODIES:
        assert mt.api(env["srv"], "POST", "/api/seed-loras", body=body)[::2] == (400, {"error": message}), body
    assert env["asked"] == [] and not os.path.exists(env["registry"]) and probe_count(env["ws"]) == 0


def test_cl_t26_a_body_that_is_not_an_object_is_a_400(env):
    for body in ([], ["a"], "text", 5):
        assert mt.api(env["srv"], "POST", "/api/seed-loras", body=body)[::2] == (
            400, {"error": "body must be a JSON object"}), body
    assert env["asked"] == [] and not os.path.exists(env["registry"]) and probe_count(env["ws"]) == 0


# --- CL-T27 (CL38): POST a Hugging Face LoRA ------------------------------------------------------------------------

def test_cl_t27_post_a_hugging_face_lora(env):
    s, ws = env["srv"], env["ws"]
    status, _h, data = mt.api(s, "POST", "/api/seed-loras", body={"repo": slr.REPO, "trigger": slr.TRIGGER})
    assert status == 201, data
    assert data["lora"] == {"id": LORA_ID, "label": slr.REPO, "family": "qwen2511", "default_on": False,
                            "default_scale": 1.0, "steps": None, "scheduler": None, "license": "apache-2.0",
                            "user": True, "source": "hf", "trigger": slr.TRIGGER,
                            "setup": "bin/seed-edit-setup --lora " + LORA_ID}
    assert data["notes"] == ["family qwen2511 (the model card's base_model is Qwen/Qwen-Image-Edit-2511)",
                             "download it with: bin/seed-edit-setup --lora " + LORA_ID]
    cap = data["seed_edit"]
    assert cap["registry"] == seedgen.registry_view() and data["lora"] in cap["registry"]["loras"]
    assert probe_count(ws) == 1 and env["asked"] == [slr.REPO]
    assert cap["ok"] is True and cap["models"]["qwen"]["loras"][LORA_ID] == {
        "ok": False, "reason": lib.PROBE_NOT_REPORTED}
    assert mt.api(s, "GET", "/api/host")[2]["capabilities"]["seed_edit"] == cap


# --- CL-T28 (CL38): POST a local LoRA, then DELETE it ----------------------------------------------------------------

def test_cl_t28_post_local_and_delete(env):
    s, ws = env["srv"], env["ws"]
    path = slr.safetensors(os.path.join(env["tmp"], "loras", "real.safetensors"))
    status, _h, data = mt.api(s, "POST", "/api/seed-loras", body={"path": path, "family": "qwen2511", "id": "user-real"})
    assert status == 201, data
    assert (data["lora"]["id"], data["lora"]["source"], data["lora"]["setup"]) == ("user-real", "local", None)
    assert data["notes"] == ["the file is used in place: moving, replacing or resizing it makes this LoRA unavailable"]
    status, _h, data = mt.api(s, "DELETE", "/api/seed-loras/user-real")
    assert status == 200, data
    assert set(data) == {"removed", "kept", "seed_edit"} and (data["removed"], data["kept"]) == ("user-real", path)
    assert "user-real" not in [l["id"] for l in data["seed_edit"]["registry"]["loras"]]
    assert seedgen.qwen_lora_ids() == seedgen.BUILTIN_QWEN_LORA_IDS and os.path.isfile(path)
    assert probe_count(ws) == 2
    assert mt.api(s, "DELETE", "/api/seed-loras/user-real")[::2] == (
        404, {"error": "unknown custom LoRA user-real (custom LoRAs: none)"})
    assert mt.api(s, "DELETE", "/api/seed-loras/user-real", body={"x": 1})[::2] == (
        400, {"error": "DELETE /api/seed-loras/<id> takes no body"})
    assert mt.api(s, "DELETE", "/api/seed-loras/user-real", body={})[0] == 404
    assert probe_count(ws) == 2


# --- CL-T29 (CL13, CL36, CL37): a Seeds run with a custom LoRA -------------------------------------------------------

def test_cl_t29_a_seeds_run_with_a_custom_lora(env):
    s, ws, state = env["srv"], env["ws"], env["state"]
    path = slr.safetensors(os.path.join(env["tmp"], "loras", "real.safetensors"))
    entry = slr.local_entry(path)
    slr.write_registry(env["registry"], [entry])
    stub_seed_edit(ws, {"zimage": OK_Z, "qwen": qwen_probe(seedgen.BUILTIN_QWEN_LORA_IDS + ("user-local",))})
    up = _upload(s)
    assert mt.api(s, "POST", "/api/seeds/runs", body=_run_body(ws, up, "qwen2511-bf16", ["user-local"]))[::2] == (
        400, {"error": NO_LORAS})
    status, _h, data = mt.api(s, "POST", "/api/seeds/runs", body=_run_body(ws, up, "qwen2511-q4", ["user-local"]))
    assert status == 201, data
    with open(os.path.join(data["run"]["dir"], "run.json"), encoding="utf-8") as f:
        record = json.load(f)
    assert record["prompt"] == slr.TRIGGER + " make it night" == data["run"]["prompt"]
    assert record["loras"] == [{"id": "user-local", "source": "local", "file": "real.safetensors",
                                "sha256": entry["sha256"], "scale": 1.0, "trigger": slr.TRIGGER}]
    job = lib.read_job(lib.job_dir(state, record["job"]))
    argv = job["argv"]
    assert argv[argv.index("--prompt") + 1] == "make it night" and job["fields"]["prompt"] == "make it night"
    assert argv[argv.index("--lora") + 1] == "user-local=1.0"


# --- CL-T30 (CL45): old records after a remove -------------------------------------------------------------------------

def test_cl_t30_old_records_after_a_remove(env):
    s, ws = env["srv"], env["ws"]
    path = slr.safetensors(os.path.join(env["tmp"], "loras", "real.safetensors"))
    slr.write_registry(env["registry"], [slr.hf_entry(), slr.local_entry(path)])
    stub_seed_edit(ws, {"zimage": OK_Z, "qwen": qwen_probe(seedgen.BUILTIN_QWEN_LORA_IDS + ("user-hf", "user-local"))})
    status, _h, data = mt.api(s, "POST", "/api/seeds/runs",
                              body=_run_body(ws, _upload(s), "qwen2511-q4", ["user-local", "user-hf"]))
    assert status == 201, data
    run = data["run"]["run"]
    with open(os.path.join(data["run"]["dir"], "run.json"), encoding="utf-8") as f:
        recorded = json.load(f)["loras"]
    assert [l["id"] for l in recorded] == ["user-hf", "user-local"]
    for lora_id in ("user-hf", "user-local"):
        assert mt.api(s, "DELETE", "/api/seed-loras/" + lora_id)[0] == 200, lora_id
    assert seedgen.qwen_lora_ids() == seedgen.BUILTIN_QWEN_LORA_IDS
    status, _h, data = mt.api(s, "GET", "/api/seeds/runs?ws=" + ws)
    assert status == 200 and [(r["run"], r["loras"]) for r in data["runs"]] == [(run, recorded)]
    status, _h, view = mt.api(s, "GET", "/api/seeds/runs/%s?ws=%s" % (run, ws))
    assert status == 200 and view["loras"] == recorded and view["qwen_model"]["id"] == "qwen2511-q4"
    chosen = qe.selection_of(view)
    assert chosen == ("qwen2511-q4", [{"id": "user-hf", "scale": 1.0}, {"id": "user-local", "scale": 1.0}])
    assert qe.generator_text(*chosen) == ("Qwen-Image-Edit-2511 q4 (Lightning) (mflux-community/qwen-image-edit-2511-"
                                          "mflux-q4) + LoRAs user-hf@1, user-local@1, 8 steps")


# --- CL-T31 (CL39): main exports the registry path before the threads start -------------------------------------------

def test_cl_t31_main_exports_the_registry_path_before_the_threads(monkeypatch, tmp_path, capsys):
    mt.set_home(monkeypatch, tmp_path)
    monkeypatch.delenv("SEED_EDIT_USER_LORAS")
    seen = []

    class FakeServer(object):
        port = 8999

        def serve_forever(self):
            return None

        def server_close(self):
            return None

    def start(server):
        seen.append(os.environ.get("SEED_EDIT_USER_LORAS"))
        return threading.Event()

    monkeypatch.setattr(srv, "make_server", lambda port, state, ui_ws, token: FakeServer())
    monkeypatch.setattr(srv, "start_threads", start)
    monkeypatch.setattr(srv, "batch_recovery", lambda state: None)
    monkeypatch.setattr(srv.lib, "startup_recovery", lambda state: None)
    monkeypatch.setattr(srv.signal, "signal", lambda signum, handler: None)
    try:
        assert srv.main(["--port", "8999"]) == 0
    finally:
        while srv._LOCK_FD:
            os.close(srv._LOCK_FD.pop())
    assert seen == [os.path.join(WS, "generated", "seed_loras", "user_loras.json")] == [seedgen.user_loras_path()]
    assert capsys.readouterr().out.endswith("movie-ui: stopped\n")


# --- CL-T32, CL-T33 (CL40-CL43): the page ------------------------------------------------------------------------------

APP_JS_PINS = ("  function customLoraForm(prefix, onAdded) {", "  function customLoraBody(v) {", '"/api/seed-loras"',
               '"Add custom LoRA"', '"qwen2511-bf16 runs without LoRAs; choose qwen2511-q4 to use a Qwen-Image-Edit-2511 LoRA"',
               '" steps (set by "', 'el("span", {cls: "chip", text: "custom"})', 'askConfirm("Remove custom LoRA "',
               'entry.family + "|" + entry.backend + "|"', "event.stopPropagation()",
               "return [l.id, loraOk(l.id), loraNote(l)];", '" steps (turbo)"',
               'if (!node("-custom")) { node("-qwen-box").appendChild(customLoraForm(prefix)); }',
               '"adding… (hashing a large local file can take minutes)"', '"; the file stays at "',
               'cls: "se-lora-remove", text: "Remove"', '"; trigger: "')


def _page():
    static = os.path.join(WS, "static", "movie-ui")
    with open(os.path.join(static, "index.html"), encoding="utf-8") as f:
        html = f.read()
    with open(os.path.join(static, "app.js"), encoding="utf-8") as f:
        js = f.read()
    return static, html, js


def test_cl_t32_the_page_texts():
    static, html, js = _page()
    for text in APP_JS_PINS:
        assert text in js, text
    assert js.count("function customLoraForm(prefix, onAdded) {") == 1 and js.count("function customLoraBody(v) {") == 1
    for name, text in (("index.html", html), ("app.js", js)):
        for pattern in (r"https?://", r"\son[a-z]+=", r"style=", r"\balert\(", r"\bconfirm\(", r"\bprompt\(",
                        r"\beval\(", r"new Function"):
            assert not re.search(pattern, text), (name, pattern)
    node = shutil.which("node")
    if node:
        proc = subprocess.run([node, "--check", os.path.join(static, "app.js")], capture_output=True, text=True,
                              timeout=60)
        assert proc.returncode == 0, proc.stderr


def test_the_loras_tab_lists_the_qwen_stills_bases():
    static, html, js = _page()
    for text in ('["qwen:qwen2511", "Qwen-Image-Edit-2511 (Qwen stills)"]', '["qwen:qwen21", "Qwen-Image-2.1 (Qwen stills)"]',
                 "Pick one base: the Z-Image model or one Qwen model, not both.",
                 "if (typeof onAdded === \"function\") { onAdded(); }", "function syncQwenBase() {",
                 '"stills (Qwen)"', 'api("DELETE", "/api/seed-loras/" + enc(l.id))'):
        assert text in js, text
    assert 'customLoraForm("l"' not in js
    assert "l-qwen-box" not in html and "l-qwen-box" not in js
    assert "l-custom-family" not in js
    assert 'id="l-custom' not in html
    for name, text in (("index.html", html), ("app.js", js)):
        for pattern in (r"https?://", r"\son[a-z]+=", r"style=", r"\bconfirm\(", r"innerHTML"):
            assert not re.search(pattern, text), (name, pattern)
    node = shutil.which("node")
    if node:
        proc = subprocess.run([node, "--check", os.path.join(static, "app.js")], capture_output=True, text=True,
                              timeout=60)
        assert proc.returncode == 0, proc.stderr


def test_the_qwen_base_fixes_are_pinned():
    _static, _html, js = _page()
    sync = js[js.index("function syncQwenBase() {"):js.index("const QWEN_MIX_MESSAGE")]
    assert 'show($("#l-add"), true)' in sync
    assert 'show($("#l-add"), false)' not in js
    handler = js[js.index('$("#l-add").addEventListener("click"'):js.index("// --- jobs (MU84)")]
    assert '"/api/seed-loras"' in handler
    assert sync.count('$("#l-output").textContent === QWEN_MIX_MESSAGE') == 1
    load = js[js.index("async function loadCatalogTable("):js.index("// lora_catalog.MOTION_SCOPE_WARNING")]
    assert load.count("function appendQwenRows(body) {") == 1
    assert js.count("function appendQwenRows(") == 1
    assert load.count("appendQwenRows(") == 4
    assert load.index("appendQwenRows(firstBody)") < load.index('api("GET", "/api/loras"')
    assert "appendQwenRows(body);\n      return;" in load
    assert load.rstrip().endswith("appendQwenRows(body);\n  }")
    assert "remove.disabled = true;" in load and "} finally {" in load


BODY_CASES = [
    ({"source": "hf", "repo": " " + slr.REPO + " ", "file": " ", "path": "/left/over.safetensors", "family": "",
      "trigger": "  ", "scale": "", "steps": ""}, {"repo": slr.REPO}),
    ({"source": "hf", "repo": slr.REPO, "file": " a.safetensors ", "path": "", "family": "qwen2511",
      "trigger": " " + slr.TRIGGER + " ", "scale": "0.7", "steps": "30"},
     {"repo": slr.REPO, "file": "a.safetensors", "family": "qwen2511", "trigger": slr.TRIGGER, "scale": 0.7,
      "steps": 30}),
    ({"source": "local", "repo": "left/over", "file": "x.safetensors", "path": " /a/b.safetensors ", "family": "qwen21",
      "trigger": "", "scale": "1", "steps": ""}, {"path": "/a/b.safetensors", "family": "qwen21", "scale": 1}),
    ({"source": "hf", "repo": "o/n", "file": "", "path": "", "family": "", "trigger": "", "scale": "abc", "steps": "x"},
     {"repo": "o/n", "scale": "abc", "steps": "x"}),
]


def test_cl_t33_the_post_body(tmp_path):
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed")
    _static, _html, js = _page()
    start = js.index("  function customLoraBody(v) {")
    body = js[start:js.index("\n  }\n", start) + len("\n  }\n")]
    script = body + "process.stdout.write(JSON.stringify(%s.map(customLoraBody)));\n" % json.dumps(
        [v for v, _want in BODY_CASES])
    path = os.path.join(str(tmp_path), "body.js")
    with open(path, "w", encoding="utf-8") as f:
        f.write(script)
    proc = subprocess.run([node, path], capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stderr
    assert json.loads(proc.stdout) == [want for _v, want in BODY_CASES]


# --- CL-T34 (CL47, SC10): batch forks are unchanged ------------------------------------------------------------------

def test_cl_t34_batch_forks_are_unchanged():
    assert batch.COPY_FILES == {
        "render": ("story.md", "plan.json", "story_checks.json", "story_prompt.txt", "catalog_loras.json",
                   "manifest.json", "seed_edits.json"),
        "stills": ("story.md", "plan.json", "story_checks.json", "story_prompt.txt"),
        "replan": ()}
    assert batch.FIELD_LEVELS == {
        "model": "render", "gemma": "render", "video_loras": "render", "action_loras": "render",
        "frames": "render", "fps": "render", "no_low_ram": "render", "panel_timeout": "render",
        "width": "stills", "height": "stills", "stills_loras": "stills", "location_strength": "stills",
        "seed_edit_model": "stills", "seed_edit_loras": "stills", "extra_refs": "stills",
        "narrative": "replan", "goal": "replan", "panels": "replan", "length": "replan",
        "seed_upload": "replan", "mode": "replan", "characters": "replan", "locations": "replan",
        "narration": "replan", "story_model": "replan", "story_legacy": "replan", "judge": "replan",
        "auto_lora": "replan"}
    root = subprocess.run(["git", "-C", WS, "rev-parse", "--show-toplevel"], capture_output=True, text=True)
    if root.returncode != 0:
        pytest.skip("not a git checkout")
    if subprocess.run(["git", "-C", WS, "cat-file", "-e", "20cee82^{commit}"], capture_output=True).returncode:
        pytest.skip("20cee82 is not in this checkout")
    proc = subprocess.run(["git", "-C", WS, "diff", "--quiet", "20cee82", "--", "movie_ui_batch.py"],
                          capture_output=True, text=True)
    assert proc.returncode == 0, proc.stdout + proc.stderr


# --- Review Focus 5: an older probe gives a clear 409 --------------------------------------------------------------------

def test_cl_review_focus_5_an_older_probe_gives_a_clear_409(env):
    s, ws = env["srv"], env["ws"]
    path = slr.safetensors(os.path.join(env["tmp"], "loras", "real.safetensors"))
    slr.write_registry(env["registry"], [slr.local_entry(path)])
    status, _h, data = mt.api(s, "POST", "/api/seeds/runs", body=_run_body(ws, _upload(s), "qwen2511-q4", ["user-local"]))
    assert (status, data) == (409, {"error": "LoRA real.safetensors is unavailable: not reported by this workspace's "
                                             "bin/seed-edit --probe (it may predate custom LoRAs)"})
    assert not os.path.exists(os.path.join(ws, "generated", "seeds"))
    s.server.refresh_seed_edit()
    cap = s.server.capability_snapshot()["seed_edit"]
    assert cap["ok"] is True and cap["models"]["qwen"]["loras"] == dict(
        [(i, OK) for i in seedgen.BUILTIN_QWEN_LORA_IDS] + [("user-local", {"ok": False, "reason": lib.PROBE_NOT_REPORTED})])
