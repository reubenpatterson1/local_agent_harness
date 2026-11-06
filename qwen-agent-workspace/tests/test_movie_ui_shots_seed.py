"""Tests for the movie-ui side of shots mode with a seed image (docs/superpowers/specs/2026-11-05-compose-shots-
seed-edit-design.md, Section 4, test table 6.2: SET16-SET21, with the plan's Review Focus pin 5): V1 rule 8, the
argv and the phases, the 409 rule for movie and redo jobs and seed folders, the render-level batch copy, the
field flags and the static page.

Run from the workspace root: python3 -m pytest -q -p no:cacheprovider tests/test_movie_ui_shots_seed.py

Rules (spec 6.1): the V1 tests use v1_env, a copy of tests/test_movie_ui_checks.py's env (a temporary HOME and a
stub workspace); the HTTP tests use tests/test_movie_ui_qwen_edit.py's server env fixture by import (the in-test
server and stub workspace, lib.seed_edit_check a recorder answering in _probe's shape, lib.shared_checks a pass
stub). Every test sets HOME, HF_HOME and Z_IMAGE_HF_HOME under tmp_path and removes HF_HUB_CACHE and every
SEED_EDIT_* variable. Review Focus 5 runs bin/ltx-movie's Phase 2 with tests/test_ltx_movie_shots_seed.py's
multi-job fake. No test uses the real HOME, renders, dispatches a job or contacts a server other than the in-test
127.0.0.1 one; none touches port 8177 or 8178. Stdlib, PIL and pytest.
"""

import os
import re
import shutil
import subprocess

import pytest

import movie_ui_testutil as mt
import movie_ui_batch as batch
import movie_ui_lib as lib
import test_ltx_movie_shots_seed as sse
from test_movie_ui_qwen_edit import _clean_env, _compose, _function, _job, _probe, _upload, env  # noqa: F401

WS = mt.WS
UP = "a" * 64 + ".png"
UNC = [{"id": "uncensored", "scale": 1.0}]
NEEDS_MODEL = ("a seed image in shots mode needs a Qwen edit model: every panel's still is an edit of the seed, so "
               "the seed cannot be used as-is")
NEEDS_ENGINE = "a seed image in shots mode needs the default story engine; it cannot be combined with --story-legacy"
NO_STILLS_LORAS = ("stills LoRAs do not apply in shots mode with a seed image: every panel's still is a Qwen edit "
                   "of the seed")
FLAGS = {"--story-id", "--panels", "--length", "--fps", "--frames", "--video-width", "--video-height",
         "--seed-image", "--model", "--gemma", "--story-model", "--goal", "--shots", "--no-stills", "--lora",
         "--stills-lora", "--character", "--location", "--location-strength", "--action", "--no-auto-lora",
         "--no-narration", "--speech-only", "--story-legacy", "--judge", "--no-low-ram", "--panel-timeout",
         "--force", "--force-story", "--redo", "--story-only", "--no-review", "--seed-edit-model",
         "--seed-edit-lora"}


@pytest.fixture
def v1_env(monkeypatch, tmp_path):
    """tests/test_movie_ui_checks.py's env with spec 6.1's variables, and the seed upload UP in the uploads."""
    state = mt.set_home(monkeypatch, tmp_path)
    _clean_env(monkeypatch, tmp_path)
    ws = mt.make_stub_workspace(tmp_path)
    with open(os.path.join(state, "uploads", UP), "wb") as f:
        f.write(mt.PNG)
    return {"state": state, "ws": ws, "tmp": str(tmp_path)}


def _errors(v1_env, **overrides):
    return lib.validate_fields(mt.fields(v1_env["ws"], **overrides), v1_env["ws"], v1_env["state"])


# --- SET16 (SE23): V1 rule 8 in shots mode with a seed image ---------------------------------------------------

