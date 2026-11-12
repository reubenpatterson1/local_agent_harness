"""Tests for the movie UI half of motion-beat-only
(docs/superpowers/specs/2026-11-12-motion-lora-beat-only-design.md, MB4 and MB8: MB-T8, MB-T9):
POST /api/loras refuses a motion LoRA scoped global or either, and the LoRAs tab shows a motion
LoRA's scope as beat and warns about a saved global or either.

Run from the workspace root: python3 -m pytest -q -p no:cacheprovider tests/test_motion_beat_only_ui.py
"""

import os
import shutil
import subprocess
import sys

import pytest

WS = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
sys.path.insert(0, WS)
sys.path.insert(0, os.path.join(WS, "tests"))

import lora_catalog  # noqa: E402
import movie_ui_testutil as mt  # noqa: E402

NOTE = ("Where the story planner may put a physics video LoRA: global applies it to every panel, "
        "beat only to the beats it suits, either lets the planner choose; the default is beat. "
        "A style LoRA is always global, a motion LoRA is always per-beat, and a stills LoRA has "
        "no scope, so the select is off for all three.")


@pytest.fixture
def ui(monkeypatch, tmp_path):
    state = mt.set_home(monkeypatch, tmp_path)
    workspace = mt.make_stub_workspace(tmp_path)
    running = mt.Running(state)
    yield {"ws": workspace, "srv": running}
    running.close()
    mt.kill_everything(state)


def test_mbt8_the_movie_ui_refuses_a_non_beat_motion_scope(ui):
    s, ws = ui["srv"], ui["ws"]
    add = {"ws": ws, "path": "/l/fight.safetensors", "id": "fight", "kind": "motion",
           "target": "video", "base_models": ["M1"], "triggers": [], "description": "a fight",
           "use_when": "fights", "avoid_when": "", "default_strength": 0.8,
           "strength_range": [0.5, 1], "rank": 16, "alpha": None}
    for scope in ("global", "either"):
        assert mt.api(s, "POST", "/api/loras", body=dict(add, scope=scope))[::2] == (
            400, {"error": "scope must be beat or null for a motion LoRA"}), scope
    assert mt.stub_calls(ws) == []
    for body, tail in ((dict(add, scope="beat"), ["--rank", "16", "--scope", "beat"]),
                       (dict(add, scope=None), None),
                       (dict(add, kind="physics", scope="either"),
                        ["--rank", "16", "--scope", "either"])):
        status, _h, payload = mt.api(s, "POST", "/api/loras", body=body)
        assert status == 200, payload
        argv = mt.stub_calls(ws)[-1]["argv"]
        if tail is None:
            assert "--scope" not in argv
        else:
            assert argv[argv.index(tail[0]):argv.index(tail[0]) + len(tail)] == tail
    calls = len(mt.stub_calls(ws))
    assert mt.api(s, "POST", "/api/loras", body=dict(add, kind="style", scope="either"))[::2] == (
        400, {"error": "scope must be global or null for a style LoRA"})
    assert len(mt.stub_calls(ws)) == calls
    status, _h, payload = mt.api(s, "POST", "/api/loras/scope",
                                 body={"ws": ws, "id": "fight", "scope": "global"})
    assert status == 200, payload
    assert mt.stub_calls(ws)[-1]["argv"] == ["scope", "fight", "global"]


def test_mbt9_the_loras_tab_shows_motion_as_beat_and_warns():
    static = os.path.join(WS, "static", "movie-ui")
    with open(os.path.join(static, "index.html"), encoding="utf-8") as f:
        html = f.read()
    with open(os.path.join(static, "app.js"), encoding="utf-8") as f:
        js = f.read()
    assert html.count('id="l-scope-warnings"') == 1
    assert '<div id="l-scope-warnings" class="warning" hidden></div>' in html
    assert html.index('id="l-verify-all"') < html.index('id="l-scope-warnings"') < html.index(
        'id="l-table"')
    assert NOTE + "</span>" in html
    for text in ('if (e.kind === "motion") { return el("td", {text: "beat"}); }',
                 '$("#l-scope").disabled = $("#l-target").value !== "video" || '
                 '$("#l-kind").value !== "physics";',
                 'const warnings = clear($("#l-scope-warnings"));',
                 'warnings.hidden = true;',
                 'if (e.target === "video" && e.kind === "motion" && e.scope && '
                 'e.scope !== "beat") {',
                 'warnings.appendChild(el("div", {text: "Warning: " + motionScopeWarning(e)}));',
                 'warnings.hidden = false;'):
        assert js.count(text) == 1, text
    parts = lora_catalog.MOTION_SCOPE_WARNING.split("%s")
    assert len(parts) == 4
    assert ('return "%s" + e.id + "%s" + e.scope + "%s" + e.id + "%s";' % tuple(parts)) in js
    assert '$("#l-kind").value === "style";' not in js
    node = shutil.which("node")
    if node:
        proc = subprocess.run([node, "--check", os.path.join(static, "app.js")],
                              capture_output=True, text=True, timeout=60)
        assert proc.returncode == 0, proc.stderr
