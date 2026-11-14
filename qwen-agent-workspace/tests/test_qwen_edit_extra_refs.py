"""Tests for the registry and the runner of the extra reference images (docs/superpowers/specs/2026-11-13-extra-
reference-images-design.md, XR8-XR10: XR-T1-XR-T5): every QWEN_MODELS entry has max_references and reference_gib;
the memory floor grows by reference_gib for every image above two; the child timeout grows with the references; and
run_jobs refuses a job whose "sources" lists more than its model's max_references before any child.

Run from the workspace root: python3 -m pytest -q -p no:cacheprovider tests/test_qwen_edit_extra_refs.py

The children are tests/test_seed_edit_tool.py's stubs (through test_qwen_edit's env fixture). No test loads a model,
renders, downloads or contacts a server or touches port 8177 or 8178. Stdlib, PIL and pytest.
"""

import os

import pytest

import movie_ui_testutil as mt  # first: it puts the workspace on sys.path
import movie_ui_seedgen as seedgen  # noqa: E402
import qwen_edit as qe  # noqa: E402
import test_seed_edit_tool as st
from test_qwen_edit import _bf16_cache, _mflux_ready, env  # noqa: F401

UNC = [{"id": "uncensored", "scale": 1.0}]


def _refs(env, count=11):
    """count distinct 64x48 PNGs under tmp."""
    return [st.png(os.path.join(env["tmp"], "refs", "r%02d.png" % k), (64, 48), (k * 20, 90, 30))
            for k in range(count)]


def _job(env, refs, k):
    """Job 1 with sources refs[:k], staged and finished in <tmp>/out."""
    out = os.path.join(env["tmp"], "out")
    os.makedirs(out, exist_ok=True)
    return {"n": 1, "seed": 7, "prompt": "p", "source": refs[0], "sources": refs[:k],
            "stage_path": os.path.join(out, "cand_01.pending.png"), "output_path": os.path.join(out, "cand_01.png")}


# --- XR-T1 (XR8): the registry ---------------------------------------------------------------------------------

def test_xrt1_the_registry():
    assert [(m["id"], m["max_references"], m["reference_gib"]) for m in seedgen.QWEN_MODELS] == [
        ("qwen21-q4", 10, 2.0), ("qwen21-q8", 10, 2.0), ("qwen21-bf16", 10, 2.0), ("qwen2511-q4", 1, 3.0),
        ("qwen2511-bf16", 3, 3.0)]
    for m in seedgen.QWEN_MODELS:
        keys = list(m)
        at = keys.index("memory_gib")
        assert keys[at + 1:at + 3] == ["max_references", "reference_gib"], m["id"]
    views = seedgen.registry_view()["models"]
    assert [v["max_references"] for v in views] == [10, 10, 10, 1, 3]
    for v in views:
        keys = list(v)
        assert keys[keys.index("memory_gib") + 1] == "max_references", v["id"]
    assert [qe.max_references(i) for i in qe.MODEL_IDS] == [10, 10, 10, 1, 3]


# --- XR-T2 (XR9): the memory floor -----------------------------------------------------------------------------

def test_xrt2_the_memory_floor(monkeypatch):
    assert [qe.memory_floor("qwen21-q4", n) for n in (1, 2, 3, 4, 6, 10)] == [20.0, 20.0, 22.0, 24.0, 28.0, 36.0]
    assert qe.memory_floor("qwen21-q4") == 20.0
    assert qe.memory_floor("qwen21-bf16", 10) == 72.0
    assert qe.memory_floor("qwen2511-bf16", 3) == 67.0
    assert qe.entry_floor(seedgen.qwen_model("qwen21-q8"), 4) == 36.0
    monkeypatch.setattr(qe, "total_gib", lambda: 32.0)
    assert qe.memory_problem(seedgen.qwen_model("qwen21-q4")) is None
    assert qe.memory_problem(seedgen.qwen_model("qwen21-q4"), 10) == (
        "needs a host with at least 36 GiB of memory (this host has 32.0 GiB)")
    assert qe.reference_memory_problem("qwen21-q4", 8) is None
    assert qe.reference_memory_problem("qwen21-q4", 10) == (
        "Qwen-Image-2.1 q4 with 10 reference images is unavailable: needs a host with at least 36 GiB of memory "
        "(this host has 32.0 GiB)")
    monkeypatch.setattr(qe, "install_problem", lambda model_id, loras: (None, {}))
    assert qe.selection_problem("qwen21-q4", []) is None


