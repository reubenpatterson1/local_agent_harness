"""Tests for the movie-UI seams check (docs/superpowers/specs/2026-10-30-chained-end-frames-
design.md, Sections 4 and 6: CT23-CT28, with the plan's Review Focus pins 4 and 5): the seams job
kind, POST /api/stories/<id>/seams, Compose's check_seams option, the Stories tab's report and
the static page.

Run from the workspace root: python3 -m pytest -q -p no:cacheprovider tests/test_movie_ui_seams.py
Stdlib plus pytest. No test renders, reads the real HOME, or contacts a model server, a daemon,
ffmpeg or the Anthropic API: the only server is the in-test movie-UI server on 127.0.0.1 under a
temporary HOME (movie_ui_testutil), every workspace is the stub workspace, the VLM lifecycle is
off (MOVIE_UI_VLM_LIFECYCLE=0, conftest.py), and the one seams job that runs (CT28) stops at "no
clips to check" before it would contact any server.
"""

import json
import os
import re
import shutil
import subprocess
import sys

import pytest

import movie_ui_testutil as mt
import movie_ui_lib as lib
import movie_ui_server as srv

WS = mt.WS
END_FRAME = "The courier stands at frame centre on the wet quay, facing the camera, seen from the waist up."
REPORT = {"schema": "ltx-movie.seam-report.v1", "story_id": "ronin-rescue",
          "created": "2026-10-31T12:00:00Z", "model": "test-vlm", "threshold": 6,
          "panels": [{"panel": 1, "end_frame": END_FRAME, "source": "chainseed",
                      "frame": "clips/panel_02.chainseed.png", "score": 4, "verdict": "missed",
                      "reason": "The courier faces left.", "missing": ["facing the camera"],
                      "attempts": 1}],
          "summary": {"panels": 1, "scored": 1, "ok": 0, "missed": 1, "no_clip": 0,
                      "unparseable": 0, "mean_score": 4.0}}


@pytest.fixture
def env(monkeypatch, tmp_path):
    monkeypatch.setenv("MOVIE_UI_VLM_LIFECYCLE", "0")
    state = mt.set_home(monkeypatch, tmp_path)
    ws = mt.make_stub_workspace(tmp_path)
    running = mt.Running(state)
    yield {"state": state, "ws": ws, "tmp": str(tmp_path), "srv": running}
    running.close()
    mt.kill_everything(state)


def _plan(mode="chained", end_frames=True):
    beats = [{"index": k, "arc": "rising", "action": "the courier rides on", "cast": ["c1"]}
             for k in (1, 2)]
    if end_frames:
        beats[1]["end_frame"] = END_FRAME
    return {"schema": "ltx-movie.plan.v1", "mode": mode, "beats": beats,
            "cast": [{"id": "c1", "phrase": "the courier", "descriptor": "a young man"}]}


def _story(ws, story_id="ronin-rescue", plan=None, report=None):
    """generated/stories/<story_id>/ with plan.json (a dict, raw text, or none) and
    seam_report.json (a dict, raw text, or none); returns its directory."""
    sdir = os.path.join(ws, "generated", "stories", story_id)
    os.makedirs(sdir, exist_ok=True)
    for name, value in (("plan.json", plan), ("seam_report.json", report)):
        if value is not None:
            with open(os.path.join(sdir, name), "w", encoding="utf-8") as f:
                f.write(value if isinstance(value, str) else json.dumps(value))
    return sdir


def _passing_checks(monkeypatch):
    monkeypatch.setattr(lib, "run_checks",
                        lambda fields, ws_real, state, py=None: [lib.check("V1", "fields", "pass")])


def _jobs_of(state, kind):
    return [i for i in lib.list_job_ids(state) if lib.read_job(lib.job_dir(state, i))["kind"] == kind]


# --- CT23: the seams job kind, its argv and the plan test (CE14) ----------------------------------

