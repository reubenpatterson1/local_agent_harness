"""Tests for the multi-reference Qwen edit job (docs/superpowers/specs/2026-11-09-shots-multi-reference-stills-
design.md, CR1-CR3: CRT1-CRT6): a qwen_edit.run_jobs job may carry "sources", every reference image in order;
the mflux child passes them as image_paths, the diffusers qwenedit child as its image list; qwen2511-q4 is
refused; a multi-reference job counts MULTI_REFERENCE_TIMEOUT_FACTOR jobs in the child timeout. Single-image jobs
are unchanged.

Run from the workspace root: python3 -m pytest -q -p no:cacheprovider tests/test_qwen_edit_cast_refs.py

The children are tests/test_seed_edit_tool.py's stubs (through test_qwen_edit's env fixture) or run in-process
with sys.modules fakes (test_seed_edit_tool.child_fakes, test_location_dataset._fake_edit_stack). No test loads a
model, renders, downloads or contacts a server. Stdlib, PIL and pytest.
"""

import json
import os
import re

import pytest
from PIL import Image

import movie_ui_testutil as mt  # first: it puts the workspace on sys.path
import character_dataset  # noqa: E402
import qwen_edit as qe  # noqa: E402
import test_seed_edit_tool as st
from test_location_dataset import _fake_edit_stack
from test_qwen_edit import _bf16_cache, _mflux_ready, env  # noqa: F401

UNC = [{"id": "uncensored", "scale": 1.0}]
REFUSED = ("mflux's Qwen-Image-Edit-2511 pipeline reads only the first input image (its edit tokenizer is built "
           "without picture prefixes), so the second character's reference would be silently ignored; use "
           "qwen2511-bf16 or a qwen21 model")


def _refs(env):
    """Two distinct 1024x640 reference PNGs and one 640x1024 source under tmp."""
    return [st.png(os.path.join(env["tmp"], "refs", "a.png"), (1024, 640), (0, 90, 0)),
            st.png(os.path.join(env["tmp"], "refs", "b.png"), (1024, 640), (0, 0, 90)),
            st.png(os.path.join(env["tmp"], "refs", "c.png"), (640, 1024), (90, 0, 0))]


def _jobs(env, refs, multi=(1, 3)):
    """Jobs 1-3 (stage cand_NN.pending.png): the numbers in multi carry sources [a, b], the rest only source c."""
    out = os.path.join(env["tmp"], "out")
    os.makedirs(out, exist_ok=True)
    jobs = []
    for n in (1, 2, 3):
        job = {"n": n, "seed": 7, "prompt": "two people %d" % n, "source": refs[0] if n in multi else refs[2],
               "stage_path": os.path.join(out, "cand_%02d.pending.png" % n),
               "output_path": os.path.join(out, "cand_%02d.png" % n)}
        if n in multi:
            job["sources"] = [refs[0], refs[1]]
        jobs.append(job)
    return jobs


# --- CRT1 (CR1, CR2): the refusal table and the timeout ------------------------------------------------------

def test_crt1_the_refusal_table_and_the_timeout():
    assert qe.MULTI_REFERENCE_REFUSED == {"qwen2511-q4": REFUSED}
    assert qe.MULTI_REFERENCE_MODEL_IDS == ("qwen21-q4", "qwen21-q8", "qwen21-bf16", "qwen2511-bf16")
    assert [qe.multi_reference_problem(m) for m in qe.MODEL_IDS] == [None, None, None, REFUSED, None]
    assert qe.MULTI_REFERENCE_TIMEOUT_FACTOR == 6
    single, multi = {"n": 1}, {"n": 1, "sources": ["a", "b"]}
    for n in (1, 6, 7, 24):
        assert qe.jobs_timeout([single] * n) == qe.child_timeout(n), n
    assert qe.jobs_timeout([{"n": 1, "sources": ["a"]}] * 7) == qe.child_timeout(7)
    assert [qe.jobs_timeout([multi] * n) for n in (1, 2, 3, 6)] == [3600, 7200, 10800, 21600]
    assert qe.jobs_timeout([multi, single, single, single, single]) == 6000