def test_set16_v1_rule_8_in_shots_mode(v1_env):
    shots = dict(seed_upload=UP, mode="shots")
    for model in (None, "as-is"):
        assert _errors(v1_env, seed_edit_model=model, **shots) == [NEEDS_MODEL], model
    assert _errors(v1_env, seed_edit_model="qwen21-q4", **shots) == []
    assert _errors(v1_env, seed_edit_model="qwen21-q4", seed_edit_loras=UNC, **shots) == []
    assert _errors(v1_env, seed_edit_model="qwen21-q4", story_legacy=True, **shots) == [NEEDS_ENGINE]
    stills = [{"id": None, "path": "/a.safetensors", "strength": 1, "kind": None}]
    assert _errors(v1_env, seed_edit_model="qwen21-q4", stills_loras=stills, **shots) == [NO_STILLS_LORAS]
    assert _errors(v1_env, seed_upload=UP, mode="chained") == []
    assert _errors(v1_env, mode="shots", stills_loras=stills) == []


# --- SET17 (SE24, SE26): the argv is unchanged, and shots seed jobs have no phase 1c -------------------------

def test_set17_argv_and_phases(v1_env):
    state = v1_env["state"]
    f = mt.fields(WS, seed_upload=UP, action="movie", mode="shots", seed_edit_model="qwen21-q4",
                  seed_edit_loras=[{"id": "uncensored", "scale": 1}])
    argv = lib.build_argv(f, WS, state)
    i = argv.index("--seed-image")
    assert argv[i - 4:i + 6] == ["--fps", "24", "--frames", "145", "--seed-image", os.path.join(state, "uploads", UP),
                                 "--seed-edit-model", "qwen21-q4", "--seed-edit-lora", "uncensored=1.0"]
    assert argv.count("--shots") == 1
    assert lib.job_phases("movie", f) == ["0", "1", "1b", "2", "3", "4"]
    assert lib.job_phases("movie", dict(f, action="redo", redo=[2])) == ["0", "1", "1b", "redo", "2", "3", "4"]
    assert lib.job_phases("movie", dict(f, mode="chained")) == ["0", "1", "1b", "1c", "2", "3", "4"]
    assert lib.job_phases("story", f) == ["0", "1"]


# --- SET18 (SE25): the 409 rule for movie and redo jobs, and seed folders in shots mode ----------------------

def test_set18_the_409_rule_for_movie_and_redo_jobs_and_seed_folders(env):
    s, ws, state, probes = env["srv"], env["ws"], env["state"], env["probes"]
    up = _upload(s)
    q8 = ("mflux-community/qwen-image-2-1-mflux-q8@f5c8cc79a674 is not in /z or /h "
          "(run bin/seed-edit-setup --model qwen21-q8)")
    probes["answer"] = (_probe(models={"qwen21-q8": {"ok": False, "reason": q8}}), None)
    shots = dict(mode="shots", seed_edit_model="qwen21-q8")
    sdir = os.path.join(ws, "generated", "stories", "shots-redo")
    os.makedirs(sdir)
    with open(os.path.join(sdir, "story.md"), "w", encoding="utf-8") as f:
        f.write("x")
    movie_body = _compose(ws, up, story_id="shots-seed", **shots)
    redo_body = _compose(ws, up, story_id="shots-redo", action="redo", redo=[2], **shots)
    for body in (movie_body, redo_body):
        status, _h, payload = mt.api(s, "POST", "/api/jobs", body=body)
        assert (status, payload.get("error")) == (409, "Qwen-Image-2.1 q8 is unavailable: " + q8), body["action"]
    assert lib.list_job_ids(state) == [] and probes["calls"] == [ws, ws]
    probes["answer"] = (_probe(), None)
    for body in (movie_body, redo_body):
        status, _h, payload = mt.api(s, "POST", "/api/jobs", body=body)
        assert status == 201, payload
        argv = _job(state, payload)["argv"]
        assert "--shots" in argv and argv[argv.index("--seed-edit-model") + 1] == "qwen21-q8", body["action"]
    assert "--redo" in argv and len(probes["calls"]) == 4
    seeds = [{"name": "alpha.png", "upload_id": _upload(s, mt.PNG + b"a")},
             {"name": "beta.png", "upload_id": _upload(s, mt.PNG + b"b")}]
    folder = dict(mt.fields(ws, story_id="", action="movie", mode="shots", seed_edit_model="qwen21-q4"), seeds=seeds,
                  preview=False)
    jobs = len(lib.list_job_ids(state))
    status, _h, payload = mt.api(s, "POST", "/api/jobs/seed-folder", body=folder)
    assert status == 201, payload
    assert [r["status"] for r in payload["seeds"]] == ["ok", "ok"] and payload["queued"] == 2
    assert len(lib.list_job_ids(state)) == jobs + 2
    for row in payload["seeds"]:
        argv = lib.read_job(lib.job_dir(state, row["job"]["id"]))["argv"]
        assert "--shots" in argv and argv[argv.index("--seed-edit-model") + 1] == "qwen21-q4"
    status, _h, payload = mt.api(s, "POST", "/api/jobs/seed-folder", body=dict(folder, seed_edit_model=None))
    assert status == 409, payload
    assert [(r["status"], r["reason"]) for r in payload["seeds"]] == [("refused", NEEDS_MODEL)] * 2
    assert len(lib.list_job_ids(state)) == jobs + 2