def test_ct23_the_seams_job_policy_argv_and_plan_test(monkeypatch, tmp_path):
    monkeypatch.delenv("MOVIE_UI_VLM_PORT", raising=False)
    ws = str(tmp_path)
    assert lib.job_vlm("seams", {}, ws, "s1") == "required"
    assert lib.seams_argv(ws, "s1") == [sys.executable, ws + "/bin/seam-report", "s1", "--port",
                                        "8177"]
    assert lib.seams_argv(ws, "s1", py="/usr/bin/python3")[0] == "/usr/bin/python3"
    monkeypatch.setenv("MOVIE_UI_VLM_PORT", "9001")
    assert lib.seams_argv(ws, "s1")[-2:] == ["--port", "9001"]
    assert lib.plan_has_end_frames(_plan()) is True
    for plan in (None, {}, [], _plan(mode="shots"), _plan(end_frames=False),
                 {"mode": "chained", "beats": [{"end_frame": "   "}, {"end_frame": ""}]},
                 {"mode": "chained", "beats": [{"end_frame": 5}, "x", None]},
                 {"mode": "chained", "beats": "x"}, {"mode": "chained", "beats": []}):
        assert lib.plan_has_end_frames(plan) is False, plan


# --- CT24: POST /api/stories/<id>/seams (CE14) ----------------------------------------------------

def test_ct24_the_check_seams_route(env, monkeypatch):
    monkeypatch.delenv("MOVIE_UI_VLM_PORT", raising=False)
    s, ws, state = env["srv"], env["ws"], env["state"]
    _story(ws, plan=_plan())
    path = "/api/stories/ronin-rescue/seams"
    status, _h, created = mt.api(s, "POST", path, body={"ws": ws})
    assert status == 201, created
    job = created["job"]
    assert (job["kind"], job["state"], job["story_id"], job["workspace"]) == (
        "seams", "queued", "ronin-rescue", ws)
    assert job["command"].endswith("seam-report ronin-rescue --port 8177")
    record = lib.read_job(lib.job_dir(state, job["id"]))
    assert record["vlm"] == "required"
    assert record["argv"] == lib.seams_argv(ws, "ronin-rescue")
    assert record["fields"] == {"ws": ws, "story_id": "ronin-rescue"}
    assert lib.read_queue(state)[-1] == job["id"]
    assert mt.api(s, "POST", path, body={"ws": ws})[::2] == (
        409, {"error": "a seams check of ronin-rescue is already queued as job %s" % job["id"]})
    lib.write_queue(state, [i for i in lib.read_queue(state) if i != job["id"]])
    lib.write_status(lib.job_dir(state, job["id"]), {"state": "done", "exit_code": 0})
    assert mt.api(s, "POST", path, body={"ws": ws})[0] == 201
    stories = os.path.join(ws, "generated", "stories")
    assert mt.api(s, "POST", "/api/stories/nope/seams", body={"ws": ws})[::2] == (
        404, {"error": "no story nope in %s" % stories})
    _story(ws, "old-story", plan=_plan(end_frames=False))
    assert mt.api(s, "POST", "/api/stories/old-story/seams", body={"ws": ws})[::2] == (
        409, {"error": "story old-story has no end frames to check"})
    _story(ws, "shots-story", plan=_plan(mode="shots"))
    assert mt.api(s, "POST", "/api/stories/shots-story/seams", body={"ws": ws})[0] == 409
    _story(ws, "no-plan")
    assert mt.api(s, "POST", "/api/stories/no-plan/seams", body={"ws": ws})[0] == 409
    for token in (None, "wrong-token"):
        assert mt.api(s, "POST", path, body={"ws": ws}, token=token)[::2] == (
            401, {"error": "missing or invalid token"})
    assert ("POST", r"/api/stories/" + srv._STORY + r"/seams", "h_story_seams",
            "/api/stories/ronin-rescue/seams") in srv.ROUTES
    assert len(_jobs_of(state, "seams")) == 2


# --- CT25: Compose's check_seams option (CE14, D12) ------------------------------------------------