# --- CRT2 (CR3): the mflux spec carries sources only for multi-reference jobs; the timeout follows ---------

def test_crt2_the_mflux_spec_and_timeout(env):
    mp = env["mp"]
    py, _snapshot, _lora = _mflux_ready(env)
    refs = _refs(env)
    seen, real = [], qe.run_child

    def spy(argv, child_env, on_line, timeout_s, log_path=None):
        seen.append(timeout_s)
        return real(argv, child_env, on_line, timeout_s, log_path)

    mp.setattr(qe, "run_child", spy)
    jobs = _jobs(env, refs)
    results, failure = qe.run_jobs("qwen21-q4", UNC, jobs, 1024, 576, "ltx_movie_cast_ref_edit",
                                   os.path.join(env["tmp"], "work"))
    assert failure is None and [r["status"] for r in results] == ["ok"] * 3
    (call,) = st.stub_calls(py)
    assert call["spec"]["jobs"] == [
        {"n": 1, "seed": 7, "prompt": "two people 1", "source": refs[0], "output_path": jobs[0]["stage_path"],
         "sources": [refs[0], refs[1]]},
        {"n": 2, "seed": 7, "prompt": "two people 2", "source": refs[2], "output_path": jobs[1]["stage_path"]},
        {"n": 3, "seed": 7, "prompt": "two people 3", "source": refs[0], "output_path": jobs[2]["stage_path"],
         "sources": [refs[0], refs[1]]}]
    assert seen == [max(3600, 600 * (6 + 1 + 6))]
    with open(os.path.join(env["tmp"], "work", "mflux_spec.json"), encoding="utf-8") as f:
        assert list(json.load(f)["jobs"][1]) == ["n", "seed", "prompt", "source", "output_path"]
    single = _jobs(env, refs, multi=())
    qe.run_jobs("qwen21-q4", UNC, single, 1024, 576, "x", os.path.join(env["tmp"], "work2"))
    assert all("sources" not in j for j in st.stub_calls(py)[1]["spec"]["jobs"])
    assert seen[1] == qe.child_timeout(3)


# --- CRT3 (CR1, CR3): qwen2511-q4 refuses a multi-reference job before any child; single jobs still run ----

def test_crt3_qwen2511_q4_refuses_several_references(env):
    py, _snapshot, _lora = _mflux_ready(env, "qwen2511-q4")
    refs = _refs(env)
    with pytest.raises(qe.Unavailable) as info:
        qe.run_jobs("qwen2511-q4", [], _jobs(env, refs), 1024, 576, "x", os.path.join(env["tmp"], "work"))
    assert str(info.value) == ("Qwen-Image-Edit-2511 q4 (Lightning) cannot edit with several reference images: "
                               + REFUSED)
    assert st.stub_calls(py) == []
    results, failure = qe.run_jobs("qwen2511-q4", [], _jobs(env, refs, multi=()), 1024, 576, "x",
                                   os.path.join(env["tmp"], "work"))
    assert failure is None and [r["status"] for r in results] == ["ok"] * 3


# --- CRT4 (CR3): the diffusers spec gives a multi-reference job its "images" list -------------------------

def test_crt4_the_diffusers_spec_lists_every_reference(env):
    _bf16_cache(env)
    stub = st.qwenedit_stub(env, {})
    refs = _refs(env)
    jobs = _jobs(env, refs)
    results, failure = qe.run_jobs("qwen2511-bf16", [], jobs, 1024, 576, "ltx_movie_cast_ref_edit",
                                   os.path.join(env["tmp"], "work"))
    assert failure is None and [r["status"] for r in results] == ["ok"] * 3
    (call,) = st.stub_calls(stub)
    spec = call["spec"]
    assert (spec["image"], spec["skill"]) == (refs[0], "ltx_movie_cast_ref_edit")
    assert spec["jobs"] == [
        {"prompt": "two people 1", "output_path": jobs[0]["stage_path"], "seed": 7, "width": 1024, "height": 576,
         "images": [refs[0], refs[1]]},
        {"prompt": "two people 2", "output_path": jobs[1]["stage_path"], "seed": 7, "width": 1024, "height": 576,
         "image": refs[2]},
        {"prompt": "two people 3", "output_path": jobs[2]["stage_path"], "seed": 7, "width": 1024, "height": 576,
         "images": [refs[0], refs[1]]}]


