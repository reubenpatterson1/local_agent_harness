"""Tests for catalog LoRA scopes in the movie UI
(docs/superpowers/specs/2026-11-10-lora-scope-design.md, LS7: LST10, LST11): the scope of the
add form, the per-row scope select and POST /api/loras/scope.

Run from the workspace root: python3 -m pytest -q -p no:cacheprovider tests/test_lora_scope_ui.py

The server runs against the stub workspace of movie_ui_testutil (its bin/lora-catalog is a stub
that records argv), under a temporary HOME on a free 127.0.0.1 port. Stdlib and pytest.
"""

import os
import re
import shutil
import subprocess
import sys

import pytest

WS = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
sys.path.insert(0, WS)
sys.path.insert(0, os.path.join(WS, "tests"))

import lora_catalog  # noqa: E402
import movie_ui_server as srv  # noqa: E402
import movie_ui_testutil as mt  # noqa: E402


@pytest.fixture
def ui(monkeypatch, tmp_path):
    state = mt.set_home(monkeypatch, tmp_path)
    workspace = mt.make_stub_workspace(tmp_path)
    running = mt.Running(state)
    yield {"ws": workspace, "srv": running}
    running.close()
    mt.kill_everything(state)


def test_lst10_the_scope_endpoints(ui):
    s, ws = ui["srv"], ui["ws"]
    assert ("POST", r"/api/loras/scope", "h_lora_scope", "/api/loras/scope") in srv.ROUTES
    assert srv.LORA_SCOPES == lora_catalog.SCOPES
    add = {"ws": ws, "path": "/l/fight.safetensors", "id": "fight", "kind": "motion",
           "target": "video", "base_models": ["M1"], "triggers": [], "description": "a fight",
           "use_when": "fights", "avoid_when": "", "default_strength": 0.8,
           "strength_range": [0.5, 1], "rank": 16, "alpha": None}
    for scope, tail in (("either", ["--rank", "16", "--scope", "either"]),
                        (None, ["--rank", "16"])):
        status, _h, payload = mt.api(s, "POST", "/api/loras", body=dict(add, scope=scope))
        assert status == 200, payload
        assert mt.stub_calls(ws)[-1]["argv"] == [
            "add", "/l/fight.safetensors", "--id", "fight", "--kind", "motion", "--target",
            "video", "--base-model", "M1", "--description", "a fight", "--use-when", "fights",
            "--default-strength", "0.8", "--strength-range", "0.5,1.0"] + tail
    for scope in ("default", "anywhere", 3, ["beat"]):
        assert mt.api(s, "POST", "/api/loras", body=dict(add, scope=scope))[::2] == (
            400, {"error": "scope must be global, beat, either or null"}), scope
    for scope in ("global", "beat", "either", "default"):
        status, _h, payload = mt.api(s, "POST", "/api/loras/scope",
                                     body={"ws": ws, "id": "fight", "scope": scope})
        assert status == 200 and payload["run"]["exit_code"] == 0
        assert mt.stub_calls(ws)[-1]["argv"] == ["scope", "fight", scope]
    calls = len(mt.stub_calls(ws))
    for body, error in (({"id": "fight", "scope": None}, "scope must be global, beat, either or "
                                                         "default"),
                        ({"id": "fight", "scope": "Beat"}, "scope must be global, beat, either "
                                                           "or default"),
                        ({"id": "-x", "scope": "beat"}, "id must not start with '-'"),
                        ({"id": 5, "scope": "beat"}, "id must be a string")):
        assert mt.api(s, "POST", "/api/loras/scope", body=dict(body, ws=ws))[::2] == (
            400, {"error": error}), body
    assert len(mt.stub_calls(ws)) == calls
    assert mt.api(s, "POST", "/api/loras/scope", body={"ws": ws, "id": "fight", "scope": "beat"},
                  token=None)[::2] == (401, {"error": "missing or invalid token"})


def test_lst11_the_static_page_sets_the_scope():
    static = os.path.join(WS, "static", "movie-ui")
    with open(os.path.join(static, "index.html"), encoding="utf-8") as f:
        html = f.read()
    with open(os.path.join(static, "app.js"), encoding="utf-8") as f:
        js = f.read()
    assert html.count('id="l-scope"') == 1
    assert ('<select id="l-scope"><option value="">default for the kind</option><option>global'
            '</option><option>beat</option><option>either</option></select>') in html
    assert "<th>Target</th><th>Scope</th><th>Strength</th>" in html
    assert html.index('id="l-target"') < html.index('id="l-scope"') < html.index('id="l-add"')
    defaults = re.search(r"const LORA_SCOPE_DEFAULTS = \{style: \"(\w+)\", motion: \"(\w+)\", "
                         r"physics: \"(\w+)\"\};", js)
    assert defaults and dict(zip(("style", "motion", "physics"), defaults.groups())) == (
        lora_catalog.DEFAULT_SCOPES)
    for text in ('scope: $("#l-target").value === "video" && $("#l-scope").value ? '
                 '$("#l-scope").value : null,',
                 'api("POST", "/api/loras/scope", {ws: S.ws, id: e.id, scope: select.value})',
                 'select.value = e.scope || "default";',
                 'scopeCell(e), el("td", {text: strength}),',
                 '$("#l-scope").disabled = $("#l-target").value !== "video";'):
        assert js.count(text) == 1, text
    node = shutil.which("node")
    if node:
        proc = subprocess.run([node, "--check", os.path.join(static, "app.js")],
                              capture_output=True, text=True, timeout=60)
        assert proc.returncode == 0, proc.stderr