def test_ct25_run_all_queues_the_seams_job_right_behind_the_movie(env, monkeypatch):
    monkeypatch.delenv("MOVIE_UI_VLM_PORT", raising=False)
    s, ws, state = env["srv"], env["ws"], env["state"]
    _passing_checks(monkeypatch)
    movie = mt.fields(ws, action="movie", mode="chained")
    status, _h, created = mt.api(s, "POST", "/api/jobs", body=dict(movie, check_seams=True))
    assert status == 201, created
    assert created["job"]["kind"] == "movie"
    seams = _jobs_of(state, "seams")
    assert len(seams) == 1
    assert lib.read_queue(state)[-2:] == [created["job"]["id"], seams[0]]
    record = lib.read_job(lib.job_dir(state, seams[0]))
    assert record["argv"] == [sys.executable, ws + "/bin/seam-report", "ronin-rescue", "--port",
                              "8177"]
    assert (record["story_id"], record["workspace"], record["vlm"]) == ("ronin-rescue", ws,
                                                                        "required")
    assert "check_seams" not in lib.read_job(lib.job_dir(state, created["job"]["id"]))["fields"]
    for body in (movie, dict(movie, check_seams=False), dict(movie, check_seams="true"),
                 dict(movie, check_seams=1),
                 dict(mt.fields(ws, action="movie", mode="shots"), check_seams=True),
                 dict(mt.fields(ws, action="story", mode="chained"), check_seams=True)):
        assert mt.api(s, "POST", "/api/jobs", body=body)[0] == 201, body
    assert len(_jobs_of(state, "seams")) == 1


# --- CT25, fix round 1: the after link (CE14; Task 6 review I1, Minor 5) -----------------------

def _record_vlm(monkeypatch, tmp):
    """The VLM lifecycle on, with story-server and story-server-restore stubs that append one line
    per call to the returned calls file; the dispatcher's own restore queue is empty."""
    tools = os.path.join(tmp, "vlm-tools")
    os.makedirs(tools)
    calls = os.path.join(tools, "calls.txt")
    for tool in ("story-server", "story-server-restore"):
        path = os.path.join(tools, tool)
        with open(path, "w", encoding="utf-8") as f:
            f.write('#!/bin/sh\necho "%s $*" >> "%s"\n' % (tool, calls))
        os.chmod(path, 0o755)
    monkeypatch.setenv("MOVIE_UI_VLM_LIFECYCLE", "1")
    monkeypatch.setenv("MOVIE_UI_VLM_TOOLS", tools)
    monkeypatch.setenv("MOVIE_UI_VLM_PORT", "9")
    monkeypatch.setattr(lib, "VLM_RECOVERY", [])
    return calls


def _record_launches(monkeypatch):
    """lib.launch_runner records the job IDs it is asked to start and starts nothing."""
    launched = []
    monkeypatch.setattr(lib, "launch_runner", lambda state, job_id, ui_ws: launched.append(job_id))
    return launched


def _tick(state):
    with srv.STORE_LOCK:
        return lib.dispatch_tick(state, mt.WS)


def _after_seams(state, ws, movie):
    with srv.STORE_LOCK:
        return srv._create_seams_job(state, ws, "ronin-rescue", after=movie)


def _skipped(state, seams, reason):
    status = mt.status_of(state, seams)
    assert (status["state"], status["exit_code"], status["error"]) == ("cancelled", None, reason)
    assert mt.read_log(state, seams) == "[movie-ui] %s\n" % reason
    assert seams not in lib.read_queue(state)


