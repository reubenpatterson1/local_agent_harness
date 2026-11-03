"""Tests for qwen_edit.py, the shared Qwen edit runner, and seed_edit_mflux_child.py's per-job prompt and
source (docs/superpowers/specs/2026-11-03-qwen-edit-models-design.md, Section 11.2: QET1-QET11, with the
plan's Review Focus pin 1).

Run from the workspace root: python3 -m pytest -q -p no:cacheprovider tests/test_qwen_edit.py

Rules (spec 11.1): every test sets HOME, HF_HOME and Z_IMAGE_HF_HOME under tmp_path and removes
HF_HUB_CACHE and every SEED_EDIT_* variable (the env fixture). The mflux child is tests/test_seed_edit_tool.py's
MFLUX_STUB through SEED_EDIT_MFLUX_PYTHON, the qwenedit child its QWENEDIT_STUB through
SEED_EDIT_QWENEDIT_SCRIPT, and content_safety its sys.modules fake (make_fakes), whose assert_image_safe
blocks an image with a pure-red top-left pixel. qwen_edit.avail_gib, total_gib and missing_modules are
monkeypatched. No test uses the real HOME, loads a model, runs bin/seed-edit-setup, renders, downloads
or contacts a server; none touches port 8177 or 8178. Stdlib, PIL and pytest.
"""

import json
import os
import re
import subprocess
import sys
import time

import pytest

import movie_ui_testutil as mt
import movie_ui_seedgen as seedgen
import qwen_edit as qe
import test_seed_edit_tool as st

WS = mt.WS
UNC = [{"id": "uncensored", "scale": 1.0}]
HEAVY = {"torch", "PIL", "psutil", "diffusers", "transformers", "content_safety", "character_dataset",
         "z_image_skill"}


@pytest.fixture
def env(monkeypatch, tmp_path):
    """Spec 11.1's environment; qwen_edit's host probes faked (40 GiB available, 48 GiB total, every
    module importable) and the content_safety fake installed (test_seed_edit_tool.make_fakes)."""
    tmp = str(tmp_path)
    home = os.path.join(tmp, "home")
    os.makedirs(home)
    monkeypatch.setenv("HOME", home)
    for key in list(os.environ):
        if key.startswith("SEED_EDIT_"):
            monkeypatch.delenv(key)
    monkeypatch.delenv("HF_HUB_CACHE", raising=False)
    monkeypatch.setenv("HF_HOME", os.path.join(tmp, "hf"))
    monkeypatch.setenv("Z_IMAGE_HF_HOME", os.path.join(tmp, "zi"))
    monkeypatch.setattr(qe, "avail_gib", lambda: 40.0)
    monkeypatch.setattr(qe, "total_gib", lambda: 48.0)
    monkeypatch.setattr(qe, "missing_modules", lambda names: [])
    return {"tmp": tmp, "qe": qe, "calls": st.make_fakes(monkeypatch), "mp": monkeypatch,
            "zhub": os.path.join(tmp, "zi", "hub"), "hfhub": os.path.join(tmp, "hf", "hub")}


def _sources(env):
    """Two distinct 1024x640 PNG sources under tmp."""
    return [st.png(os.path.join(env["tmp"], "src", "a.png"), (1024, 640), (0, 90, 0)),
            st.png(os.path.join(env["tmp"], "src", "b.png"), (1024, 640), (0, 0, 90))]


def _jobs(env, sources, stage="loc_%02d.pending.png", prompts=("north view", "south view", "east view")):
    """One job per prompt (n 1, 2, 3; seed 10 + n), the sources used in turn, staged and finished in
    <tmp>/out."""
    out = os.path.join(env["tmp"], "out")
    os.makedirs(out, exist_ok=True)
    return [{"n": n, "seed": 10 + n, "prompt": prompts[n - 1], "source": sources[(n - 1) % len(sources)],
             "stage_path": os.path.join(out, stage % n), "output_path": os.path.join(out, "loc_%02d.png" % n)}
            for n in range(1, len(prompts) + 1)]


def _mflux_ready(env, model_id="qwen21-q4"):
    """The mflux stub venv, model_id's pinned snapshot and the uncensored LoRA; returns (python, snapshot,
    LoRA path)."""
    py, _venv = st.mflux_venv(env)
    snapshot, _lightning = st.install_model(env, model_id)
    return py, snapshot, st.install_lora(env, "uncensored")


