"""Tests for the model-download feature (MU63b): the /api/models/download endpoint
queues a background `bin/model-download` job into the right cache hub, and the lib
helpers that build its argv and keep it out of the render phase model.
Run from the workspace root: python3 -m pytest tests/test_model_download.py -v"""

import os

import pytest

import movie_ui_testutil as mt
import movie_ui_lib as lib


@pytest.fixture
def env(monkeypatch, tmp_path):
    state = mt.set_home(monkeypatch, tmp_path)
    ws = mt.make_stub_workspace(tmp_path)
    running = mt.Running(state)
    yield {"state": state, "ws": ws, "srv": running}
    running.close()
    mt.kill_everything(state)


def test_build_download_argv_is_pure():
    argv = lib.build_download_argv("dgrauet/ltx-2.3-mlx-q8", "ltx", "/WS", py="PY")
    assert argv == ["PY", "/WS/bin/model-download", "--hub", "ltx", "dgrauet/ltx-2.3-mlx-q8"]


def test_download_job_has_no_render_phases():
    assert lib.job_phases("download", {}) == []
    assert lib.job_phases("download", {"seed_upload": "x.png"}) == []


def test_download_hubs_are_the_three_caches():
    assert lib.DOWNLOAD_HUBS == ("ltx", "zimage", "hf")


def test_endpoint_queues_a_download_job(env):
    s = env["srv"]
    status, _h, created = mt.api(s, "POST", "/api/models/download",
                                 body={"ws": env["ws"], "repo": "dgrauet/ltx-2.3-mlx-q8", "hub": "ltx"})
    assert status == 201, created
    job = lib.read_job(lib.job_dir(env["state"], created["job"]["id"]))
    assert job["kind"] == "download"
    assert job["argv"][-3:] == ["--hub", "ltx", "dgrauet/ltx-2.3-mlx-q8"]
    assert os.path.basename(job["argv"][1]) == "model-download"


def test_endpoint_defaults_hub_to_ltx(env):
    s = env["srv"]
    status, _h, created = mt.api(s, "POST", "/api/models/download",
                                 body={"ws": env["ws"], "repo": "org/name"})
    assert status == 201
    job = lib.read_job(lib.job_dir(env["state"], created["job"]["id"]))
    assert job["argv"][-3:] == ["--hub", "ltx", "org/name"]


def test_endpoint_respects_zimage_hub(env):
    s = env["srv"]
    status, _h, created = mt.api(s, "POST", "/api/models/download",
                                 body={"ws": env["ws"], "repo": "Tongyi-MAI/Z-Image-Turbo", "hub": "zimage"})
    assert status == 201
    job = lib.read_job(lib.job_dir(env["state"], created["job"]["id"]))
    assert job["argv"][-3:] == ["--hub", "zimage", "Tongyi-MAI/Z-Image-Turbo"]


@pytest.mark.parametrize("repo", ["", "noslash", "/leadingslash", "-dash/x", "a//b", "a b/c"])
def test_endpoint_rejects_bad_repo(env, repo):
    s = env["srv"]
    status, _h, payload = mt.api(s, "POST", "/api/models/download",
                                 body={"ws": env["ws"], "repo": repo, "hub": "ltx"})
    assert status == 400, payload


def test_endpoint_rejects_unknown_hub(env):
    s = env["srv"]
    status, _h, payload = mt.api(s, "POST", "/api/models/download",
                                 body={"ws": env["ws"], "repo": "org/name", "hub": "nope"})
    assert status == 400, payload


def test_stale_incomplete_with_final_blob_is_not_flagged(tmp_path):
    """A finished blob whose `.incomplete` sidecar was never cleaned up (HF/Xet leftover)
    must not read as an incomplete download (MU63b hardening)."""
    repo_dir = mt.make_hf_cache(tmp_path, "org/stale", {"model.safetensors": b"\x01" * 8})
    blobs = os.path.join(repo_dir, "blobs")
    digest = "a" * 64
    with open(os.path.join(blobs, digest), "wb") as f:
        f.write(b"\x01" * 8)                                  # the completed blob
    with open(os.path.join(blobs, "%s.deadbeef.incomplete" % digest), "wb") as f:
        f.write(b"x")                                         # stale sidecar beside it
    ok, detail = lib.model_check("org/stale", os.path.join(str(tmp_path), "hub"))
    assert ok, detail


def test_genuine_partial_without_final_blob_is_flagged(tmp_path):
    """An `.incomplete` with no finished blob is a real interrupted download."""
    repo_dir = mt.make_hf_cache(tmp_path, "org/partial2", {"model.safetensors": b"\x01" * 8})
    with open(os.path.join(repo_dir, "blobs", "%s.deadbeef.incomplete" % ("b" * 64)), "wb") as f:
        f.write(b"x")
    ok, detail = lib.model_check("org/partial2", os.path.join(str(tmp_path), "hub"))
    assert not ok and "download incomplete: 1 partial blob(s)" in detail