def test_ct25_a_movie_cancelled_while_queued_skips_its_seams_job(env, monkeypatch):
    monkeypatch.delenv("MOVIE_UI_VLM_PORT", raising=False)
    s, ws, state = env["srv"], env["ws"], env["state"]
    _passing_checks(monkeypatch)
    created = mt.api(s, "POST", "/api/jobs", body=dict(mt.fields(ws, action="movie",
                                                                 mode="chained"), check_seams=True))[2]
    movie, seams = created["job"]["id"], _jobs_of(state, "seams")[0]
    assert lib.read_queue(state) == [movie, seams]
    assert lib.read_job(lib.job_dir(state, seams))["fields"] == {
        "ws": ws, "story_id": "ronin-rescue", "after": movie}
    assert sorted(created) == ["checks", "job"]
    assert mt.api(s, "POST", "/api/jobs/%s/cancel" % movie, body={})[::2] == (200, {"state": "cancelled"})
    calls = _record_vlm(monkeypatch, env["tmp"])
    launched = _record_launches(monkeypatch)
    assert _tick(state) is None
    _skipped(state, seams, "skipped: movie %s ended cancelled" % movie)
    assert launched == [] and not os.path.exists(calls)
    assert mt.api(s, "GET", "/api/jobs")[0] == 200


def test_ct25_a_failed_movie_skips_its_seams_job_and_the_next_job_runs(env, monkeypatch):
    ws, state = env["ws"], env["state"]
    mt.stub_config(ws, {"ltx-movie run": {"exit": 1, "stderr": "render failed\n"}})
    movie = mt.make_job(state, [os.path.join(ws, "bin", "ltx-movie"), "a narrative", "--story-id",
                                "ronin-rescue"], ws, story_id="ronin-rescue")
    seams = _after_seams(state, ws, movie)
    other = mt.make_job(state, mt.py_argv("print('next')"), ws, kind="smoke")
    mt.dispatch(state, movie)
    _wait_finished(state, movie)
    assert mt.status_of(state, movie)["state"] == "failed"
    calls = _record_vlm(monkeypatch, env["tmp"])
    assert lib.next_queued_job(state)[0] == other
    assert lib.vlm_restore_wanted(state) == (False, "next job %s runs without it" % other)
    launched = _record_launches(monkeypatch)
    assert _tick(state) == other
    _skipped(state, seams, "skipped: movie %s ended failed" % movie)
    assert launched == [other] and not os.path.exists(calls)
    assert lib.read_queue(state) == []


def test_ct25_a_done_movie_runs_its_seams_job(env):
    ws, state = env["ws"], env["state"]
    shutil.copy(os.path.join(WS, "bin", "seam-report"), os.path.join(ws, "bin", "seam-report"))
    sdir = _story(ws, plan=_plan())
    movie = mt.make_job(state, ["true"], ws, story_id="ronin-rescue",
                        status={"state": "done", "exit_code": 0, "ended": lib.utc_now()})
    seams = _after_seams(state, ws, movie)
    assert lib.seams_skip_reason(state, lib.read_job(lib.job_dir(state, seams)),
                                 lib.read_queue(state)) is None
    assert lib.next_queued_job(state)[0] == seams
    assert _tick(state) == seams
    _wait_finished(state, seams)
    assert (mt.status_of(state, seams)["state"], mt.status_of(state, seams)["exit_code"]) == (
        "done", 0)
    lines = mt.read_log(state, seams).splitlines()
    assert [line for line in lines if not line.startswith("[movie-ui] ")][-1] == (
        "seam-report: no clips to check in %s" % os.path.join(sdir, "clips"))