def _bf16_cache(env):
    """The diffusers model and the Lightning file in the default hub (as test_seed_edit_tool's bf16_cache)."""
    root = os.path.join(env["tmp"], "hf")
    mt.make_hf_cache(root, qe.EDIT_MODEL, {"transformer/x.safetensors": b"\x01" * 8})
    mt.make_hf_cache(root, qe.EDIT_LORA_REPO, {qe.EDIT_LORA_FILE: b"\x01" * 8})


# --- QET1 (QE10): the CLI selection rule ----------------------------------------------------------------

def test_qet1_cli_selection():
    assert qe.cli_selection(None, None) == ("qwen21-q4", [{"id": "uncensored", "scale": 1.0}])
    assert qe.cli_selection("qwen21-q8", None) == ("qwen21-q8", [])
    assert qe.cli_selection("qwen21-q4", ["viggle-turbo=0.5", "uncensored=1"]) == (
        "qwen21-q4", [{"id": "uncensored", "scale": 1.0}, {"id": "viggle-turbo", "scale": 0.5}])
    assert qe.cli_selection("qwen2511-bf16", []) == ("qwen2511-bf16", [])
    for model_flag, lora_flag in (("--qwen-model", "--lora"), ("--seed-edit-model", "--seed-edit-lora")):
        def refused(model, loras):
            with pytest.raises(qe.SelectionError) as info:
                qe.cli_selection(model, loras, model_flag, lora_flag)
            return str(info.value)

        scale = "%s uncensored scale must be a number above 0 and at most 2" % lora_flag
        assert refused(None, ["uncensored=1"]) == "%s needs %s" % (lora_flag, model_flag)
        assert refused("flux", None) == (
            "%s must be one of qwen21-q4, qwen21-q8, qwen21-bf16, qwen2511-q4, qwen2511-bf16" % model_flag)
        for loras, text in ((["uncensored"], "%s must be ID=SCALE (got uncensored)" % lora_flag),
                            (["Uncensored=1"], "%s must be ID=SCALE (got Uncensored=1)" % lora_flag),
                            (["nope=1"], "%s: unknown LoRA nope; known: uncensored, viggle-turbo" % lora_flag),
                            (["uncensored=1", "uncensored=0.5"], "%s uncensored is given twice" % lora_flag),
                            (["uncensored=0"], scale), (["uncensored=2.5"], scale), (["uncensored=x"], scale),
                            (["uncensored=nan"], scale), (["uncensored=inf"], scale)):
            assert refused("qwen21-q4", loras) == text, (model_flag, loras)
        assert refused("qwen2511-q4", ["uncensored=1"]) == (
            "%s uncensored is for Qwen-Image-2.1, not Qwen-Image-Edit-2511 q4 (Lightning)" % lora_flag)


# --- QET2 (QE9-QE12): texts, lookups and the selection checks --------------------------------------------