# --- SET19 (SE27): a render-level fork copies seed_edits.json ------------------------------------------------

def test_set19_a_render_fork_copies_seed_edits_json(v1_env):
    sdir = os.path.join(v1_env["tmp"], "story")
    os.makedirs(os.path.join(sdir, "images"))
    for rel in ("story.md", "seed_edits.json", "seed_edit.json", "seed-original.png", "images/panel_01.png"):
        with open(os.path.join(sdir, rel), "w", encoding="utf-8") as f:
            f.write("x")
    assert [rel for rel, _n in batch.copy_plan(sdir, "render")] == ["images/panel_01.png", "seed_edits.json",
                                                                    "story.md"]
    for level in ("stills", "replan"):
        assert "seed_edits.json" not in [rel for rel, _n in batch.copy_plan(sdir, level)], level
    assert batch.COPY_FILES["render"] == ("story.md", "plan.json", "story_checks.json", "story_prompt.txt",
                                          "catalog_loras.json", "manifest.json", "seed_edits.json")


# --- SET21 (SE28): no new field flag ---------------------------------------------------------------------------

def test_set21_no_new_field_flag(v1_env):
    assert len(lib.FIELD_FLAGS) == 31
    assert lib.FIELD_FLAGS[-1] == ("seed_edit", ("--seed-edit-model", "--seed-edit-lora"))
    assert set(flag for _key, flags in lib.FIELD_FLAGS for flag in flags) == FLAGS


# --- Review Focus 5: a render-level batch fork of a shots seed story reuses every still ---------------------

def test_sse_review_focus_5_a_render_fork_reuses_every_still(monkeypatch, tmp_path, capsys):
    tmp = str(tmp_path)
    monkeypatch.setenv("HOME", os.path.join(tmp, "home"))
    _clean_env(monkeypatch, tmp_path)
    fake = sse._FakeShotsQwenEdit()
    monkeypatch.setattr(sse.movie, "_qwen_edit", lambda: fake)
    monkeypatch.setattr(sse.movie, "_story_dir", lambda story_id: os.path.join(tmp, "stories", story_id))
    sdir = sse._write_story(tmp)
    assert sse.movie._phase2_shots_seed(sse._phase_args(tmp)) == 0
    fork = os.path.join(tmp, "stories", "s1-b1-v1")
    for rel, _n in batch.copy_plan(sdir, "render"):
        os.makedirs(os.path.dirname(os.path.join(fork, rel)), exist_ok=True)
        shutil.copy2(os.path.join(sdir, rel), os.path.join(fork, rel))
    capsys.readouterr()
    assert sse.movie._phase2_shots_seed(sse._phase_args(tmp, story_id="s1-b1-v1")) == 0
    assert len(fake.calls["run_jobs"]) == 1
    assert capsys.readouterr().out.splitlines()[-1] == (
        "seed edits: every panel's still is a recorded edit of the same seed image, prompt, seed and settings; "
        "nothing to edit")
    assert not os.path.exists(os.path.join(fork, "seed-original.png"))