def test_ct25_a_seams_job_never_runs_ahead_of_its_movie(env, monkeypatch):
    ws, state = env["ws"], env["state"]
    movie = mt.make_job(state, mt.py_argv("print('render')"), ws, story_id="ronin-rescue")
    seams = _after_seams(state, ws, movie)
    assert lib.read_queue(state) == [movie, seams]
    with srv.STORE_LOCK:
        assert lib.move_job(state, seams, "up") == [seams, movie]
    calls = _record_vlm(monkeypatch, env["tmp"])
    launched = _record_launches(monkeypatch)
    assert _tick(state) == movie
    _skipped(state, seams, "skipped: movie %s has not run yet" % movie)
    assert launched == [movie] and not os.path.exists(calls)
    gone = _after_seams(state, ws, "20261031-120000-abcd")
    assert lib.seams_skip_reason(state, lib.read_job(lib.job_dir(state, gone)), []) == (
        "skipped: movie 20261031-120000-abcd no longer exists")
    lost = mt.make_job(state, ["true"], ws, status={"state": "lost", "exit_code": None})
    assert lib.seams_skip_reason(state, {"kind": "seams", "fields": {"after": lost}}, []) == (
        "skipped: movie %s ended lost" % lost)
    for job in ({"kind": "seams", "fields": {"ws": ws, "story_id": "ronin-rescue"}},
                {"kind": "seams", "fields": None}, {"kind": "movie", "fields": {"after": lost}}):
        assert lib.seams_skip_reason(state, job, []) is None, job


# --- CT26: the Stories tab's data (CE14) ----------------------------------------------------------

def test_ct26_get_story_has_end_frames_and_the_report(env):
    s, ws = env["srv"], env["ws"]
    _story(ws, plan=_plan(), report=REPORT)
    data = mt.api(s, "GET", "/api/stories/ronin-rescue?ws=" + ws)[2]
    assert (data["end_frames"], data["seams"], data["plan_mode"]) == (True, REPORT, "chained")
    _story(ws, "old-story", plan=_plan(end_frames=False))
    data = mt.api(s, "GET", "/api/stories/old-story?ws=" + ws)[2]
    assert (data["end_frames"], data["seams"]) == (False, None)
    _story(ws, "bare")
    data = mt.api(s, "GET", "/api/stories/bare?ws=" + ws)[2]
    assert (data["end_frames"], data["seams"], data["plan_mode"]) == (False, None, None)


# --- CT27: the static page (CE15) -------------------------------------------------------------------

HTML_SNIPPETS = (
    '    <button id="c-run-all" type="button">Run all</button> <span id="c-run-all-reason" '
    'class="muted"></span>\n    <label id="c-check-seams-box"><input id="c-check-seams" '
    'type="checkbox" checked> Check seams after render</label>\n',
    '      <button id="s-regenerate" type="button">Regenerate story</button>\n'
    '      <button id="s-seams" type="button" hidden>Check seams</button>\n',
    '    <div id="s-checks"></div>\n'
    '    <div id="s-seams-box" hidden>\n'
    '      <h3>Seams</h3>\n'
    '      <p id="s-seams-summary" class="muted"></p>\n'
    '      <table id="s-seams-table" class="list"><thead><tr><th>Panel</th><th>Score</th>'
    '<th>Verdict</th><th>Reason</th></tr></thead><tbody></tbody></table>\n'
    '    </div>\n',
)
JS_SNIPPETS = (
    '"/seams"',
    'check_seams: $("#c-mode").value === "chained" && $("#c-check-seams").checked',
    '"seam-missed"', '"This plan has no end frames; no seam report."',
    '"No seam report yet: press Check seams."', "showSeams(res.data);",
    '"seams check queued as job "', 'show($("#c-check-seams-box"), mode === "chained");',
    '(Array.isArray(report.panels) ? report.panels : []).forEach(function (p) {\n'
    '      if (!p || typeof p !== "object") { return; }\n',
    'const TABS = ["compose", "stories", "batches", "characters", "locations", "actions", "loras", '
    '"jobs", "traces"];',
)