def test_qet2_texts_lookups_and_selection_checks(env):
    assert qe.generator_text("qwen21-q4", UNC) == (
        "Qwen-Image-2.1 q4 (mflux-community/qwen-image-2-1-mflux-q4) + LoRAs uncensored@1, 40 steps")
    assert qe.generator_text("qwen21-q8", [{"id": "uncensored", "scale": 0.5},
                                           {"id": "viggle-turbo", "scale": 1.0}]) == (
        "Qwen-Image-2.1 q8 (mflux-community/qwen-image-2-1-mflux-q8) + LoRAs uncensored@0.5, viggle-turbo@1, "
        "6 steps")
    assert qe.generator_text("qwen2511-q4", []) == (
        "Qwen-Image-Edit-2511 q4 (Lightning) (mflux-community/qwen-image-edit-2511-mflux-q4) + LoRAs none, "
        "8 steps")
    assert qe.generator_text("qwen2511-bf16", []) == (
        "Qwen/Qwen-Image-Edit-2511 + Qwen-Image-Edit-2511-Lightning-8steps-V1.0-bf16.safetensors, 8 steps")
    want = {"qwen21-q4": ("Qwen-Image-2.1 q4", 32, 20.0), "qwen21-q8": ("Qwen-Image-2.1 q8", 32, 32.0),
            "qwen21-bf16": ("Qwen-Image-2.1 bf16", 32, 56.0),
            "qwen2511-q4": ("Qwen-Image-Edit-2511 q4 (Lightning)", 16, 32.0),
            "qwen2511-bf16": ("Qwen-Image-Edit-2511 bf16 (Lightning, diffusers)", 16, 64.0)}
    for model_id, (label, multiple, floor) in want.items():
        assert (qe.label(model_id), qe.multiple(model_id), qe.memory_floor(model_id)) == (label, multiple, floor)
    assert qe.MODEL_IDS == seedgen.QWEN_MODEL_IDS and qe.LEGACY_EDIT_MODEL == "qwen2511-bf16"
    assert qe.settings("qwen21-q4", UNC) == seedgen.qwen_settings("qwen21-q4", UNC)
    assert qe.selection_of(qe.settings("qwen21-q8", [{"id": "uncensored", "scale": 0.5}])) == (
        "qwen21-q8", [{"id": "uncensored", "scale": 0.5}])
    where = "%s or %s" % (env["zhub"], env["hfhub"])
    st.mflux_venv(env)
    assert qe.install_problem("qwen21-q8", []) == (
        "Qwen-Image-2.1 q8 is unavailable: mflux-community/qwen-image-2-1-mflux-q8@f5c8cc79a674 is not in %s "
        "(run bin/seed-edit-setup --model qwen21-q8)" % where, {})
    snapshot, _none = st.install_model(env, "qwen21-q4")
    assert qe.install_problem("qwen21-q4", UNC) == (
        "LoRA Uncensored (abenzerps) is unavailable: qwen-image-2.1-uncensored-lora.safetensors is not in %s "
        "(run bin/seed-edit-setup --lora uncensored)" % where, {})
    lora = st.install_lora(env, "uncensored")
    assert qe.install_problem("qwen21-q4", UNC) == (
        None, {"model_path": snapshot, "builtin_lora": None, "lora_paths": [lora]})
    env["mp"].setattr(qe, "total_gib", lambda: 16.0)
    assert qe.selection_problem("qwen21-q4", UNC) == (
        "Qwen-Image-2.1 q4 is unavailable: needs a host with at least 20 GiB of memory (this host has 16.0 GiB)")
    env["mp"].setattr(qe, "total_gib", lambda: 48.0)
    assert qe.selection_problem("qwen21-q4", UNC) is None
    assert qe.selection_problem("qwen21-q8", []).startswith(
        "Qwen-Image-2.1 q8 is unavailable: mflux-community/qwen-image-2-1-mflux-q8@")


# --- QET3 (QE11): the child timeout --------------------------------------------------------------------------

def test_qet3_the_child_timeout():
    assert (qe.CHILD_TIMEOUT_S, qe.JOB_TIMEOUT_S, qe.AVAIL_WAIT_S) == (3600, 600, 600)
    assert [qe.child_timeout(n) for n in (1, 4, 6, 7, 18, 23, 24)] == [
        3600, 3600, 3600, 4200, 10800, 13800, 14400]


# --- QET4 (QE13-QE15): the mflux spec, argv and environment ----------------------------------------------------

def test_qet4_the_mflux_spec_argv_and_env(env):
    mp = env["mp"]
    mp.setenv("HF_TOKEN", "dummy-not-a-token")
    mp.setenv("HUGGING_FACE_HUB_TOKEN", "dummy-not-a-token")
    mp.delenv("HF_HUB_DISABLE_IMPLICIT_TOKEN", raising=False)
    py, snapshot, lora = _mflux_ready(env)
    jobs = _jobs(env, _sources(env))
    work = os.path.join(env["tmp"], "work")
    seen, real = [], qe.run_child

    def spy(argv, child_env, on_line, timeout_s, log_path=None):
        seen.append(dict(child_env))
        return real(argv, child_env, on_line, timeout_s, log_path)

    mp.setattr(qe, "run_child", spy)
    results, failure = qe.run_jobs("qwen21-q4", UNC, jobs, 1024, 640, "location_edit", work)
    assert failure is None and [r["status"] for r in results] == ["ok"] * 3
    (call,) = st.stub_calls(py)
    assert call["argv"] == [py, os.path.join(WS, "seed_edit_mflux_child.py"), "--spec",
                            os.path.join(work, "mflux_spec.json")]
    assert call["spec"] == {
        "family": "qwen21", "model_path": snapshot, "lora_paths": [lora], "lora_scales": [1.0], "width": 1024,
        "height": 640, "steps": 40, "guidance": 1.0, "scheduler": "linear",
        "jobs": [{"n": j["n"], "seed": j["seed"], "prompt": j["prompt"], "source": j["source"],
                  "output_path": j["stage_path"]} for j in jobs]}
    assert [j["source"] for j in call["spec"]["jobs"]] == [jobs[0]["source"], jobs[1]["source"], jobs[0]["source"]]
    assert len(seen) == 1
    child = seen[0]
    assert sorted(k for k in ("HF_TOKEN", "HUGGING_FACE_HUB_TOKEN") if k in child) == []
    assert (child["HF_HUB_DISABLE_IMPLICIT_TOKEN"], child["HF_HUB_OFFLINE"], child["PYTHONUNBUFFERED"]) == (
        "1", "1", "1")
    assert os.environ["HF_TOKEN"] == "dummy-not-a-token"


