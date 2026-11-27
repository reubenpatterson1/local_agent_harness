"""Tests for the image critic's movie-ui side (docs/superpowers/specs/2026-11-27-image-critic-design.md, Section 6.2:
ICT20-ICT24; ICT22b lives in tests/test_movie_ui_seedgen.py): the log regex and the progress summary, the Compose
field, flag, argv and V1 rule 12f, the batch level, the Seeds request, argv and candidate view, the static page,
and the rule that the server never imports image_critic.

Run from the workspace root: python3 -m pytest -q -p no:cacheprovider tests/test_movie_ui_critic.py

Stdlib and pytest (node --check when node is on PATH). The V1 tests use a stub workspace whose bin/ltx-movie prints
tests/fixtures/movie_ui/ltx-movie-help-current.txt. No test starts a server, a job or a model.
"""

import os
import re
import shutil
import subprocess

import pytest

import movie_ui_testutil as mt
import movie_ui_batch as batch
import movie_ui_lib as lib
import movie_ui_seedgen as seedgen
import movie_ui_server as srv
from test_movie_ui_qwen_edit import _clean_env
from test_movie_ui_shots_zimage import _compose_page_code, _node

WS = mt.WS
UP = "a" * 64 + ".png"
UNC = [{"id": "uncensored", "scale": 1}]
RUN = "se-20261102-141500-a1b2"
RULE_12F = "the image critic needs shots mode with a seed image and a Qwen seed edit model"


@pytest.fixture
def v1_env(monkeypatch, tmp_path):
    state = mt.set_home(monkeypatch, tmp_path)
    _clean_env(monkeypatch, tmp_path)
    ws = mt.make_stub_workspace(tmp_path)
    with open(os.path.join(state, "uploads", UP), "wb") as f:
        f.write(mt.PNG)
    return {"state": state, "ws": ws}


def _page():
    static = os.path.join(WS, "static", "movie-ui")
    with open(os.path.join(static, "index.html"), encoding="utf-8") as f:
        html = f.read()
    with open(os.path.join(static, "app.js"), encoding="utf-8") as f:
        js = f.read()
    return static, html, js


# --- ICT20: the log regex and the progress summary ---------------------------------------------------------------

def test_ict20_the_log_regex_and_the_snapshot(tmp_path):
    for line, groups in (("critic 1/3: ok (score 8, attempt 1)", ("1", "3", "ok", "score 8, attempt 1")),
                         ("critic 2/3: redo (score 3: fused hand)", ("2", "3", "redo", "score 3: fused hand")),
                         ("critic 2/3: flagged (best score 5 of 3 attempts: no defect named)",
                          ("2", "3", "flagged", "best score 5 of 3 attempts: no defect named")),
                         ("critic 3/3: unjudged (VLM request failed: OSError: refused)",
                          ("3", "3", "unjudged", "VLM request failed: OSError: refused")),
                         ("critic 4/4: ok", ("4", "4", "ok", None))):
        match = lib.CRITIC_RE.match(line)
        assert match and match.groups() == groups, line
    for line in ("critic: done: 3 passed, 0 flagged, 0 unjudged; 0 redo round(s) run", "candidate 1/4 ok 2.0s",
                 "critic: judging 3 panels with the VLM (round 0)", "critic 1/3: skipped (x)"):
        assert not lib.CRITIC_RE.match(line), line
    state = str(tmp_path)
    job = {"id": "20261127-120000-a1b2", "workspace": state, "story_id": "s1"}
    lines = (b"candidate 1/3 ok 1.0s\ncandidate 2/3 ok 1.0s\ncandidate 3/3 ok 1.0s\n"
             b"critic 1/3: ok (score 8, attempt 1)\ncritic 2/3: redo (score 3: fused hand)\n"
             b"critic 3/3: unjudged (unparseable: x)\ncritic 2/3: flagged (best score 4 of 3 attempts: fused hand)\n")
    parser = lib.ProgressParser("seed-edit", {"candidates": 3})
    parser.feed(lines)
    snap = parser.snapshot(job, None, state)
    assert snap["critic"] == {"ok": [1], "redo": [], "flagged": [2], "unjudged": [3]}
    assert snap["candidates"]["ok"] == 3 and list(snap)[-1] == "critic"
    plain = lib.ProgressParser("seed-edit", {"candidates": 3})
    plain.feed(lines.split(b"critic")[0])
    assert "critic" not in plain.snapshot(job, None, state)
    movie = lib.ProgressParser("movie", {"mode": "shots"})
    movie.feed(b"panel 1 -> /x (Qwen edit of the seed, 12.5s)\ncritic 1/2: redo (score 3: x)\n"
               b"critic 2/2: ok (score 9, attempt 1)\ncritic 1/2: ok (score 8, attempt 2)\n")
    snap = movie.snapshot(job, None, state)
    assert snap["critic"] == {"ok": [1, 2], "redo": [], "flagged": [], "unjudged": []}
    assert snap["panels"] == {}
    bare = lib.ProgressParser("movie", {"mode": "shots"})
    bare.feed(b"seed edits: 3 panel stills written\n")
    assert "critic" not in bare.snapshot(job, None, state)