def test_ct27_the_static_page():
    static = os.path.join(WS, "static", "movie-ui")
    texts = {}
    for name in ("index.html", "app.js", "app.css"):
        with open(os.path.join(static, name), encoding="utf-8") as f:
            texts[name] = f.read()
    for snippet in HTML_SNIPPETS:
        assert texts["index.html"].count(snippet) == 1, snippet[:60]
    for snippet in JS_SNIPPETS:
        assert snippet in texts["app.js"], snippet
    assert texts["app.js"].count("function showSeams(data)") == 1
    assert "(report.panels || [])" not in texts["app.js"]
    assert texts["app.js"].index("function showSeams(data)") < texts["app.js"].index(
        "async function openStory(storyId)")
    assert ".seam-missed td { background: var(--warn-bg); }\n" in texts["app.css"]
    for name, text in texts.items():
        for pattern in (r"https?://", r"\son[a-z]+=", r"style=", r"\balert\(", r"\bconfirm\(",
                        r"\bprompt\(", r"\beval\(", r"new Function"):
            assert not re.search(pattern, text), (name, pattern)
    assert re.findall(r"<script[^>]*>", texts["index.html"]) == ['<script src="/static/app.js" defer>']
    node = shutil.which("node")
    if node:
        proc = subprocess.run([node, "--check", os.path.join(static, "app.js")],
                              capture_output=True, text=True)
        assert proc.returncode == 0, proc.stderr


# --- CT28: a failed movie, then its seams job (CE14, D11) ----------------------------------------

def _wait_finished(state, job_id):
    return mt.wait_until(lambda: mt.status_of(state, job_id).get("state")
                         in ("done", "failed", "cancelled"), 30)


def test_ct28_the_seams_job_of_a_failed_movie_ends_done(env):
    ws, state = env["ws"], env["state"]
    shutil.copy(os.path.join(WS, "bin", "seam-report"), os.path.join(ws, "bin", "seam-report"))
    sdir = _story(ws, plan=_plan())
    mt.stub_config(ws, {"ltx-movie run": {"exit": 1, "stderr": "render failed\n"}})
    movie = mt.make_job(state, [os.path.join(ws, "bin", "ltx-movie"), "a narrative", "--story-id",
                                "ronin-rescue"], ws, story_id="ronin-rescue")
    with srv.STORE_LOCK:
        seams = srv._create_seams_job(state, ws, "ronin-rescue")
    assert lib.read_queue(state) == [movie, seams]
    mt.dispatch(state, movie)
    _wait_finished(state, movie)
    assert mt.status_of(state, movie)["state"] == "failed"
    assert not os.path.exists(os.path.join(sdir, "clips"))
    mt.dispatch(state, seams)
    _wait_finished(state, seams)
    assert (mt.status_of(state, seams)["state"], mt.status_of(state, seams)["exit_code"]) == (
        "done", 0)
    lines = mt.read_log(state, seams).splitlines()
    child = [line for line in lines if not line.startswith("[movie-ui] ")]
    assert child[-1] == "seam-report: no clips to check in %s" % os.path.join(sdir, "clips")
    assert lines[-1] == "[movie-ui] exit 0 (done)"
    assert sorted(os.listdir(sdir)) == ["plan.json"]


# --- Review Focus 4, 5 -----------------------------------------------------------------------------

def test_review_focus_4_a_malformed_seam_report_reads_as_none(env):
    s, ws = env["srv"], env["ws"]
    _story(ws, plan=_plan(), report='{"schema": "ltx-movie.seam-report.v1", "panels": [')
    data = mt.api(s, "GET", "/api/stories/ronin-rescue?ws=" + ws)[2]
    assert (data["end_frames"], data["seams"]) == (True, None)
    assert mt.api(s, "POST", "/api/stories/ronin-rescue/seams", body={"ws": ws})[0] == 201


def test_review_focus_5_a_refused_run_all_queues_no_seams_job(env, monkeypatch):
    s, ws, state = env["srv"], env["ws"], env["state"]
    monkeypatch.setattr(lib, "run_checks", lambda fields, ws_real, state, py=None: [
        lib.check("V1", "fields", "fail", "panels must be an integer from 1 to 200")])
    status, _h, refused = mt.api(s, "POST", "/api/jobs", body=dict(
        mt.fields(ws, action="movie", mode="chained"), check_seams=True))
    assert (status, refused["error"]) == (409, "validation failed")
    assert lib.read_queue(state) == [] and lib.list_job_ids(state) == []