# --- QET5 (QE13, QE14): every mflux output is screened in this process ------------------------------------------

def test_qet5_every_output_is_screened(env):
    py, _snapshot, _lora = _mflux_ready(env)
    st.stub_config(py, {"red": [2]})
    jobs = _jobs(env, _sources(env))
    seen = []

    def on_result(result):
        seen.append((result["n"], result["status"], os.path.isfile(result["output_path"])))

    results, failure = qe.run_jobs("qwen21-q4", UNC, jobs, 1024, 640, "location_edit",
                                   os.path.join(env["tmp"], "work"), on_result=on_result)
    assert failure is None
    assert [(r["n"], r["status"], r["seconds"]) for r in results] == [
        (1, "ok", 1.0), (2, "blocked", 1.0), (3, "ok", 1.0)]
    assert env["calls"]["safety"] == [{"skill": "location_edit", "prompt": j["prompt"], "size": (1024, 640)}
                                      for j in jobs]
    assert seen == [(1, "ok", True), (2, "blocked", False), (3, "ok", True)]
    assert [os.path.exists(j["output_path"]) for j in jobs] == [True, False, True]
    assert [os.path.exists(j["stage_path"]) for j in jobs] == [False, False, False]


# --- QET6 (QE13): the three failure texts ------------------------------------------------------------------------

def test_qet6_child_failures(env):
    mp = env["mp"]
    py, _snapshot, _lora = _mflux_ready(env)
    work = os.path.join(env["tmp"], "work")
    st.stub_config(py, {"fail_after": 1})
    results, failure = qe.run_jobs("qwen21-q4", UNC, _jobs(env, _sources(env)), 1024, 640, "location_edit", work)
    assert failure == "Qwen-Image-2.1 q4 child exited 1: boom"
    assert [(r["status"], r["seconds"]) for r in results] == [("ok", 1.0), ("failed", None), ("failed", None)]
    mp.setattr(qe, "CHILD_TIMEOUT_S", 1)
    mp.setattr(qe, "JOB_TIMEOUT_S", 0)
    st.stub_config(py, {"sleep": 30})
    started = time.monotonic()
    results, failure = qe.run_jobs("qwen21-q4", UNC, _jobs(env, _sources(env)), 1024, 640, "location_edit", work)
    assert failure == "Qwen-Image-2.1 q4 child timed out after 1 s" and time.monotonic() - started < 20
    assert [r["status"] for r in results] == ["failed"] * 3 and qe.CHILD is None
    mp.setattr(qe, "CHILD_TIMEOUT_S", 3600)
    st.stub_config(py, {"silent": [2]})
    for noun, text in (("job", "job 2"), ("candidate", "candidate 2")):
        results, failure = qe.run_jobs("qwen21-q4", UNC, _jobs(env, _sources(env)), 1024, 640, "location_edit",
                                       work, noun=noun)
        assert failure == "Qwen-Image-2.1 q4 child exited 0 without finishing %s" % text
        assert [r["status"] for r in results] == ["ok", "failed", "ok"]


# --- Review Focus 1 (plan ruling R4): an unfinished job leaves no stage file -------------------------------------

def test_qe_review_focus_1_an_unfinished_job_leaves_no_stage_file(env):
    """QE13: a failed job has no file at stage_path or output_path written by the call. The stub writes job
    2's image to its stage path but never reports it (exit 0), as a child killed between saving and
    printing would; then a child that exits 1 after job 1 leaves jobs 2 and 3 unwritten."""
    py, _snapshot, _lora = _mflux_ready(env)
    st.stub_config(py, {"silent": [2]})
    jobs = _jobs(env, _sources(env))
    results, failure = qe.run_jobs("qwen21-q4", UNC, jobs, 1024, 640, "location_edit",
                                   os.path.join(env["tmp"], "w1"))
    assert failure is not None and [r["status"] for r in results] == ["ok", "failed", "ok"]
    assert sorted(os.listdir(os.path.dirname(jobs[0]["output_path"]))) == ["loc_01.png", "loc_03.png"]
    st.stub_config(py, {"fail_after": 1})
    for job in jobs:
        if os.path.exists(job["output_path"]):
            os.remove(job["output_path"])
    results, failure = qe.run_jobs("qwen21-q4", UNC, jobs, 1024, 640, "location_edit",
                                   os.path.join(env["tmp"], "w2"))
    assert failure == "Qwen-Image-2.1 q4 child exited 1: boom"
    assert sorted(os.listdir(os.path.dirname(jobs[0]["output_path"]))) == ["loc_01.png"]


