"""Tests for the VLM lifecycle at job boundaries (docs/superpowers/specs/2026-10-25-vlm-lifecycle-
design.md, Section 11: VL1-VL28 and Review Focus 1, 2, 4, 5): the per-job vlm policy, the
port-scoped health check, the runner's preflight and postflight, the startup restore, V2's warn
and the page gate.

Run from the workspace root: python3 -m pytest -q -p no:cacheprovider tests/test_vlm_lifecycle.py
Stdlib plus pytest. Every story-server and story-server-restore here is F-TOOLS (make_fake_tools),
every VLM is F-HTTP (FakeVLM) on an ephemeral 127.0.0.1 port, every HOME is temporary, and the
conftest's vlm_lifecycle_isolation keeps the lifecycle off unless a test turns it on with
lifecycle_on(); VL22 alone runs the real bin/story-server-restore, against a fake story-server.
"""

import fcntl
import http.server
import json
import os
import shlex
import signal
import subprocess
import sys
import threading
import time

import pytest

import movie_ui_testutil as mt
import movie_ui_lib as lib


@pytest.fixture
def state(monkeypatch, tmp_path):
    path = mt.set_home(monkeypatch, tmp_path)
    monkeypatch.setattr(lib, "VLM_RECOVERY", [])
    monkeypatch.setattr(lib, "RESTORERS", [])
    yield path
    mt.kill_everything(path)


@pytest.fixture
def http_env(monkeypatch, tmp_path):
    state = mt.set_home(monkeypatch, tmp_path)
    monkeypatch.setattr(lib, "VLM_RECOVERY", [])
    ws = mt.make_stub_workspace(tmp_path)
    running = mt.Running(state)
    yield {"state": state, "ws": ws, "srv": running, "tmp": str(tmp_path)}
    running.close()
    mt.kill_everything(state)


def _write_story(ws, story_id):
    sdir = lib.story_dir(ws, story_id)
    os.makedirs(sdir, exist_ok=True)
    with open(os.path.join(sdir, "story.md"), "w", encoding="utf-8") as f:
        f.write("## Panel 1 -- Shot 1\nImage: a quiet road.\nMotion: the camera drifts.\n")


# --- the constants, the switches and the isolation (spec 2.5, VR1, 11.1) ---------------------

def test_vlm_constants_and_isolation(tmp_path):
    assert (lib.VLM_MODE, lib.VLM_POLICIES) == ("mlx-vision", ("required", "forbidden", "any"))
    assert (lib.VLM_STATUS_TIMEOUT_S, lib.VLM_HTTP_TIMEOUT_S, lib.VLM_COMPLETION_TIMEOUT_S,
            lib.VLM_PREFLIGHT_TIMEOUT_S, lib.VLM_POSTFLIGHT_TIMEOUT_S, lib.VLM_TOOL_KILL_WAIT_S,
            lib.VLM_MAX_BODY) == (60, 10, 120, 6900, 90, 5, 1048576)
    assert lib.VLM_RESTORE_LOG_TEXT == "~/.local/share/qwen-agent/story-server-restore.log"
    assert isinstance(lib.VLM_RECOVERY, list) and isinstance(lib.RESTORERS, list)
    assert os.environ["MOVIE_UI_VLM_LIFECYCLE"] == "0"
    assert os.environ["MOVIE_UI_VLM_TOOLS"] == str(tmp_path / "no-vlm-tools")
    assert not os.path.exists(os.environ["MOVIE_UI_VLM_TOOLS"])
    assert os.environ["MOVIE_UI_VLM_PORT"] == "9"
    assert lib.vlm_lifecycle_enabled() is False


def test_vlm_environment_helpers(monkeypatch):
    for name in ("MOVIE_UI_VLM_LIFECYCLE", "MOVIE_UI_VLM_TOOLS", "MOVIE_UI_VLM_PORT"):
        monkeypatch.delenv(name)
    assert lib.vlm_lifecycle_enabled() is True
    assert lib.vlm_tools_dir() == os.path.join(mt.WS, "bin")
    assert lib.vlm_tools_dir("/ui") == "/ui/bin"
    assert lib.vlm_port() == 8177
    monkeypatch.setenv("MOVIE_UI_VLM_LIFECYCLE", "yes")
    assert lib.vlm_lifecycle_enabled() is True
    monkeypatch.setenv("MOVIE_UI_VLM_LIFECYCLE", "0")
    assert lib.vlm_lifecycle_enabled() is False
    monkeypatch.setenv("MOVIE_UI_VLM_TOOLS", "")
    assert lib.vlm_tools_dir("/ui") == "/ui/bin"
    monkeypatch.setenv("MOVIE_UI_VLM_TOOLS", "/t")
    assert lib.vlm_tools_dir("/ui") == "/t" and lib.vlm_tools_dir() == "/t"
    monkeypatch.setenv("MOVIE_UI_VLM_PORT", "1234")
    assert lib.vlm_port() == 1234


# --- VL1-VL5: the policy (VP1-VP4) -------------------------------------------------------------