# --- XR-T3 (XR10): the timeout scales with the references ------------------------------------------------------

def test_xrt3_the_timeout_scales_with_the_references():
    assert qe.MULTI_REFERENCE_TIMEOUT_FACTOR == 6
    for n in (1, 6, 7, 24):
        assert qe.jobs_timeout([{"n": 1}] * n) == qe.child_timeout(n), n
    assert [qe.jobs_timeout([{"n": 1, "sources": ["a"] * k}]) for k in (1, 2, 3, 4, 6, 10)] == [
        3600, 3600, 5400, 7200, 10800, 18000]
    assert qe.jobs_timeout([{"n": 1, "sources": ["a", "b"]}] * 3) == 10800
    assert qe.jobs_timeout([{"n": 1, "sources": ["a"] * 10}, {"n": 2}]) == 18600


# --- XR-T4 (XR8): run_jobs refuses more than the cap, mflux ----------------------------------------------------

def test_xrt4_run_jobs_refuses_more_than_the_cap_mflux(env):
    mp = env["mp"]
    py, _snapshot, _lora = _mflux_ready(env)
    r = _refs(env)
    work = os.path.join(env["tmp"], "work")
    with pytest.raises(qe.Unavailable) as info:
        qe.run_jobs("qwen21-q4", UNC, [_job(env, r, 11)], 1024, 576, "x", work)
    assert str(info.value) == "Qwen-Image-2.1 q4 takes at most 10 reference images per edit; job 1 lists 11"
    assert st.stub_calls(py) == []
    seen, real = [], qe.run_child

    def spy(argv, child_env, on_line, timeout_s, log_path=None):
        seen.append(timeout_s)
        return real(argv, child_env, on_line, timeout_s, log_path)

    mp.setattr(qe, "run_child", spy)
    results, failure = qe.run_jobs("qwen21-q4", UNC, [_job(env, r, 10)], 1024, 576, "x", work)
    assert failure is None
    (call,) = st.stub_calls(py)
    assert call["spec"]["jobs"][0]["sources"] == r[:10]
    assert seen == [18000]
    st.install_model(env, "qwen2511-q4")
    with pytest.raises(qe.Unavailable) as info:
        qe.run_jobs("qwen2511-q4", [], [_job(env, r, 2)], 1024, 576, "x", work)
    assert str(info.value) == ("Qwen-Image-Edit-2511 q4 (Lightning) cannot edit with several reference images: "
                               + qe.MULTI_REFERENCE_REFUSED["qwen2511-q4"])


# --- XR-T5 (XR8): run_jobs refuses more than the cap, diffusers ------------------------------------------------

def test_xrt5_run_jobs_refuses_more_than_the_cap_diffusers(env):
    _bf16_cache(env)
    stub = st.qwenedit_stub(env, {})
    r = _refs(env)
    work = os.path.join(env["tmp"], "work")
    with pytest.raises(qe.Unavailable) as info:
        qe.run_jobs("qwen2511-bf16", [], [_job(env, r, 4)], 1024, 576, "x", work)
    assert str(info.value) == ("Qwen-Image-Edit-2511 bf16 (Lightning, diffusers) takes at most 3 reference images "
                               "per edit; job 1 lists 4")
    assert st.stub_calls(stub) == []
    results, failure = qe.run_jobs("qwen2511-bf16", [], [_job(env, r, 3)], 1024, 576, "x", work)
    assert failure is None
    (call,) = st.stub_calls(stub)
    assert call["spec"]["jobs"][0]["images"] == r[:3]