# --- QET7 (QE4, QE14, QE16): qwen2511-bf16 runs the unchanged qwenedit child ------------------------------------

def test_qet7_the_legacy_child(env):
    _bf16_cache(env)
    stub = st.qwenedit_stub(env, {"blocked": [2]})
    srcs = _sources(env)
    work = os.path.join(env["tmp"], "work")
    jobs = _jobs(env, srcs, stage="cand_%02d.part.png")
    results, failure = qe.run_jobs("qwen2511-bf16", [], jobs, 1024, 640, "location_edit", work)
    assert failure is None
    (call,) = st.stub_calls(stub)
    assert call["argv"] == [sys.executable, stub, "qwenedit", "--spec", os.path.join(work, "qwenedit_spec.json")]
    assert call["env"] == {"PYTHONUNBUFFERED": "1"}
    assert call["spec"] == {
        "image": srcs[0], "model": "Qwen/Qwen-Image-Edit-2511", "lora_repo": "lightx2v/Qwen-Image-Edit-2511-Lightning",
        "lora_file": "Qwen-Image-Edit-2511-Lightning-8steps-V1.0-bf16.safetensors", "steps": 8, "true_cfg": 1.0,
        "skill": "location_edit",
        "jobs": [{"prompt": "north view", "output_path": jobs[0]["stage_path"], "seed": 11, "width": 1024,
                  "height": 640},
                 {"prompt": "south view", "output_path": jobs[1]["stage_path"], "seed": 12, "width": 1024,
                  "height": 640, "image": srcs[1]},
                 {"prompt": "east view", "output_path": jobs[2]["stage_path"], "seed": 13, "width": 1024,
                  "height": 640}],
        "report_path": os.path.join(work, "qwenedit_report.json")}
    assert [(r["status"], r["seconds"]) for r in results] == [("ok", 1.0), ("blocked", 1.0), ("ok", 1.0)]
    assert [os.path.exists(j["output_path"]) for j in jobs] == [True, False, True]
    assert env["calls"]["safety"] == []


# --- QET8 (QE8, QE11): the timer gets child_timeout(jobs), and the log gets every child line ---------------------

def test_qet8_the_timeout_and_the_log(env):
    _mflux_ready(env)
    seen, real = [], qe.run_child

    def spy(argv, child_env, on_line, timeout_s, log_path=None):
        seen.append((timeout_s, log_path))
        return real(argv, child_env, on_line, timeout_s, log_path)

    env["mp"].setattr(qe, "run_child", spy)
    log = os.path.join(env["tmp"], "edit.log")
    with open(log, "w", encoding="utf-8") as f:
        f.write("earlier line\n")
    jobs = _jobs(env, _sources(env))
    assert qe.run_jobs("qwen21-q4", UNC, jobs, 1024, 640, "location_edit", os.path.join(env["tmp"], "w"),
                       log_path=log)[1] is None
    assert qe.run_jobs("qwen21-q4", UNC, jobs[:1], 1024, 640, "location_edit", os.path.join(env["tmp"], "w2"))[1] is None
    assert seen == [(qe.child_timeout(3), log), (qe.child_timeout(1), None)]
    with open(log, encoding="utf-8") as f:
        lines = f.read().splitlines()
    assert lines[0] == "earlier line"
    assert [line for line in lines if line.startswith("seed-edit-child done")] == [
        "seed-edit-child done %d 1.0" % n for n in (1, 2, 3)]


# --- QET9 (QE7): the memory wait --------------------------------------------------------------------------------