# --- ICT21: the Compose field, flag, argv, V1 rule 12f and the batch level ------------------------------------

def test_ict21_the_compose_field_flag_argv_and_v1(v1_env):
    state, ws = v1_env["state"], v1_env["ws"]
    keys = list(lib.DEFAULT_FIELDS)
    assert lib.DEFAULT_FIELDS["critic"] is False and keys[keys.index("extra_refs") + 1] == "critic"
    flags = [k for k, _f in lib.FIELD_FLAGS]
    assert dict(lib.FIELD_FLAGS)["critic"] == ("--critic",) and flags[flags.index("critic") + 1] == "extra_refs"
    f = mt.fields(WS, seed_upload=UP, action="movie", mode="shots", seed_edit_model="qwen21-q4",
                  seed_edit_loras=UNC, critic=True)
    argv = lib.build_argv(f, WS, state)
    i = argv.index("--seed-image")
    assert argv[i:i + 7] == ["--seed-image", os.path.join(state, "uploads", UP), "--seed-edit-model", "qwen21-q4",
                             "--seed-edit-lora", "uncensored=1.0", "--critic"]
    golden = [a for a in argv if a != "--critic"]
    assert lib.build_argv(dict(f, critic=False), WS, state) == golden
    old = dict((k, v) for k, v in f.items() if k != "critic")
    assert lib.build_argv(old, WS, state) == golden
    assert "--critic" not in lib.build_argv(dict(f, seed_upload=None, mode="chained"), WS, state)

    def errors(**overrides):
        return lib.validate_fields(mt.fields(ws, **overrides), ws, state)

    shots = dict(seed_upload=UP, mode="shots", seed_edit_model="qwen21-q4")
    assert errors(critic=True, **shots) == []
    assert errors(critic=False, **shots) == [] and errors(**shots) == []
    assert errors(critic="yes", **shots) == ["critic must be true or false"]
    assert errors(critic=1, **shots) == ["critic must be true or false"]
    assert errors(critic=True, seed_upload=UP, mode="chained", seed_edit_model="qwen21-q4") == [RULE_12F]
    assert errors(critic=True, mode="shots") == [RULE_12F]
    assert errors(critic=True, seed_upload=UP, mode="shots", seed_edit_model="as-is") == [RULE_12F]
    assert lib.validate_fields(dict((k, v) for k, v in mt.fields(ws, **shots).items() if k != "critic"),
                               ws, state) == []
    assert batch.FIELD_LEVELS["critic"] == "stills"
    assert "critic" in [group for group in batch.GROUPS if "seed_edit_model" in group][0]


# --- ICT22a: the Seeds request, argv and candidate view -------------------------------------------------------

def _req(**overrides):
    body = {"ws": "/abs/ws", "source": {"upload_id": UP}, "prompt": "make it night", "model": "qwen", "candidates": 2,
            "seed": 7}
    body.update(overrides)
    return body


def test_ict22a_seeds_request_argv_and_view():
    clean, error = seedgen.validate_run_request(_req(critic=True))
    assert error is None and clean["critic"] is True and list(clean)[-1] == "critic"
    assert seedgen.validate_run_request(_req(model="zimage", critic=True)) == (None, "critic is only for qwen")
    for bad in (1, "true", [True]):
        assert seedgen.validate_run_request(_req(critic=bad)) == (None, "critic must be true or false"), bad
    for body in (_req(), _req(critic=None), _req(critic=False), _req(model="zimage", critic=False)):
        clean, error = seedgen.validate_run_request(body)
        assert error is None and "critic" not in clean
    assert seedgen.validate_run_request(_req(prompt="", critic=1)) == (None, "prompt is required")
    fields = {"ws": "/ws", "run": RUN, "source_file": "source.png", "prompt": "make it night", "model": "qwen",
              "strength": None, "qwen_model": "qwen21-q4", "loras": [{"id": "uncensored", "scale": 1.0}],
              "candidates": 2, "seed": 7, "source": {"kind": "upload", "upload_id": UP}}
    plain = lib.seed_edit_argv(fields, "/ws", py="/py")
    argv = lib.seed_edit_argv(dict(fields, critic=True), "/ws", py="/py")
    i = argv.index("--candidates")
    assert argv[i - 3:i + 1] == ["--lora", "uncensored=1.0", "--critic", "--candidates"]
    assert [a for a in argv if a != "--critic"] == plain and "--critic" not in plain
    assert lib.seed_edit_argv(dict(fields, critic=False), "/ws", py="/py") == plain
    for entry in ({"n": 1}, {"n": 1, "critic": "flagged"}, {"n": 1, "critic": {"status": "redo"}},
                  {"n": 1, "critic": {"score": 5}}):
        assert srv._cand_critic(entry) is None, entry
    full = {"status": "flagged", "score": 5, "defects": ["fused hand", 3, "x"], "reason": "r" * 400,
            "seed_used": 9, "pass_score": 7, "attempts": [{}, {}, {}]}
    assert srv._cand_critic({"n": 1, "critic": full}) == {"status": "flagged", "score": 5,
                                                          "defects": ["fused hand", "x"], "reason": "r" * 300,
                                                          "attempts": 3}
    assert srv._cand_critic({"n": 1, "critic": {"status": "unjudged", "score": True, "defects": "x", "reason": 5,
                                                "attempts": None}}) == {
        "status": "unjudged", "score": None, "defects": [], "reason": None, "attempts": 0}