# --- CRT5 (CR3): the mflux child edits with every listed source -------------------------------------------

def test_crt5_the_mflux_child_passes_every_source(monkeypatch, tmp_path):
    import seed_edit_mflux_child as child
    monkeypatch.setattr(child, "exit_with_parent", lambda poll_s=2.0: None)
    monkeypatch.setattr(child.importlib.metadata, "version", lambda name: "0.24.0")
    record = st.child_fakes(monkeypatch)
    tmp = str(tmp_path)
    a, b = os.path.join(tmp, "a.png"), os.path.join(tmp, "b.png")
    spec = {"family": "qwen21", "model_path": os.path.join(tmp, "model"), "lora_paths": [], "lora_scales": [],
            "width": 64, "height": 96, "steps": 40, "guidance": 1.0, "scheduler": "linear",
            "jobs": [{"n": 1, "seed": 3, "prompt": "p1", "source": a, "sources": [a, b],
                      "output_path": os.path.join(tmp, "o1.png")},
                     {"n": 2, "seed": 3, "prompt": "p2", "source": b, "output_path": os.path.join(tmp, "o2.png")}]}
    path = os.path.join(tmp, "spec.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(spec, f)
    assert child.main(["--spec", path]) == 0
    assert [kwargs["image_paths"] for _name, kwargs in record["generate"]] == [[a, b], [b]]
    with open(os.path.join(mt.WS, "seed_edit_mflux_child.py"), encoding="utf-8") as f:
        source = f.read()
    assert re.findall(r"^(?:import|from)\s+([A-Za-z_][\w.]*)", source, re.M) == [
        "argparse", "importlib.metadata", "json", "os", "re", "sys", "threading", "time"]


# --- CRT6 (CR3): the qwenedit child gives the pipeline every image of a job, each file opened once --------

def test_crt6_the_qwenedit_child_takes_a_per_job_image_list(tmp_path, monkeypatch):
    a, b, c = str(tmp_path / "a.png"), str(tmp_path / "b.png"), str(tmp_path / "c.png")
    Image.new("RGB", (300, 200), (10, 20, 30)).save(a)
    Image.new("RGB", (200, 300), (40, 50, 60)).save(b)
    Image.new("RGB", (100, 100), (70, 80, 90)).save(c)
    calls = {"pipe": [], "skills": [], "opened": [], "lora": None}
    _fake_edit_stack(monkeypatch, calls)
    jobs = [{"prompt": "two", "output_path": str(tmp_path / "o1.png"), "seed": 5, "width": 64, "height": 40,
             "images": [a, b]},
            {"prompt": "one", "output_path": str(tmp_path / "o2.png"), "seed": 5, "width": 64, "height": 40,
             "image": c},
            {"prompt": "two again", "output_path": str(tmp_path / "o3.png"), "seed": 5, "width": 64, "height": 40,
             "images": [b, a]},
            {"prompt": "spec image", "output_path": str(tmp_path / "o4.png"), "seed": 5, "width": 64, "height": 40}]
    spec = {"image": a, "model": "M", "lora_repo": "R", "lora_file": "F.safetensors", "steps": 8, "true_cfg": 1.0,
            "skill": "ltx_movie_cast_ref_edit", "report_path": str(tmp_path / "report.json"), "jobs": jobs}
    path = str(tmp_path / "spec.json")
    with open(path, "w") as f:
        json.dump(spec, f)
    assert character_dataset.main(["qwenedit", "--spec", path]) == 0
    assert calls["opened"] == [a, b, c]
    assert [[img.size for img in call["image"]] for call in calls["pipe"]] == [
        [(300, 200), (200, 300)], [(100, 100)], [(200, 300), (300, 200)], [(300, 200)]]
    assert calls["skills"] == ["ltx_movie_cast_ref_edit"] * 4
    with open(str(tmp_path / "report.json")) as f:
        assert [j["status"] for j in json.load(f)["jobs"]] == ["ok"] * 4