# --- SET20 (SE29-SE32): the static page ------------------------------------------------------------------------

LABEL = '<label><span id="c-sq-label">Panel 1 from the seed</span> <select id="c-sq-qwen-model"></select></label>'
SHOTS_NOTE = ("<p id=\"c-sq-shots-note\" class=\"muted\" hidden>Every panel's still is a Qwen edit of the seed, "
              "prompted by that panel's own Image: text. Z-Image is not used: stills LoRAs, and the stills LoRAs of "
              "characters and locations, do not apply (characters and locations still shape the story and the "
              "video).</p>")
ACTIVE = ('    return supported.seed_edit !== false && (mode === "chained" || mode === "shots")\n'
          '      && (($("#c-res-seed").checked && Boolean(S.seedUpload)) || $("#c-res-folder").checked);\n')
SE31 = ('    const shotsSeed = seedEditOn && mode === "shots";\n'
        '    if (shotsSeed && COMPOSE_PICKER.state && COMPOSE_PICKER.state.model === "as-is") {\n'
        '      COMPOSE_PICKER.select(null, null);\n'
        '      COMPOSE_PICKER.update();\n'
        '    }\n'
        '    const asIsOption = $("#c-sq-qwen-model").options[0];\n'
        '    if (asIsOption && asIsOption.value === "as-is") {\n'
        '      asIsOption.disabled = shotsSeed;\n'
        '      asIsOption.textContent = shotsSeed ? "Seed as-is (no edit) — chained mode only" '
        ': "Seed as-is (no edit)";\n'
        '    }\n'
        '    $("#c-sq-label").textContent = mode === "shots" ? "Every panel from the seed" : "Panel 1 from the seed";\n'
        '    show($("#c-sq-shots-note"), shotsSeed);\n')


def test_set20_the_page(v1_env):
    static = os.path.join(WS, "static", "movie-ui")
    with open(os.path.join(static, "index.html"), encoding="utf-8") as f:
        html = f.read()
    with open(os.path.join(static, "app.js"), encoding="utf-8") as f:
        js = f.read()
    assert html.count("          " + LABEL + "\n") == 1
    assert html.count('          <p id="c-sq-qwen-note" class="muted"></p>\n          ' + SHOTS_NOTE + "\n") == 1
    for ident in ('id="c-sq-label"', 'id="c-sq-shots-note"'):
        assert html.count(ident) == 1, ident
    box = html.index('<div id="c-sq-qwen-box" hidden>')
    assert box < html.index(LABEL) < html.index(SHOTS_NOTE) < html.index('id="c-sq-reason"') < html.index(
        "</fieldset>", box)
    active = _function(js, "  function composeSeedEditActive() {")
    assert '    const mode = $("#c-mode").value;\n' + ACTIVE in active
    buttons = _function(js, "  function updateComposeButtons() {")
    assert ('    COMPOSE_PICKER.update();\n    const seedEditOn = composeSeedEditActive();\n'
            '    // Shots seed edits spec SE31: in shots mode every panel is an edit of the seed, so "Seed as-is" is '
            'not offered.\n' + SE31 + '    show($("#c-sq-qwen-box"), seedEditOn);\n') in buttons
    for name, text in (("index.html", html), ("app.js", js)):
        for pattern in (r"https?://", r"\son[a-z]+=", r"style=", r"\balert\(", r"\bconfirm\(", r"\bprompt\(",
                        r"\beval\(", r"new Function"):
            assert not re.search(pattern, text), (name, pattern)
    node = shutil.which("node")
    if node:
        proc = subprocess.run([node, "--check", os.path.join(static, "app.js")], capture_output=True, text=True,
                              timeout=60)
        assert proc.returncode == 0, proc.stderr