# --- ICT23: the static page -------------------------------------------------------------------------------------

def test_ict23_the_page():
    static, html, js = _page()
    for element in ("c-critic-box", "c-critic", "se-critic-box", "se-critic"):
        assert html.count('id="%s"' % element) == 1, element
    assert html.index('id="c-sq-shots-note"') < html.index('id="c-critic-box"') < html.index('id="c-xr-box"')
    assert html.index('id="se-qwen-box"') < html.index('id="se-critic-box"') < html.index('id="se-strength-box"')
    assert '<label id="c-critic-box" hidden>' in html and '<label id="se-critic-box" hidden>' in html
    assert html.index('<p id="se-qwen-note" class="muted"></p>\n      </div>\n      <label id="se-critic-box"') > 0
    for text in ("function criticText(c) {", "function criticProgressText(c) {", '$("#c-critic").checked',
                 "body.critic = true;", "critic: flagged — best score ",
                 'show($("#c-critic-box"), shotsSeed && !zimageSeed',
                 '    show($("#se-qwen-box"), model === "qwen");\n    show($("#se-critic-box"), model === "qwen");\n',
                 'if (cand.critic) { row.parts.push(el("div", {cls: "muted", text: criticText(cand.critic)})); }',
                 "if (p.critic) { parts.push(criticProgressText(p.critic)); }",
                 '(p.critic ? " - " + criticProgressText(p.critic) : "")'):
        assert text in js, text
    assert js.count('$("#c-critic").checked') == 2
    for name, text in (("index.html", html), ("app.js", js)):
        for pattern in (r"https?://", r"\son[a-z]+=", r"style=", r"\bconfirm\(", r"innerHTML"):
            assert not re.search(pattern, text), (name, pattern)
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed")
    proc = subprocess.run([node, "--check", os.path.join(static, "app.js")], capture_output=True, text=True,
                          timeout=60)
    assert proc.returncode == 0, proc.stderr
    script = _compose_page_code() + (
        'function run(mode, engine, checked, editModel) {\n'
        '  $("#c-mode").value = mode;\n'
        '  $("#c-res-seed").checked = true;\n'
        '  S.seedUpload = "up1";\n'
        '  S.composeEngine = engine;\n'
        '  $("#c-critic").checked = checked;\n'
        '  PICKED.model = editModel;\n'
        '  return composeFields("movie").critic;\n'
        '}\n'
        'const out = [run("shots", "qwen", true, "qwen-edit-x"), run("shots", "zimage", true, "qwen-edit-x"),\n'
        '             run("chained", "qwen", true, "qwen-edit-x"), run("shots", "qwen", false, "qwen-edit-x"),\n'
        '             run("shots", "qwen", true, "as-is")];\n'
        'S.options = {supported: {critic: false}};\n'
        'out.push(run("shots", "qwen", true, "qwen-edit-x"));\n'
        'fillCompose({critic: true});\n'
        'const filled = $("#c-critic").checked;\n'
        'fillCompose({});\n'
        'console.log(JSON.stringify([out, filled, $("#c-critic").checked]));')
    assert _node(script) == [[True, False, False, False, False, False], True, False]


# --- ICT24: the server never imports the critic -----------------------------------------------------------------

def test_ict24_the_server_never_imports_the_critic():
    for rel in ("movie_ui_server.py", "movie_ui_lib.py", "movie_ui_seedgen.py", "movie_ui_batch.py"):
        with open(os.path.join(WS, rel), encoding="utf-8") as f:
            assert "image_critic" not in f.read(), rel