def test_qet9_wait_for_memory(env, capsys):
    env["mp"].setattr(qe, "avail_gib", lambda: 10.0)
    env["mp"].setattr(qe, "AVAIL_WAIT_S", 0)
    with pytest.raises(qe.Unavailable) as info:
        qe.wait_for_memory(20, "Qwen-Image-2.1 q4", tag="ltx-movie")
    assert str(info.value) == ("only 10.0 GiB available after waiting 0 s; Qwen-Image-2.1 q4 needs 20 GiB; free "
                               "memory and retry")
    assert capsys.readouterr().out == "ltx-movie: waiting up to 0 s for 20 GiB available (now 10.0 GiB)\n"
    env["mp"].setattr(qe, "avail_gib", lambda: 25.0)
    qe.wait_for_memory(20.0, "Qwen-Image-2.1 q4")
    assert capsys.readouterr().out == ""


# --- QET10 (QE17, QE18): the child reads each job's prompt and source, and the old spec shape --------------------

def test_qet10_the_child_takes_per_job_prompt_and_source(monkeypatch, tmp_path, capsys):
    import seed_edit_mflux_child as child
    monkeypatch.setattr(child, "exit_with_parent", lambda poll_s=2.0: None)
    monkeypatch.setattr(child.importlib.metadata, "version", lambda name: "0.24.0")
    record = st.child_fakes(monkeypatch)
    tmp = str(tmp_path)
    a, b = os.path.join(tmp, "a.png"), os.path.join(tmp, "b.png")
    spec = {"family": "qwen21", "model_path": os.path.join(tmp, "model"), "lora_paths": [], "lora_scales": [],
            "width": 64, "height": 96, "steps": 40, "guidance": 1.0, "scheduler": "linear",
            "jobs": [{"n": 1, "seed": 11, "prompt": "north view", "source": a, "output_path": os.path.join(tmp, "1.png")},
                     {"n": 2, "seed": 12, "prompt": "south view", "source": b,
                      "output_path": os.path.join(tmp, "2.png")}]}
    path = os.path.join(tmp, "new-shape.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(spec, f)
    assert child.main(["--spec", path]) == 0
    common = {"num_inference_steps": 40, "guidance": 1.0, "width": 64, "height": 96, "scheduler": "linear"}
    assert [kwargs for _name, kwargs in record["generate"]] == [
        dict(common, seed=11, prompt="north view", image_paths=[a]),
        dict(common, seed=12, prompt="south view", image_paths=[b])]
    record["init"], record["generate"] = [], []
    path, old = st.child_spec(tmp_path, "qwen21", [], [], "linear")
    assert "prompt" not in old["jobs"][0] and "source" not in old["jobs"][0]
    assert child.main(["--spec", path]) == 0
    assert [kwargs for _name, kwargs in record["generate"]] == [
        dict(common, seed=11, prompt=st.PROMPT, image_paths=[old["source"]])]
    with open(os.path.join(WS, "seed_edit_mflux_child.py"), encoding="utf-8") as f:
        source = f.read()
    assert 'prompt = job["prompt"] if "prompt" in job else spec["prompt"]' in source
    assert 'source = job["source"] if "source" in job else spec["source"]' in source
    capsys.readouterr()


# --- QET11 (QE1, QE70): the imports and the new files ---------------------------------------------------------

def test_qet11_imports_and_the_new_files(tmp_path):
    with open(os.path.join(WS, "qwen_edit.py"), encoding="utf-8") as f:
        source = f.read()
    assert re.findall(r"^(?:import|from)\s+([A-Za-z_][\w.]*)", source, re.M) == [
        "glob", "importlib.util", "json", "os", "re", "signal", "subprocess", "sys", "threading", "time",
        "movie_ui_lib", "movie_ui_seedgen"]
    proc = subprocess.run([sys.executable, "-B", "-X", "importtime", "-c", "import qwen_edit"], cwd=WS,
                          capture_output=True, text=True, timeout=60, env=dict(os.environ, HOME=str(tmp_path)))
    assert proc.returncode == 0, proc.stderr
    imported = set(line.rsplit("|", 1)[1].strip().split(".")[0] for line in proc.stderr.splitlines()
                   if line.startswith("import time:") and line.count("|") == 2)
    assert "movie_ui_seedgen" in imported
    assert not imported & HEAVY, sorted(imported & HEAVY)
    with open(os.path.join(WS, "tests", "test_movie_ui_builder.py"), encoding="utf-8") as f:
        builder = f.read()
    start = builder.index("NEW_PY = (")
    new_py = re.findall(r'"([^"]+)"', builder[start:builder.index(")", start)])
    assert new_py[new_py.index("tests/test_movie_ui_seedgen.py") + 1:] == [
        "qwen_edit.py", "tests/test_qwen_edit.py", "tests/test_ltx_movie_seed_edit.py"]