def test_vl1_job_vlm(tmp_path):
    ws = str(tmp_path)
    for kind in ("story", "character-create", "character-regenerate"):
        assert lib.job_vlm(kind, {}, ws, None) == "required", kind
    for kind in ("smoke", "character-train", "action-train"):
        assert lib.job_vlm(kind, {}, ws, None) == "forbidden", kind
    for kind in ("action-create", "download", "something-new"):
        assert lib.job_vlm(kind, {}, ws, None) == "any", kind
    assert lib.job_vlm("movie", {"action": "movie"}, ws, "s1") == "required"
    assert lib.job_vlm("movie", {"action": "movie"}, ws, None) == "required"
    assert lib.job_vlm("movie", None, ws, "") == "required"
    assert lib.job_vlm("movie", {"action": "redo"}, ws, "s1") == "forbidden"
    _write_story(ws, "s1")
    assert lib.job_vlm("movie", {"action": "movie"}, ws, "s1") == "forbidden"
    assert lib.job_vlm("movie", {"action": "redo"}, ws, "s1") == "forbidden"
    assert lib.job_vlm("movie", {"action": "movie"}, ws, "s2") == "required"


def test_vl2_jobs_carry_their_vlm_policy(http_env, monkeypatch, tmp_path):
    s, ws, state = http_env["srv"], http_env["ws"], http_env["state"]
    mt.smoke_host(monkeypatch, tmp_path)
    _write_story(ws, "written")

    def created(method_path, body):
        status, _h, payload = mt.api(s, "POST", method_path, body=body)
        assert status == 201, (method_path, payload)
        return lib.read_job(lib.job_dir(state, payload["job"]["id"]))

    compose = (("story", mt.fields(ws), "required"),
               ("regenerate", mt.fields(ws, action="regenerate"), "required"),
               ("movie without story.md", mt.fields(ws, action="movie", story_id="fresh",
                                                    mode="no_stills"), "required"),
               ("movie with story.md", mt.fields(ws, action="movie", story_id="written",
                                                 mode="no_stills"), "forbidden"),
               ("smoke", mt.fields(ws, action="smoke"), "forbidden"))
    for name, body, policy in compose:
        assert created("/api/jobs", body)["vlm"] == policy, name
    character = {"ws": ws, "name": "kyra", "phrase": "the young woman", "class_noun": "woman",
                 "descriptor": "a tall young woman", "trigger": None, "seed": None,
                 "seed_upload": None, "force": False}
    routes = (("/api/characters", character, "character-create", "required"),
              ("/api/characters/kyra/regenerate", {"ws": ws}, "character-regenerate", "required"),
              ("/api/characters/kyra/train", {"ws": ws, "video": True}, "character-train",
               "forbidden"),
              ("/api/actions/roundhouse-kick/train", {"ws": ws}, "action-train", "forbidden"),
              ("/api/models/download", {"ws": ws, "repo": "org/name"}, "download", "any"))
    for path, body, kind, policy in routes:
        job = created(path, body)
        assert (job["kind"], job["vlm"]) == (kind, policy), path
        assert list(job)[-2:] == ["vlm", "created"]
    # The two kinds no HTTP test can submit on this host (redo needs the stills stack, an action
    # create needs real clips) go through the same create_job.
    for kind, fields, story_id, policy in (("movie", {"action": "redo"}, "written", "forbidden"),
                                           ("action-create", {"name": "kick"}, None, "any")):
        job = lib.create_job(state, lib.new_job_id(state), kind, ws, story_id, None, ["x"], fields)
        assert job["vlm"] == policy, kind


def test_vl3_effective_vlm(tmp_path):
    ws = str(tmp_path)
    movie = {"kind": "movie", "workspace": ws, "story_id": "s1", "fields": {"action": "movie"},
             "vlm": "required"}
    assert lib.effective_vlm(movie) == "required"
    _write_story(ws, "s1")
    assert lib.effective_vlm(movie) == "forbidden"
    assert lib.effective_vlm(dict(movie, vlm="bogus")) == "forbidden"
    assert lib.effective_vlm({"kind": "story"}) == "any"
    assert lib.effective_vlm({"kind": "story", "vlm": "bogus"}) == "any"
    assert lib.effective_vlm({"kind": "story", "vlm": "required"}) == "required"
    assert lib.effective_vlm({"kind": "smoke", "vlm": "forbidden"}) == "forbidden"


def test_vl4_next_queued_job(state, tmp_path):
    ws = str(tmp_path)
    assert lib.next_queued_job(state) == (None, None)
    done = mt.make_job(state, ["x"], ws, kind="smoke")
    lib.write_status(lib.job_dir(state, done), {"state": "cancelled", "exit_code": None,
                                                "ended": lib.utc_now()})
    gone = mt.make_job(state, ["x"], ws, kind="smoke")
    os.unlink(os.path.join(lib.job_dir(state, gone), "job.json"))
    nxt = mt.make_job(state, ["x"], ws, kind="download")
    job_id, job = lib.next_queued_job(state)
    assert job_id == nxt and job["kind"] == "download"
    assert lib.read_queue(state) == [done, gone, nxt]
    lib.write_queue(state, [done, gone])
    assert lib.next_queued_job(state) == (None, None)


def test_vl5_vlm_restore_wanted(state, tmp_path):
    ws = str(tmp_path)
    assert lib.vlm_restore_wanted(state) == (True, "queue empty")
    for kind, wanted, text in (("story", True, "next job %s needs it"),
                               ("smoke", False, "next job %s runs without it"),
                               ("download", False, "next job %s is vlm=any")):
        lib.write_queue(state, [])
        job_id = mt.make_job(state, ["x"], ws, kind=kind)
        assert lib.vlm_restore_wanted(state) == (wanted, text % job_id), kind
