"""Tests for the custom (user-added) Qwen edit LoRAs (docs/superpowers/specs/2026-11-17-custom-edit-loras-
design.md, Section 5.1: CL-T1-CL-T24, with the plan's Review Focus pins 1-4): the registry file and its
accessors in movie_ui_seedgen, seed_lora_registry, bin/seed-edit-lora, and the run path through qwen_edit,
bin/seed-edit and bin/seed-edit-setup.

Run from the workspace root: python3 -m pytest -q -p no:cacheprovider tests/test_seed_lora_registry.py

Rules (spec 5.1):
- Every test's registry file is tmp_path/r/user_loras.json (SEED_EDIT_USER_LORAS, the autouse registry_path
  fixture). write_registry writes it as the registry module does (an atomic replace). Safetensors files are
  synthetic: the 8-byte little-endian header length, the JSON header and 16 zero bytes.
- No test calls the Hugging Face API: every test that reaches seed_lora_registry.add with a repo patches
  seed_lora_registry.fetch_model_info.
- bin/seed-edit, bin/seed-edit-setup and bin/seed-edit-lora run in-process, loaded with
  importlib.machinery.SourceFileLoader, importlib.util.module_from_spec and loader.exec_module. The tool tests
  use tests/test_seed_edit_tool.py's env and setup_env fixtures (HOME, HF_HOME and Z_IMAGE_HF_HOME under
  tmp_path, the host probes faked) and its stub mflux child; nothing loads a model, downloads, renders or
  contacts a server, and no test reads the real HOME.
Stdlib, PIL and pytest.
"""

import hashlib
import http.client
import importlib.machinery
import importlib.util
import json
import os
import re
import shutil
import ssl
import stat
import struct
import subprocess
import sys
import threading

import pytest

import movie_ui_lib as lib
import movie_ui_seedgen as seedgen
import qwen_edit as qe
import seed_lora_registry as registry
import test_seed_edit_tool as st
from test_qwen_edit import _jobs, _mflux_ready, _sources
from test_seed_edit_tool import env, setup_env  # noqa: F401

WS = st.WS
REPO = "WarmBloodAban/Anything_to_Real_Characters_2511"
FILE = "AnythingtoRealCharacters2511_20.safetensors"
SHA = "e8f98cb5f976c9431f2bef47bd1a97caa1ee4ce7"
TRIGGER = "transform the image to realistic photograph"
LOCAL_LICENSE = "not stated (local file)"


@pytest.fixture(autouse=True)
def registry_path(monkeypatch, tmp_path):
    """Spec 5.1: this file's registry file is tmp_path/r/user_loras.json."""
    path = str(tmp_path / "r" / "user_loras.json")
    monkeypatch.setenv("SEED_EDIT_USER_LORAS", path)
    return path


def pairs(layer):
    """A safetensors header with one lora_A.default/lora_B.default pair for layer (the target LoRA's key form)."""
    return {layer + ".lora_A.default.weight": {"dtype": "BF16", "shape": [16, 64], "data_offsets": [0, 8]},
            layer + ".lora_B.default.weight": {"dtype": "BF16", "shape": [64, 16], "data_offsets": [8, 16]}}


def st_bytes(header):
    """The bytes of a synthetic safetensors file with this header."""
    raw = json.dumps(header).encode("utf-8")
    return struct.pack("<Q", len(raw)) + raw + b"\0" * 16


def safetensors(path, header=None):
    """Write a synthetic safetensors file (pairs("transformer_blocks.0.attn.add_k_proj") by default); returns path."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(st_bytes(pairs("transformer_blocks.0.attn.add_k_proj") if header is None else header))
    return path


def hf_entry(lora_id="user-hf", family="qwen2511", trigger=TRIGGER, steps=None, size=354082336, repo=REPO, file=FILE):
    """A valid hf registry entry (spec CL4) pinned at SHA."""
    return {"id": lora_id, "label": repo, "family": family, "source": "hf", "repo": repo, "revision": SHA,
            "file": file, "bytes": size, "default_on": False, "default_scale": 1.0, "license": "apache-2.0",
            "steps": steps, "scheduler": None, "trigger": trigger, "user": True}


def local_entry(path, lora_id="user-local", family="qwen2511", trigger=TRIGGER, steps=None):
    """A valid local registry entry (spec CL4) for the file at path, with its sha256 and size."""
    with open(path, "rb") as f:
        data = f.read()
    return {"id": lora_id, "label": os.path.basename(path), "family": family, "source": "local", "path": path,
            "file": os.path.basename(path), "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data),
            "default_on": False, "default_scale": 1.0, "license": LOCAL_LICENSE, "steps": steps,
            "scheduler": None, "trigger": trigger, "user": True}


def write_registry(path, entries):
    """The registry file at path holding entries (an atomic replace)."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    lib.write_json_atomic(path, {"schema": "seed-edit.user-loras.v1", "loras": entries})


def probe_workspace(tmp_path, printed):
    """A directory whose bin/seed-edit prints json.dumps(printed) (movie_ui_lib.seed_edit_check runs it with
    sys.executable); returns its path."""
    ws = os.path.join(str(tmp_path), "probe-ws")
    os.makedirs(os.path.join(ws, "bin"), exist_ok=True)
    with open(os.path.join(ws, "bin", "seed-edit"), "w", encoding="utf-8") as f:
        f.write("import sys\nsys.stdout.write(%r + '\\n')\n" % json.dumps(printed))
    return ws


# --- CL-T1, CL-T2 (CL1, CL2, CL5, CL6): the constants and the merged list --------------------------------------

def test_cl_t1_no_file_gives_the_built_ins(registry_path, monkeypatch):
    assert not os.path.exists(registry_path)
    assert seedgen.qwen_lora_ids() == ("uncensored", "viggle-turbo") == seedgen.BUILTIN_QWEN_LORA_IDS
    assert [dict(lora) for lora in seedgen.BUILTIN_QWEN_LORAS] == st.LORA_REGISTRY
    assert seedgen.qwen_loras() == seedgen.BUILTIN_QWEN_LORAS and seedgen.user_loras() == ()
    old_names = ("QWEN_" + "LORAS", "QWEN_" + "LORA_IDS")   # spelled in parts so the CLK3 grep stays empty
    assert [hasattr(seedgen, name) for name in old_names] == [False, False]
    assert (seedgen.USER_LORAS_ENV, seedgen.USER_LORAS_SCHEMA) == ("SEED_EDIT_USER_LORAS", "seed-edit.user-loras.v1")
    assert seedgen.user_loras_path() == registry_path
    default = os.path.join(WS, "generated", "seed_loras", "user_loras.json")
    monkeypatch.setenv("SEED_EDIT_USER_LORAS", "")
    assert seedgen.user_loras_path() == default
    monkeypatch.delenv("SEED_EDIT_USER_LORAS")
    assert seedgen.user_loras_path() == default


def test_cl_t2_a_valid_file_appends_its_entries_in_file_order(registry_path, tmp_path):
    local = safetensors(str(tmp_path / "loras" / "real.safetensors"))
    write_registry(registry_path, [hf_entry(), local_entry(local)])
    assert seedgen.qwen_lora_ids() == ("uncensored", "viggle-turbo", "user-hf", "user-local")
    assert seedgen.user_loras() == (hf_entry(), local_entry(local))
    assert seedgen.qwen_lora("user-local") == local_entry(local)
    assert seedgen.default_loras("qwen2511-q4") == [] and seedgen.default_loras("qwen21-q4") == [
        {"id": "uncensored", "scale": 1.0}]
    write_registry(registry_path, [local_entry(local), hf_entry()])
    assert seedgen.qwen_lora_ids() == ("uncensored", "viggle-turbo", "user-local", "user-hf")
    os.remove(registry_path)
    assert seedgen.qwen_lora_ids() == ("uncensored", "viggle-turbo")
    assert seedgen.qwen_lora("user-hf") is None


# --- CL-T3 (CL4, CL5): an unusable file gives the built-ins and one warning per file state ---------------------

def _data(entries):
    return {"schema": "seed-edit.user-loras.v1", "loras": entries}


BAD_FILE_CASES = [
    (b"{not json", "not valid JSON"),
    ({"schema": "seed-edit.user-loras.v2", "loras": []}, "schema must be seed-edit.user-loras.v1"),
    ({"schema": "seed-edit.user-loras.v1"}, "top level must be {schema, loras}"),
    ({"schema": "seed-edit.user-loras.v1", "loras": {}}, "loras must be a list"),
    (_data([dict(hf_entry(), extra=1)]), "entry 1: keys or source are invalid"),
    (_data([dict(hf_entry(), source="local")]), "entry 1: keys or source are invalid"),
    (_data([dict(hf_entry(), id="User-X")]), "entry 1: id is invalid"),
    (_data([dict(hf_entry(), id="uncensored")]), "entry 1: id is invalid"),
    (_data([hf_entry(), hf_entry()]), "entry 2: id user-hf is listed twice"),
    (_data([dict(hf_entry(), revision="main")]), "entry 1: revision is invalid"),
    (_data([dict(hf_entry(), file="x.bin")]), "entry 1: file is invalid"),
    (_data([dict(hf_entry(), bytes=0)]), "entry 1: bytes is invalid"),
    (_data([dict(hf_entry(), default_on=True)]), "entry 1: default_on is invalid"),
    (_data([dict(hf_entry(), trigger="x  y")]), "entry 1: trigger is invalid"),
]


def test_cl_t3_an_unusable_file_gives_the_built_ins_and_one_warning(registry_path, capsys):
    os.makedirs(os.path.dirname(registry_path))
    for data, reason in BAD_FILE_CASES:
        raw = data if isinstance(data, bytes) else json.dumps(data).encode("utf-8")
        lib.write_bytes_atomic(registry_path, raw)
        assert seedgen.qwen_lora_ids() == seedgen.BUILTIN_QWEN_LORA_IDS, reason
        assert seedgen.qwen_lora_ids() == seedgen.BUILTIN_QWEN_LORA_IDS, reason
        assert seedgen.qwen_selection("qwen21-q4", None) == ("qwen21-q4", [{"id": "uncensored", "scale": 1.0}], None)
        assert seedgen.default_loras("qwen21-q4") == [{"id": "uncensored", "scale": 1.0}]
        assert [lora["id"] for lora in seedgen.registry_view()["loras"]] == ["uncensored", "viggle-turbo"]
        assert capsys.readouterr().err == (
            "seed-edit: ignoring %s: %s; only the built-in Qwen edit LoRAs are available\n" % (registry_path, reason)), reason


# --- CL-T4 (CL3, R10): the trigger rule ----------------------------------------------------------------------

def test_cl_t4_the_trigger_rule():
    for text in (TRIGGER, "a, b. c; d: 'e'! f? (g) & h/i-j", "A" * 200, "9 lives", "x"):
        assert seedgen.valid_trigger(text) is True, text
    for text in ("", "a" * 201, " a", "-a", "a ", "a  b", 'say "x"', "a\\b", "a\nb", "caf\u00e9", "<b>", "{x}",
                 "a$b", "a`b", None, 5):
        assert seedgen.valid_trigger(text) is False, text


# --- CL-T11 (CL19): the LoRA pair rule ---------------------------------------------------------------------------

def test_cl_t11_the_pair_rule():
    t = {"dtype": "F16", "shape": [4, 4], "data_offsets": [0, 32]}
    assert registry.lora_pair_count({"a.lora_A.weight": t, "a.lora_B.weight": t}) == 1
    assert registry.lora_pair_count({"a.lora_A.default.weight": t, "a.lora_B.default.weight": t}) == 1
    assert registry.lora_pair_count({"lora_unet_a.lora_down.weight": t, "lora_unet_a.lora_up.weight": t,
                                     "lora_unet_a.alpha": t}) == 1
    assert registry.lora_pair_count({"a.lora.down.weight": t, "a.lora.up.weight": t}) == 1
    assert registry.lora_pair_count(dict(pairs("x.0"), **pairs("x.1"))) == 2
    assert registry.lora_pair_count({"a.lora_A.weight": t}) == 0
    assert registry.lora_pair_count({"a.lora_B.weight": t, "a.lora_up.weight": t}) == 0
    assert registry.lora_pair_count({"a.lokr_w1": t, "a.lokr_w2": t, "a.hada_w1_a": t}) == 0
    assert registry.lora_pair_count({"__metadata__": {"format": "pt"}}) == 0
    assert registry.PAIR_SUBSTITUTIONS == ((".lora_A.", ".lora_B."), (".lora_down.", ".lora_up."),
                                           (".lora.down.", ".lora.up."))


# --- CL-T14 (CL22b, CL25): lora_problem for every source -------------------------------------------------------

def test_cl_t14_lora_problem_for_every_source(env, registry_path):
    hubs = qe.qwen_hubs()
    where = " or ".join(hubs)
    local = safetensors(os.path.join(env["tmp"], "loras", "real.safetensors"))
    entry = local_entry(local)
    assert qe.lora_problem(entry, hubs) == (None, local)
    os.truncate(local, entry["bytes"] - 1)
    assert qe.lora_problem(entry, hubs) == (
        "%s is %d bytes; the registry recorded %d (the file changed since it was added: re-run bin/seed-edit-lora add "
        "after bin/seed-edit-lora remove user-local)" % (local, entry["bytes"] - 1, entry["bytes"]), None)
    os.remove(local)
    assert qe.lora_problem(entry, hubs) == (
        "%s is missing or not a regular file (restore it, or re-run bin/seed-edit-lora add after bin/seed-edit-lora "
        "remove user-local)" % local, None)
    data = st_bytes(pairs("transformer_blocks.0.attn.to_q"))
    pinned = os.path.join(st.pinned_cache(os.path.join(env["tmp"], "zi"), REPO, SHA, {FILE: data}), FILE)
    assert qe.lora_problem(hf_entry(size=len(data)), hubs) == (None, pinned)
    assert qe.lora_problem(hf_entry(size=len(data) + 1), hubs) == (
        "%s is %d bytes; the registry recorded %d (delete it and run bin/seed-edit-setup --lora user-hf again)"
        % (pinned, len(data), len(data) + 1), None)
    bad = st_bytes({"transformer_blocks.0.attn.to_q.weight": {"dtype": "BF16", "shape": [4, 4], "data_offsets": [0, 16]}})
    np_path = os.path.join(st.pinned_cache(os.path.join(env["tmp"], "zi"), "o/no-pairs", SHA, {FILE: bad}), FILE)
    assert qe.lora_problem(hf_entry("user-np", size=len(bad), repo="o/no-pairs"), hubs) == (
        "%s has no LoRA weight pairs in its safetensors header, so mflux would apply nothing (bin/seed-edit-lora "
        "remove user-np)" % np_path, None)
    junk = b"not a safetensors file at all"
    ns_path = os.path.join(st.pinned_cache(os.path.join(env["tmp"], "zi"), "o/not-st", SHA, {FILE: junk}), FILE)
    assert qe.lora_problem(hf_entry("user-ns", size=len(junk), repo="o/not-st"), hubs) == (
        "%s is not a safetensors file (bin/seed-edit-lora remove user-ns)" % ns_path, None)
    assert qe.lora_problem(hf_entry("user-never", repo="o/never"), hubs) == (
        "%s is not in %s (run bin/seed-edit-setup --lora user-never)" % (FILE, where), None)
    unc = seedgen.qwen_lora("uncensored")
    assert qe.lora_problem(unc, hubs) == (
        "qwen-image-2.1-uncensored-lora.safetensors is not in %s (run bin/seed-edit-setup --lora uncensored)" % where,
        None)
    unc_path = st.install_lora(env, "uncensored")
    assert qe.lora_problem(unc, hubs) == (None, unc_path)


# --- CL-T15 (CL11, CL28): the trigger prefix and run_jobs ------------------------------------------------------

def test_cl_t15_trigger_prompt_and_run_jobs(env, registry_path):
    write_registry(registry_path, [hf_entry("user-a"), hf_entry("user-b", trigger="Photo Style"),
                                   hf_entry("user-c", trigger=TRIGGER.upper()), hf_entry("user-d", trigger=None)])
    tp = seedgen.trigger_prompt
    a, b, c, d = ({"id": "user-%s" % k, "scale": 1.0} for k in "abcd")
    assert tp("make it night", [b, a]) == TRIGGER + " Photo Style make it night"
    assert tp("Photo style, TRANSFORM the image to realistic photograph: make it night", [a, b]) == (
        "Photo style, TRANSFORM the image to realistic photograph: make it night")
    assert tp("photo style at dusk", [a, b]) == TRIGGER + " photo style at dusk"
    assert tp("make it night", [a, c]) == TRIGGER + " make it night"
    assert tp("", [a]) == TRIGGER and tp("   ", [a]) == TRIGGER
    assert tp("make it night", [{"id": "user-gone", "scale": 1.0}]) == "make it night"
    assert tp("make it night", [{"id": "uncensored", "scale": 1.0}]) == "make it night"
    assert tp("make it night", [d]) == "make it night" and tp("make it night", []) == "make it night"
    items = seedgen.qwen_settings("qwen2511-q4", [a])["loras"]
    assert tp("x", items) == TRIGGER + " x"
    once = tp("make it night", [a, b])
    assert tp(once, [a, b]) == once
    py, _snapshot, unc = _mflux_ready(env)
    local = safetensors(os.path.join(env["tmp"], "loras", "real.safetensors"))
    write_registry(registry_path, [local_entry(local, lora_id="user-real", family="qwen21", trigger="photo style")])
    jobs = _jobs(env, _sources(env))
    before = json.loads(json.dumps(jobs))
    loras = [{"id": "user-real", "scale": 0.5}, {"id": "uncensored", "scale": 1.0}]
    results, failure = qe.run_jobs("qwen21-q4", loras, jobs, 1024, 640, "location_edit", os.path.join(env["tmp"], "work"))
    assert failure is None and [r["status"] for r in results] == ["ok"] * 3
    assert jobs == before
    (call,) = st.stub_calls(py)
    want = ["photo style " + j["prompt"] for j in jobs]
    assert [j["prompt"] for j in call["spec"]["jobs"]] == want
    assert (call["spec"]["lora_paths"], call["spec"]["lora_scales"]) == ([unc, local], [1.0, 0.5])
    assert [c["prompt"] for c in env["calls"]["safety"]] == want


# --- CL-T16 (CL31): bin/seed-edit records the triggered prompt, once ---------------------------------------------

def test_cl_t16_seed_edit_records_the_triggered_prompt_once(env, registry_path):
    py, _venv = st.mflux_venv(env)
    st.install_model(env, "qwen21-q4")
    local = safetensors(os.path.join(env["tmp"], "loras", "x.safetensors"))
    entry = local_entry(local, lora_id="user-x", family="qwen21")
    write_registry(registry_path, [entry])
    code, run_dir = st.run_tool(env, "--qwen-model", "qwen21-q4", "--lora", "user-x=1.0", "--candidates", "2",
                                "--seed", "100", model="qwen")
    assert code == 0
    want = TRIGGER + " " + st.PROMPT
    record = st.record_of(run_dir)
    assert record["prompt"] == want and record["state"] == "done"
    assert record["loras"] == [{"id": "user-x", "source": "local", "file": "x.safetensors", "sha256": entry["sha256"],
                                "scale": 1.0, "trigger": TRIGGER}]
    (call,) = st.stub_calls(py)
    assert [job["prompt"] for job in call["spec"]["jobs"]] == [want, want]
    assert all(job["prompt"].count(TRIGGER) == 1 for job in call["spec"]["jobs"])
    assert call["spec"]["lora_paths"] == [local]
    assert [c["prompt"] for c in env["calls"]["safety"]] == [want, want]


# --- CL-T17 (CL10, D4, D5, D13): the settings items --------------------------------------------------------------

def test_cl_t17_settings_items_removed_ids_and_steps(registry_path, tmp_path):
    local = safetensors(str(tmp_path / "loras" / "real.safetensors"))
    write_registry(registry_path, [hf_entry(), local_entry(local), hf_entry("user-q21", family="qwen21", steps=30),
                                   hf_entry("user-s30", steps=30)])
    s = seedgen.qwen_settings("qwen2511-q4", [{"id": "user-local", "scale": 1}, {"id": "user-hf", "scale": 0.5}])
    assert s["loras"] == [
        {"id": "user-hf", "repo": REPO, "revision": SHA, "file": FILE, "scale": 0.5, "trigger": TRIGGER},
        {"id": "user-local", "source": "local", "file": "real.safetensors", "sha256": local_entry(local)["sha256"],
         "scale": 1.0, "trigger": TRIGGER}]
    assert (s["steps"], s["scheduler"]) == (8, None)
    assert "repo" not in s["loras"][1] and "path" not in s["loras"][1]
    assert seedgen.qwen_settings("qwen21-q4", [{"id": "uncensored", "scale": 1}])["loras"] == [
        {"id": "uncensored", "repo": "abenzerps/Qwen-Image-2.1-Uncensored-Quantized",
         "file": "qwen-image-2.1-uncensored-lora.safetensors", "scale": 1.0}]
    gone = seedgen.qwen_settings("qwen2511-q4", [{"id": "user-gone", "scale": 1}])
    assert gone["loras"] == [{"id": "user-gone", "scale": 1.0, "removed": True}]
    q21 = seedgen.qwen_settings("qwen21-q4", [{"id": "user-q21", "scale": 1}])
    assert (q21["steps"], q21["scheduler"]) == (30, "linear")
    s30 = seedgen.qwen_settings("qwen2511-q4", [{"id": "user-s30", "scale": 1}])
    assert (s30["steps"], s30["scheduler"]) == (30, None)
    both = seedgen.qwen_settings("qwen21-q4", [{"id": "user-q21", "scale": 1}, {"id": "viggle-turbo", "scale": 1}])
    assert (both["steps"], both["scheduler"]) == (6, "viggle_turbo")
    assert qe.generator_text("qwen2511-q4", [{"id": "user-gone", "scale": 1}]) == (
        "Qwen-Image-Edit-2511 q4 (Lightning) (mflux-community/qwen-image-edit-2511-mflux-q4) + LoRAs user-gone@1, "
        "8 steps")
    assert qe.selection_of(gone) == ("qwen2511-q4", [{"id": "user-gone", "scale": 1.0}])
    assert seedgen.registry_order([{"id": "user-gone", "scale": 1}, {"id": "user-hf", "scale": 1},
                                   {"id": "uncensored", "scale": 1}]) == [
        {"id": "uncensored", "scale": 1}, {"id": "user-hf", "scale": 1}, {"id": "user-gone", "scale": 1}]
    view = [l for l in seedgen.registry_view()["loras"] if l["id"] in ("uncensored", "user-hf", "user-local")]
    assert [(l["user"], l["source"], l["trigger"], l["setup"]) for l in view] == [
        (False, "builtin", None, "bin/seed-edit-setup --lora uncensored"),
        (True, "hf", TRIGGER, "bin/seed-edit-setup --lora user-hf"), (True, "local", TRIGGER, None)]


# --- CL-T18 (CL13, CL26, CL27): no LoRA on the diffusers model ---------------------------------------------------

def test_cl_t18_no_lora_on_the_diffusers_model(registry_path, monkeypatch):
    write_registry(registry_path, [hf_entry("user-x")])
    no_loras = ("qwen2511-bf16 runs without LoRAs (its diffusers child loads only the built-in Lightning LoRA); "
                "use qwen2511-q4")
    assert seedgen.NO_LORAS_MSG % "qwen2511-bf16" == no_loras
    assert seedgen.qwen_selection("qwen2511-bf16", [{"id": "user-x", "scale": 1}]) == (
        None, None, "LoRA user-x: " + no_loras)
    for flag in ("--lora", "--seed-edit-lora"):
        with pytest.raises(qe.SelectionError) as info:
            qe.check_lora_args(["user-x=1"], seedgen.qwen_model("qwen2511-bf16"), flag)
        assert str(info.value) == "%s user-x: %s" % (flag, no_loras)
    monkeypatch.setattr(qe, "qwen_model_problem", lambda entry: (None, {}))
    assert qe.install_problem("qwen2511-bf16", [{"id": "user-x", "scale": 1.0}]) == (no_loras, {})
    assert qe.install_problem("qwen2511-bf16", []) == (None, {"lora_paths": []})
    assert seedgen.qwen_selection("qwen2511-q4", [{"id": "user-x", "scale": 1}]) == (
        "qwen2511-q4", [{"id": "user-x", "scale": 1.0}], None)
    assert qe.check_lora_args(["user-x=1"], seedgen.qwen_model("qwen2511-q4")) == [{"id": "user-x", "scale": 1.0}]
    assert qe.cli_selection("qwen2511-q4", ["user-x=0.5"], "--seed-edit-model", "--seed-edit-lora") == (
        "qwen2511-q4", [{"id": "user-x", "scale": 0.5}])
    assert seedgen.qwen_selection("qwen2511-bf16", [{"id": "uncensored", "scale": 1}]) == (
        None, None, "LoRA uncensored is for Qwen-Image-2.1, not Qwen-Image-Edit-2511 bf16 (Lightning, diffusers)")


# --- CL-T19 (CL8, CL27, CL46): a removed LoRA --------------------------------------------------------------------

def test_cl_t19_a_removed_lora(env, registry_path, monkeypatch):
    write_registry(registry_path, [hf_entry("user-x", family="qwen21")])
    selection = seedgen.qwen_selection("qwen21-q4", [{"id": "user-x", "scale": 1}, {"id": "uncensored", "scale": 1}])[1]
    assert selection == [{"id": "uncensored", "scale": 1.0}, {"id": "user-x", "scale": 1.0}]
    write_registry(registry_path, [])
    assert seedgen.registry_order(selection[::-1]) == selection
    monkeypatch.setattr(qe, "qwen_model_problem", lambda entry: (None, {"model_path": "/m", "builtin_lora": None}))
    text = ("LoRA user-x is unavailable: it is not in the Qwen edit LoRA registry (removed?); add it again with "
            "bin/seed-edit-lora add, or choose other LoRAs")
    assert qe.install_problem("qwen21-q4", [{"id": "user-x", "scale": 1.0}]) == (text, {})
    with pytest.raises(qe.Unavailable) as info:
        qe.run_jobs("qwen21-q4", [{"id": "user-x", "scale": 1.0}], _jobs(env, _sources(env)), 1024, 640,
                    "location_edit", os.path.join(env["tmp"], "work"))
    assert str(info.value) == text
    with pytest.raises(qe.SelectionError) as info:
        qe.check_lora_args(["user-x=1"], seedgen.qwen_model("qwen21-q4"))
    assert str(info.value) == "--lora: unknown LoRA user-x; known: uncensored, viggle-turbo"
    assert seedgen.qwen_selection("qwen21-q4", [{"id": "user-x", "scale": 1}]) == (None, None, "unknown LoRA user-x")


# --- CL-T20 (CL30, CL34): the probe lists custom IDs; the lib tolerates user- IDs --------------------------------

def test_cl_t20_the_probe_and_its_tolerance(env, registry_path, tmp_path):
    local = safetensors(os.path.join(env["tmp"], "loras", "real.safetensors"))
    write_registry(registry_path, [hf_entry(), local_entry(local)])
    loras = env["tool"].probe()["qwen"]["loras"]
    assert list(loras) == ["uncensored", "viggle-turbo", "user-hf", "user-local"]
    assert loras["user-local"] == {"ok": True, "reason": None}
    assert loras["user-hf"] == {"ok": False, "reason": "%s is not in %s or %s (run bin/seed-edit-setup --lora user-hf)"
                                % (FILE, env["zhub"], env["hfhub"])}
    ok = {"ok": True, "reason": None}
    models = dict((i, ok) for i in seedgen.QWEN_MODEL_IDS)
    builtins = dict((i, ok) for i in seedgen.BUILTIN_QWEN_LORA_IDS)

    def printed(found):
        return {"zimage": {"ok": True, "reason": None, "backend": "zimage"},
                "qwen": {"ok": True, "reason": None, "models": models, "loras": found}}

    ids = seedgen.BUILTIN_QWEN_LORA_IDS + ("user-a", "user-b")
    reported = dict(builtins, **{"user-b": {"ok": False, "reason": "gone"}, "user-zz": ok})
    found, detail = lib.seed_edit_check(probe_workspace(tmp_path, printed(reported)), seedgen.QWEN_MODEL_IDS, ids)
    assert detail is None
    assert found["qwen"]["loras"] == dict(builtins, **{
        "user-a": {"ok": False, "reason": lib.PROBE_NOT_REPORTED}, "user-b": {"ok": False, "reason": "gone"}})
    no_viggle = dict(builtins)
    del no_viggle["viggle-turbo"]
    for loras in (no_viggle, dict(builtins, extra=ok)):
        assert lib.seed_edit_check(probe_workspace(tmp_path, printed(loras)), seedgen.QWEN_MODEL_IDS, ids) == (
            None, "bin/seed-edit --probe printed unparsable output")
    assert lib.USER_LORA_PREFIX == "user-"
    assert lib.PROBE_NOT_REPORTED == (
        "not reported by this workspace's bin/seed-edit --probe (it may predate custom LoRAs)")


# --- CL-T21 (CL32, CL33): bin/seed-edit-setup for custom IDs -----------------------------------------------------

def test_cl_t21_setup_for_custom_ids(setup_env, registry_path, capsys):
    e = setup_env
    setup, rec = e["setup"], e["rec"]
    local = safetensors(os.path.join(e["tmp"], "loras", "local.safetensors"))
    write_registry(registry_path, [hf_entry(), local_entry(local)])
    rec["free"] = 1.0
    where = min(setup.existing_ancestor(e["hub"]), setup.existing_ancestor(os.path.dirname(e["venv"])))
    assert setup.main(["--lora", "user-hf"]) == 2
    assert capsys.readouterr().err == (
        "Error: only 1.0 GiB free on %s; seed-edit-setup needs at least 4.3 GiB more (4.3 GiB in all, 0.0 GiB "
        "already present; user-hf ~0.33 GiB, mflux venv ~3 GiB, 1 GiB headroom)\n" % where)
    rec["free"] = 100.0
    assert setup.main(["--lora", "user-hf"]) == 0
    assert st.downloads(rec) == [[{"kind": "file", "repo": REPO, "revision": SHA, "file": FILE}]]
    out = capsys.readouterr().out.splitlines()
    assert "seed-edit-setup: license: user-hf: apache-2.0" in out
    assert "seed-edit-setup: LoRA user-hf (%s) is not in %s" % (FILE, e["hub"]) in out
    st.mark_ready(e)
    rec["call"] = []
    assert setup.main(["--lora", "user-local"]) == 0
    out = capsys.readouterr().out.splitlines()
    line = "seed-edit-setup: LoRA user-local (local) %s: 0.00 GiB" % local
    assert rec["call"] == [] and "seed-edit-setup: nothing to do" in out and line in out
    assert out.index(line) < [i for i, text in enumerate(out) if text.startswith("seed-edit-setup: free on ")][0]
    os.remove(local)
    assert setup.main(["--lora", "user-local"]) == 0
    assert ("seed-edit-setup: LoRA user-local (local): %s is missing or not a regular file (restore it, or re-run "
            "bin/seed-edit-lora add after bin/seed-edit-lora remove user-local)" % local) in (
        capsys.readouterr().out.splitlines())
    bad = st_bytes({"transformer_blocks.0.attn.to_q.weight": {"dtype": "BF16", "shape": [4, 4], "data_offsets": [0, 16]}})
    pinned = os.path.join(st.pinned_cache(os.path.join(e["tmp"], "zi"), REPO, SHA, {FILE: bad}), FILE)
    write_registry(registry_path, [hf_entry(size=len(bad))])
    unusable = ("seed-edit-setup: LoRA user-hf is unusable: %s has no LoRA weight pairs in its safetensors header, so "
                "mflux would apply nothing (bin/seed-edit-lora remove user-hf)" % pinned)
    error = ("Error: 1 custom LoRA file(s) failed the safetensors check (listed above); remove them with "
             "bin/seed-edit-lora remove ID\n")
    assert setup.main(["--lora", "user-hf"]) == 1
    captured = capsys.readouterr()
    assert "seed-edit-setup: nothing to do" in captured.out.splitlines() and unusable in captured.out.splitlines()
    assert captured.err == error
    rec["ready"] = False
    assert setup.main(["--lora", "user-hf"]) == 1
    captured = capsys.readouterr()
    assert "seed-edit-setup: nothing to do" not in captured.out.splitlines() and unusable in captured.out.splitlines()
    assert captured.err == error
    assert setup.main(["--lora", "user-nope"]) == 2
    assert capsys.readouterr().err == "Error: unknown --lora user-nope; known: uncensored, viggle-turbo, user-hf\n"


# --- CL-T23 (CL5): the reader caches by the file's stat ---------------------------------------------------------

def test_cl_t23_the_reader_caches_by_stat(registry_path, monkeypatch):
    write_registry(registry_path, [hf_entry()])
    opened = []
    real_open = open

    def counting_open(path, *args, **kwargs):
        opened.append(path)
        return real_open(path, *args, **kwargs)

    monkeypatch.setattr(seedgen, "open", counting_open, raising=False)
    assert seedgen.qwen_lora_ids()[-1] == "user-hf"
    assert seedgen.qwen_lora_ids()[-1] == "user-hf"
    assert seedgen.user_loras() == (hf_entry(),)
    assert opened == [registry_path]
    write_registry(registry_path, [hf_entry("user-new")])
    assert seedgen.qwen_lora_ids()[-1] == "user-new"
    assert opened == [registry_path, registry_path]


# --- Review Focus 1: a moved local LoRA refuses before the child -------------------------------------------------

def test_cl_review_focus_1_a_moved_local_lora_refuses_before_the_child(env, registry_path):
    py, _venv = st.mflux_venv(env)
    st.install_model(env, "qwen2511-q4")
    local = safetensors(os.path.join(env["tmp"], "Volumes", "Drive", "real.safetensors"))
    entry = local_entry(local)
    write_registry(registry_path, [entry])
    os.remove(local)
    code, run_dir = st.run_tool(env, "--qwen-model", "qwen2511-q4", "--lora", "user-local=1.0", "--candidates", "1",
                                model="qwen")
    assert code == 2
    record = st.record_of(run_dir)
    assert (record["state"], record["error"]) == (
        "failed", "LoRA real.safetensors is unavailable: %s is missing or not a regular file (restore it, or re-run "
                  "bin/seed-edit-lora add after bin/seed-edit-lora remove user-local)" % local)
    assert [c["status"] for c in record["candidates"]] == ["failed"]
    safetensors(local, pairs("x"))
    size = os.path.getsize(local)
    assert size != entry["bytes"]
    code, run_dir = st.run_tool(env, "--qwen-model", "qwen2511-q4", "--lora", "user-local=1.0", "--candidates", "1",
                                model="qwen", run=st.R2)
    assert code == 2
    assert st.record_of(run_dir)["error"] == (
        "LoRA real.safetensors is unavailable: %s is %d bytes; the registry recorded %d (the file changed since it "
        "was added: re-run bin/seed-edit-lora add after bin/seed-edit-lora remove user-local)"
        % (local, size, entry["bytes"]))
    assert st.stub_calls(py) == []


# --- Task 2: the writer, the Hugging Face answer and the CLI ------------------------------------------------------

INFO = {"id": REPO, "modelId": REPO, "author": "WarmBloodAban", "sha": SHA, "private": False, "disabled": False,
        "gated": False, "library_name": "diffusers", "pipeline_tag": "image-to-image",
        "cardData": {"base_model": "Qwen/Qwen-Image-Edit-2511", "instance_prompt": TRIGGER, "license": "apache-2.0",
                     "library_name": "diffusers", "pipeline_tag": "image-to-image",
                     "new_version": "Qwen/Qwen-Image-Edit-2511",
                     "tags": ["text-to-image", "lora", "diffusers", "template:diffusion-lora", "toReal",
                              "Qwen-image-Edit-2511"]},
        "siblings": [{"rfilename": ".gitattributes", "size": 2307}, {"rfilename": FILE, "size": 354082336},
                     {"rfilename": "README.md", "size": 3892},
                     {"rfilename": "images/2511动漫转写实真人.jpg", "size": 1250845}]}
ENTRY = {"id": "user-anything-to-real-charact", "label": REPO, "family": "qwen2511", "source": "hf", "repo": REPO,
         "revision": SHA, "file": FILE, "bytes": 354082336, "default_on": False, "default_scale": 1.0,
         "license": "apache-2.0", "steps": None, "scheduler": None, "trigger": TRIGGER, "user": True}
N_FAMILY = "family qwen2511 (the model card's base_model is Qwen/Qwen-Image-Edit-2511)"
N_IN_PLACE = "the file is used in place: moving, replacing or resizing it makes this LoRA unavailable"
R5 = "repo must be OWNER/NAME (letters, digits, '.', '_' or '-') or https://huggingface.co/OWNER/NAME (got %s)"
CONN = "HTTPS" + "Connection"   # spelled in two parts: the workspace has one use of the name (CL51, SC3)


def fake_fetch(monkeypatch, info=None):
    """Patch seed_lora_registry.fetch_model_info to answer a copy of info (INFO by default); returns the list of
    the repos it was asked for."""
    asked = []
    answer = INFO if info is None else info

    def fetch(repo):
        asked.append(repo)
        return json.loads(json.dumps(answer))

    monkeypatch.setattr(registry, "fetch_model_info", fetch)
    return asked


def load_cli():
    path = os.path.join(WS, "bin", "seed-edit-lora")
    loader = importlib.machinery.SourceFileLoader("seed_edit_lora_cli", path)
    spec = importlib.util.spec_from_loader("seed_edit_lora_cli", loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def refused(call):
    """(status, text) of the RegistryError that call() raises."""
    with pytest.raises(registry.RegistryError) as info:
        call()
    return info.value.status, str(info.value)


# --- CL-T5 (CL21, CL22, CL24, H5, H9, N-*; CLK1): add the target LoRA ---------------------------------------------

def test_cl_t5_add_the_target_lora(env, registry_path, monkeypatch, capsys):
    asked = fake_fetch(monkeypatch)
    cli = load_cli()
    assert cli.main(["add", "--repo", REPO, "--trigger", TRIGGER]) == 0
    assert capsys.readouterr().out.splitlines() == [
        "seed-edit-lora: " + N_FAMILY,
        "seed-edit-lora: download it with: bin/seed-edit-setup --lora user-anything-to-real-charact",
        "seed-edit-lora: added user-anything-to-real-charact: %s@e8f98cb5f976 %s (0.33 GiB, apache-2.0)" % (REPO, FILE)]
    assert asked == [REPO]
    assert st.read_json(registry_path) == {"schema": "seed-edit.user-loras.v1", "loras": [ENTRY]}
    assert seedgen.qwen_lora_ids()[-1] == ENTRY["id"]
    assert refused(lambda: registry.add({"repo": REPO, "id": ENTRY["id"]}, None)) == (
        409, "LoRA id user-anything-to-real-charact already exists; choose another id or remove it first")
    registry.remove(ENTRY["id"])
    entry, notes = registry.add({"repo": "https://huggingface.co/" + REPO, "id": "user-to-real", "trigger": TRIGGER},
                                os.getcwd())
    assert entry == dict(ENTRY, id="user-to-real") and asked[-1] == REPO
    assert notes == [N_FAMILY, "download it with: bin/seed-edit-setup --lora user-to-real"]
    assert refused(lambda: registry.add({"repo": REPO, "id": "user-other"}, None)) == (
        409, "%s:%s is already in the registry as user-to-real" % (REPO, FILE))
    registry.remove("user-to-real")
    entry, notes = registry.add({"repo": REPO}, None)
    assert entry == dict(ENTRY, trigger=None)
    assert notes == [N_FAMILY, "the model card's instance_prompt is 'transform the image to realistic photograph'; "
                               "pass trigger to prepend it to every edit prompt of this LoRA",
                     "download it with: bin/seed-edit-setup --lora user-anything-to-real-charact"]


# --- CL-T6 (CL17, CL49, CL51; CLK4): the one network function -------------------------------------------------------

class FakeResponse(object):
    def __init__(self, status, body, headers):
        self.status, self.body, self.headers = status, body, headers

    def getheader(self, name, default=None):
        return self.headers.get(name, default)

    def read(self, n=-1):
        return self.body if n < 0 else self.body[:n]


def fake_connection(monkeypatch, status=200, body=b"{}", headers=None, error=None):
    """Patch http.client's HTTPS connection class, as seed_lora_registry sees it, with a fake answering status,
    body and headers, or raising error from request(); returns the list of its recorded calls."""
    calls = []

    class Fake(object):
        def __init__(self, host, timeout=None, context=None):
            calls.append(("init", host, timeout, context is not None))

        def request(self, method, url, headers=None):
            calls.append(("request", method, url, dict(headers or {})))
            if error is not None:
                raise error

        def getresponse(self):
            return FakeResponse(status, body, headers or {})

        def close(self):
            calls.append(("close",))

    monkeypatch.setattr(registry.http.client, CONN, Fake)
    return calls


def test_cl_t6_fetch_model_info(monkeypatch):
    monkeypatch.setenv("HF_TOKEN", "dummy-not-a-token")
    monkeypatch.setenv("HUGGING_FACE_HUB_TOKEN", "dummy-not-a-token")
    calls = fake_connection(monkeypatch, body=json.dumps(INFO).encode("utf-8"))
    assert registry.fetch_model_info("o/n") == INFO
    assert calls == [("init", "huggingface.co", 30, True),
                     ("request", "GET", "/api/models/o/n?blobs=true",
                      {"User-Agent": "qwen-agent-seed-edit-lora/1", "Accept": "application/json"}),
                     ("close",)]
    moved = "repo o/n has moved (%s); add it by its new name"
    gone = ("repo o/n is not on the Hugging Face Hub, or it is private (only public repos can be added; no token is "
            "sent)")
    cases = [(301, b"", {"Location": "/api/models/o/m"}, 400, moved % "/api/models/o/m"), (302, b"", {}, 400, moved % "-"),
             (307, b"", {}, 400, moved % "-"), (308, b"", {"Location": "/x"}, 400, moved % "/x"),
             (401, b"", {}, 400, gone), (404, b"", {}, 400, gone),
             (500, b"", {}, 502, "the Hugging Face API answered HTTP 500 for o/n"),
             (200, b"{bad", {}, 502, "the Hugging Face API answered o/n with invalid JSON"),
             (200, b"\xff\xfe", {}, 502, "the Hugging Face API answered o/n with invalid JSON")]
    for status, body, headers, code, text in cases:
        calls = fake_connection(monkeypatch, status=status, body=body, headers=headers)
        assert refused(lambda: registry.fetch_model_info("o/n")) == (code, text), status
        assert calls[-1] == ("close",)
    monkeypatch.setattr(registry, "HF_MAX_BYTES", 10)
    fake_connection(monkeypatch, body=b"{" + b" " * 9 + b"}")
    assert refused(lambda: registry.fetch_model_info("o/n")) == (
        502, "the Hugging Face API answer for o/n is larger than 32 MiB")
    monkeypatch.setattr(registry, "HF_MAX_BYTES", 32 * 2 ** 20)
    unreachable = "cannot reach the Hugging Face API (huggingface.co): %s"
    for error, text in ((OSError("boom"), "OSError: boom"),
                        (http.client.RemoteDisconnected("closed"), "RemoteDisconnected: closed"),
                        (ssl.SSLCertVerificationError(1, "certificate verify failed"),
                         "SSLCertVerificationError: certificate verify failed; this Python has no CA certificates "
                         "(run its Install Certificates.command)")):
        calls = fake_connection(monkeypatch, error=error)
        assert refused(lambda: registry.fetch_model_info("o/n")) == (502, unreachable % text)
        assert calls[-1] == ("close",)


def test_cl_t6_one_network_function_in_the_workspace():
    root = subprocess.run(["git", "-C", WS, "rev-parse", "--show-toplevel"], capture_output=True, text=True)
    if root.returncode != 0:
        pytest.skip("not a git checkout")
    proc = subprocess.run(["git", "-C", WS, "grep", "--untracked", "-c", CONN, "--", ".", ":(exclude)docs"],
                          capture_output=True, text=True)
    assert proc.stdout.splitlines() == ["seed_lora_registry.py:1"]
    with open(os.path.join(WS, "seed_lora_registry.py"), encoding="utf-8") as f:
        source = f.read()
    for gone in ("Authorization", "HF_TOKEN", "HUGGING_FACE_HUB_TOKEN", "os.environ"):
        assert gone not in source, gone


# --- CL-T7 (R1-R12): the request rules, before any network or file access ------------------------------------------

BASE = {"repo": REPO}
LOCAL = {"path": "/abs/x.safetensors", "family": "qwen2511"}
FIELDS_TEXT = "unknown field %s; allowed: repo, file, path, family, id, label, trigger, scale, steps"
ONE_SOURCE = "give exactly one of repo and path"
R6 = "file must be a relative path of letters, digits, spaces and . _ - + ( ), with no '..' (got %s)"
NOT_ST = ("%s is not a .safetensors file; other formats are refused (the pickle formats .bin, .pt, .pth and .ckpt "
          "can run code when loaded)")
R8 = "id must be user- followed by 1 to 24 lowercase letters, digits or '-' (got %s)"
LABEL_TEXT = "label must be 1 to 80 characters with no control characters"
TRIGGER_TEXT = ("trigger must be 1 to 200 characters: letters, digits, spaces and , . ; : ' ! ? ( ) & / -, starting "
                "with a letter or digit, with no double or trailing space")
SCALE_TEXT = "scale must be a number above 0 and at most 2"
STEPS_TEXT = "steps must be an integer from 1 to 100"
REQUEST_CASES = [
    (dict(BASE, ws="/abs/ws"), FIELDS_TEXT % "ws"),
    (dict(BASE, zz=1, aa=None), FIELDS_TEXT % "aa"),
    ({"repo": 5}, "repo must be a string"),
    (dict(BASE, label=["x"]), "label must be a string"),
    (dict(LOCAL, family=21), "family must be a string"),
    ({}, ONE_SOURCE),
    ({"repo": None, "path": None}, ONE_SOURCE),
    (dict(BASE, path="/abs/x.safetensors"), ONE_SOURCE),
    (dict(LOCAL, file="a.safetensors"), "file is only for repo"),
    ({"repo": "no-slash"}, R5 % "no-slash"),
    ({"repo": "a/b..c"}, R5 % "a/b..c"),
    ({"repo": "a--b/c"}, R5 % "a--b/c"),
    (dict(BASE, file="x.bin"), NOT_ST % "x.bin"),
    (dict(BASE, file="../x.safetensors"), R6 % "../x.safetensors"),
    (dict(BASE, file="a/../b.safetensors"), R6 % "a/../b.safetensors"),
    (dict(BASE, family="flux"), "family must be qwen21 or qwen2511 (got flux)"),
    ({"path": "/abs/x.safetensors"}, "family is required for a local file (qwen21 or qwen2511)"),
    (dict(BASE, id="to-real"), R8 % "to-real"),
    (dict(BASE, id="user-" + "a" * 25), R8 % ("user-" + "a" * 25)),
    (dict(BASE, id="user-A"), R8 % "user-A"),
    (dict(BASE, label=""), LABEL_TEXT),
    (dict(BASE, label="a" * 81), LABEL_TEXT),
    (dict(BASE, label="a\tb"), LABEL_TEXT),
    (dict(BASE, label="a\x7fb"), LABEL_TEXT),
    (dict(BASE, trigger="a  b"), TRIGGER_TEXT),
    (dict(BASE, trigger="-x"), TRIGGER_TEXT),
    (dict(BASE, scale=0), SCALE_TEXT),
    (dict(BASE, scale=2.5), SCALE_TEXT),
    (dict(BASE, scale=True), SCALE_TEXT),
    (dict(BASE, scale="1"), SCALE_TEXT),
    (dict(BASE, steps=0), STEPS_TEXT),
    (dict(BASE, steps=101), STEPS_TEXT),
    (dict(BASE, steps=2.5), STEPS_TEXT),
    (dict(BASE, steps=True), STEPS_TEXT),
]


@pytest.mark.parametrize("body,message", REQUEST_CASES, ids=["case%d" % (i + 1) for i in range(len(REQUEST_CASES))])
def test_cl_t7_the_request_rules(body, message, registry_path, monkeypatch):
    asked = fake_fetch(monkeypatch)
    assert refused(lambda: registry.add(body, None)) == (400, message)
    assert asked == [] and not os.path.exists(os.path.dirname(registry_path))


def test_cl_t7_the_cli_conversions(registry_path, monkeypatch, capsys):
    asked = fake_fetch(monkeypatch)
    cli = load_cli()
    for argv, text in ((["add", "--repo", REPO, "--scale", "x"], SCALE_TEXT),
                       (["add", "--repo", REPO, "--scale", "nan"], SCALE_TEXT),
                       (["add", "--repo", REPO, "--steps", "2.5"], STEPS_TEXT),
                       (["add", "--repo", REPO, "--steps", "0"], STEPS_TEXT),
                       (["add", "--repo", REPO, "--path", "/abs/x.safetensors"], ONE_SOURCE),
                       (["add"], ONE_SOURCE)):
        assert cli.main(argv) == 2, argv
        assert capsys.readouterr().err == "Error: %s\n" % text, argv
    with pytest.raises(SystemExit) as info:
        cli.main(["frob"])
    assert info.value.code == 2
    assert asked == [] and not os.path.exists(registry_path)
    assert (registry.M_SCALE, registry.M_STEPS) == (SCALE_TEXT, STEPS_TEXT)


# --- CL-T8 (H1-H9): the Hugging Face answer rules -------------------------------------------------------------------

def info_with(card=None, **changes):
    """A copy of INFO with changes, and with cardData updated by card (a key set to None is removed)."""
    info = json.loads(json.dumps(INFO))
    info.update(changes)
    for key, value in (card or {}).items():
        if value is None:
            info["cardData"].pop(key, None)
        else:
            info["cardData"][key] = value
    return info


def test_cl_t8_the_hugging_face_answer_rules(env, registry_path, monkeypatch):
    def no(info, body=None):
        fake_fetch(monkeypatch, info)
        return refused(lambda: registry.add(body or {"repo": REPO, "trigger": TRIGGER}, None))

    def yes(info, body=None):
        fake_fetch(monkeypatch, info)
        entry, notes = registry.add(body or {"repo": REPO, "trigger": TRIGGER}, None)
        registry.remove(entry["id"])
        return entry, notes

    where = REPO + "@e8f98cb5f976"
    no_model = (502, "the Hugging Face API returned no model, commit sha or file list for " + REPO)
    assert no("x") == no_model
    assert no(info_with(sha=None)) == no_model and no(info_with(sha=SHA.upper())) == no_model
    assert no(info_with(siblings={"x": 1})) == no_model
    assert no(info_with(disabled=True)) == (400, "repo %s is disabled on the Hugging Face Hub" % REPO)
    assert no(info_with(gated="auto")) == (
        400, "repo %s is gated (auto); seed-edit downloads are unauthenticated, so it cannot be installed" % REPO)
    assert yes(info_with(gated=None))[0]["file"] == FILE
    assert no(INFO, {"repo": REPO, "file": "other.safetensors"}) == (
        400, "file other.safetensors is not in %s; its .safetensors files: %s" % (where, FILE))
    many = [{"rfilename": "l%02d.safetensors" % i, "size": 10} for i in range(12)]
    assert no(info_with(siblings=many), {"repo": REPO, "file": "other.safetensors"}) == (
        400, "file other.safetensors is not in %s; its .safetensors files: %s and 2 more"
        % (where, ", ".join("l%02d.safetensors" % i for i in range(10))))
    folders = [{"rfilename": "README.md", "size": 1}, {"rfilename": "loras/a.safetensors", "size": 10},
               {"rfilename": "model.bin", "size": 10}, {"rfilename": "weights.PT", "size": 10}]
    assert no(info_with(siblings=folders)) == (
        400, "repo %s has no .safetensors file at its top level; its .safetensors files in folders: "
             "loras/a.safetensors; pass file; it has model.bin, weights.PT, which are refused: pickle formats can run "
             "code when loaded" % where)
    assert no(info_with(siblings=[{"rfilename": "README.md", "size": 1}])) == (
        400, "repo %s has no .safetensors file at its top level" % where)
    two = [{"rfilename": "a.safetensors", "size": 10}, {"rfilename": "b.safetensors", "size": 10}]
    assert no(info_with(siblings=two)) == (
        400, "repo %s has 2 .safetensors files at its top level (a.safetensors, b.safetensors); pass file to choose "
             "one" % where)
    entry, _notes = yes(info_with(siblings=two), {"repo": REPO, "file": "b.safetensors", "trigger": TRIGGER})
    assert (entry["file"], entry["bytes"]) == ("b.safetensors", 10)
    assert no(info_with(siblings=[{"rfilename": "bad name!.safetensors", "size": 10}])) == (
        400, "the repo's file bad name!.safetensors has characters this tool does not accept, so it cannot be added")
    assert yes(info_with(siblings=[{"rfilename": "Lora.SafeTensors", "size": 10}]))[0]["file"] == "Lora.SafeTensors"
    no_size = (502, "the Hugging Face API reported no size for " + FILE)
    assert no(info_with(siblings=[{"rfilename": FILE}])) == no_size
    assert no(info_with(siblings=[{"rfilename": FILE, "size": True}])) == no_size
    assert no(info_with(siblings=[{"rfilename": FILE, "size": 0}])) == no_size
    assert no(info_with(siblings=[{"rfilename": FILE, "size": 9 * 2 ** 30}])) == (
        400, "%s is 9.0 GiB; custom LoRAs are limited to 8 GiB" % FILE)
    unknown = ("the model card's base_model (%s) is not Qwen/Qwen-Image-Edit-2511 or Qwen/Qwen-Image-2.1; pass family "
               "(qwen21 or qwen2511)")
    assert no(info_with(card={"base_model": "black-forest-labs/FLUX.1-dev"})) == (
        400, unknown % "black-forest-labs/FLUX.1-dev")
    assert no(info_with(card={"base_model": None})) == (400, unknown % "none")
    assert no(info_with(cardData=None)) == (400, unknown % "none")
    both = ["Qwen/Qwen-Image-Edit-2511", "Qwen/Qwen-Image-2.1"]
    assert no(info_with(card={"base_model": both})) == (400, "the model card's base_model lists both families; pass family")
    download = "download it with: bin/seed-edit-setup --lora user-anything-to-real-charact"
    entry, notes = yes(INFO, {"repo": REPO, "family": "qwen21", "trigger": TRIGGER})
    assert entry["family"] == "qwen21" and notes == [
        "family qwen21 (given)",
        "warning: family qwen21 was given, but the model card's base_model Qwen/Qwen-Image-Edit-2511 means qwen2511",
        download]
    entry, notes = yes(info_with(card={"base_model": both}), {"repo": REPO, "family": "qwen2511", "trigger": TRIGGER})
    assert notes == ["family qwen2511 (given)", download]
    entry, notes = yes(info_with(card={"base_model": ["Qwen/Qwen-Image-Edit-2511", "x/y"]}))
    assert notes == ["family qwen2511 (the model card's base_model is Qwen/Qwen-Image-Edit-2511, x/y)", download]
    entry, notes = yes(INFO, {"repo": REPO, "trigger": TRIGGER, "steps": 30, "scale": 0.7, "label": "To real"})
    assert (entry["steps"], entry["default_scale"], entry["label"]) == (30, 0.7, "To real")
    assert notes == [N_FAMILY, "qwen2511-q4 always loads the Lightning 8-step LoRA; 30 steps with Lightning are "
                               "untested", download]
    for card, licence in (({"license": ["mit", "apache-2.0"]}, "mit, apache-2.0"),
                          ({"license": "other", "license_name": "flux-1-dev-non-commercial-license"},
                           "other (flux-1-dev-non-commercial-license)"),
                          ({"license": None}, "not stated in the model card"),
                          ({"license": 5}, "not stated in the model card"),
                          ({"license": "x" * 300}, "x" * 200)):
        assert yes(info_with(card=card))[0]["license"] == licence, card
    assert st.read_json(registry_path)["loras"] == []


# --- CL-T9 (CL22): the default ids ---------------------------------------------------------------------------------

def test_cl_t9_ids():
    assert registry.slug("Anything_to_Real_Characters_2511") == "anything-to-real-charact"
    assert registry.slug("My LoRA v2.1") == "my-lora-v2-1"
    assert registry.slug("--x--") == "x"
    assert registry.slug("动漫") == "lora" and registry.slug("___") == "lora" and registry.slug("") == "lora"
    assert registry.slug("a" * 23 + "-b") == "a" * 23
    base = "anything-to-real-charact"
    assert registry.default_id(base, ()) == "user-anything-to-real-charact"
    taken = ("user-anything-to-real-charact",)
    assert registry.default_id(base, taken) == "user-anything-to-real-chara-2"
    taken += tuple("user-anything-to-real-chara-%d" % n for n in range(2, 10))
    assert registry.default_id(base, taken) == "user-anything-to-real-char-10"
    assert seedgen.USER_ID_RE.fullmatch("user-anything-to-real-char-10")
    assert registry.default_id("lora", ("user-lora",)) == "user-lora-2"


# --- CL-T10 (CL18, CL19, CL21 local; D7, D10, SC6): local files ------------------------------------------------------

def test_cl_t10_local_files(env, registry_path, monkeypatch):
    tmp = env["tmp"]
    given = safetensors(os.path.join(tmp, "loras", "Real Skin.safetensors"), pairs("block0"))
    entry, notes = registry.add({"path": given, "family": "qwen2511", "trigger": TRIGGER}, None)
    with open(given, "rb") as f:
        data = f.read()
    assert entry == {"id": "user-real-skin", "label": "Real Skin.safetensors", "family": "qwen2511", "source": "local",
                     "path": given, "file": "Real Skin.safetensors", "sha256": hashlib.sha256(data).hexdigest(),
                     "bytes": len(data), "default_on": False, "default_scale": 1.0, "license": LOCAL_LICENSE,
                     "steps": None, "scheduler": None, "trigger": TRIGGER, "user": True}
    assert notes == [N_IN_PLACE]
    copy = os.path.join(tmp, "loras", "copy.safetensors")
    shutil.copyfile(given, copy)
    assert refused(lambda: registry.add({"path": copy, "family": "qwen2511", "id": "user-copy"}, None)) == (
        409, "%s is already in the registry as user-real-skin" % copy)
    home_file = safetensors(os.path.join(tmp, "home", "loras", "h.safetensors"), pairs("block1"))
    entry, notes = registry.add({"path": "~/loras/h.safetensors", "family": "qwen21", "steps": 30}, None)
    assert (entry["path"], entry["id"], notes) == (home_file, "user-h", [N_IN_PLACE])
    rel = safetensors(os.path.join(tmp, "work", "rel", "y.safetensors"), pairs("block2"))
    entry, _notes = registry.add({"path": os.path.join("rel", "y.safetensors"), "family": "qwen21"},
                                 os.path.join(tmp, "work"))
    assert entry["path"] == rel
    assert refused(lambda: registry.add({"path": os.path.join("rel", "y.safetensors"), "family": "qwen21"}, None)) == (
        400, "path must be an absolute path or start with ~ (got %s)" % os.path.join("rel", "y.safetensors"))
    blob = os.path.join(tmp, "hub", "blobs", "abc")
    os.makedirs(os.path.dirname(blob))
    with open(blob, "wb") as f:
        f.write(st_bytes(pairs("block3")))
    link = os.path.join(tmp, "hub", "snapshots", "rev", "x.safetensors")
    os.makedirs(os.path.dirname(link))
    os.symlink(blob, link)
    entry, notes = registry.add({"path": link, "family": "qwen2511", "steps": 30}, None)
    assert (entry["path"], entry["file"], entry["bytes"]) == (link, "x.safetensors", os.path.getsize(blob))
    assert notes == ["qwen2511-q4 always loads the Lightning 8-step LoRA; 30 steps with Lightning are untested",
                     N_IN_PLACE]
    with open(registry_path, "rb") as f:
        before = f.read()
    os.makedirs(os.path.join(tmp, "dir.safetensors"))
    ckpt = os.path.join(tmp, "x.ckpt")
    with open(ckpt, "wb") as f:
        f.write(b"x")
    empty = os.path.join(tmp, "empty.safetensors")
    open(empty, "wb").close()
    garbage = os.path.join(tmp, "garbage.safetensors")
    with open(garbage, "wb") as f:
        f.write(b"not a safetensors file at all")
    unpaired = safetensors(os.path.join(tmp, "unpaired.safetensors"), {"a.lora_A.weight": {"dtype": "F16"}})
    control = os.path.join(tmp, "bad\nname.safetensors")
    for path, text in ((os.path.join(tmp, "nope.safetensors"), "%s does not exist"),
                       (os.path.join(tmp, "dir.safetensors"), "%s is not a regular file"),
                       (ckpt, NOT_ST),
                       (empty, "%s is not a safetensors file (its header does not parse)"),
                       (garbage, "%s is not a safetensors file (its header does not parse)"),
                       (unpaired, "%s has no LoRA weight pairs (lora_A/lora_B, lora_down/lora_up or lora.down/lora.up) "
                                  "in its safetensors header, so mflux would apply nothing")):
        assert refused(lambda: registry.add({"path": path, "family": "qwen21"}, None)) == (400, text % path), path
    assert refused(lambda: registry.add({"path": control, "family": "qwen21"}, None)) == (
        400, "path must not contain control characters")
    with monkeypatch.context() as m:
        m.setattr(os.path, "getsize", lambda p: 9 * 2 ** 30)
        assert refused(lambda: registry.add({"path": unpaired, "family": "qwen21"}, None)) == (
            400, "%s is 9.0 GiB; custom LoRAs are limited to 8 GiB" % unpaired)
    assert refused(lambda: registry.add({"path": unpaired}, None)) == (
        400, "family is required for a local file (qwen21 or qwen2511)")
    with open(registry_path, "rb") as f:
        assert f.read() == before
    assert [e["id"] for e in st.read_json(registry_path)["loras"]] == ["user-real-skin", "user-h", "user-y", "user-x"]


# --- CL-T12 (CL22a, CL24): remove keeps every file --------------------------------------------------------------------

def test_cl_t12_remove_keeps_every_file(env, registry_path, capsys):
    cli = load_cli()
    local = safetensors(os.path.join(env["tmp"], "loras", "real.safetensors"))
    data = st_bytes(pairs("block0"))
    pinned = os.path.join(st.pinned_cache(os.path.join(env["tmp"], "zi"), REPO, SHA, {FILE: data}), FILE)
    write_registry(registry_path, [local_entry(local), hf_entry(size=len(data)),
                                   hf_entry("user-never", repo="o/never", file="never.safetensors")])
    assert cli.main(["remove", "user-nope"]) == 2
    assert capsys.readouterr().err == (
        "Error: unknown custom LoRA user-nope (custom LoRAs: user-local, user-hf, user-never)\n")
    head = "seed-edit-lora: removed %s from " + registry_path + "; "
    assert cli.main(["remove", "user-local"]) == 0
    assert capsys.readouterr().out == head % "user-local" + "the file stays at %s\n" % local
    assert cli.main(["remove", "user-hf"]) == 0
    assert capsys.readouterr().out == head % "user-hf" + "its downloaded file stays at %s\n" % pinned
    assert cli.main(["remove", "user-never"]) == 0
    assert capsys.readouterr().out == head % "user-never" + "it was never downloaded\n"
    assert cli.main(["remove", "uncensored"]) == 2
    assert capsys.readouterr().err == "Error: uncensored is a built-in LoRA and cannot be removed\n"
    assert cli.main(["remove", "user-nope"]) == 2
    assert capsys.readouterr().err == "Error: unknown custom LoRA user-nope (custom LoRAs: none)\n"
    assert os.path.isfile(local) and os.path.isfile(pinned)
    assert st.read_json(registry_path) == {"schema": "seed-edit.user-loras.v1", "loras": []}


# --- CL-T13 (CL24): the list ------------------------------------------------------------------------------------------

def test_cl_t13_the_list(env, registry_path, capsys):
    local = safetensors(os.path.join(env["tmp"], "loras", "real.safetensors"))
    write_registry(registry_path, [hf_entry(), local_entry(local)])
    assert load_cli().main(["list"]) == 0
    where = "%s or %s" % (env["zhub"], env["hfhub"])
    assert capsys.readouterr().out.splitlines() == [
        "ID\tFAMILY\tSOURCE\tWHERE\tSCALE\tTRIGGER\tINSTALLED",
        "uncensored\tqwen21\tbuiltin\tabenzerps/Qwen-Image-2.1-Uncensored-Quantized@7959e658915f "
        "qwen-image-2.1-uncensored-lora.safetensors\t1\t-\tno: qwen-image-2.1-uncensored-lora.safetensors is not in "
        "%s (run bin/seed-edit-setup --lora uncensored)" % where,
        "viggle-turbo\tqwen21\tbuiltin\tViggle/Qwen-Image-2.1-viggle-turbo@009a44a895ef "
        "Qwen-Image-2.1-viggle-turbo-v0.3-6step-lora-r128.safetensors\t1\t-\tno: "
        "Qwen-Image-2.1-viggle-turbo-v0.3-6step-lora-r128.safetensors is not in %s (run bin/seed-edit-setup --lora "
        "viggle-turbo)" % where,
        "user-hf\tqwen2511\thf\t%s@e8f98cb5f976 %s\t1\t%s\tno: %s is not in %s (run bin/seed-edit-setup --lora "
        "user-hf)" % (REPO, FILE, TRIGGER, FILE, where),
        "user-local\tqwen2511\tlocal\t%s\t1\t%s\tyes" % (local, TRIGGER),
        "seed-edit-lora: registry %s (2 custom)" % registry_path]


# --- CL-T22 (CL20): the lock, the file and an unreadable registry ------------------------------------------------------

def test_cl_t22_the_lock_and_the_file(env, registry_path):
    tmp = env["tmp"]
    a = safetensors(os.path.join(tmp, "loras", "a.safetensors"), pairs("block0"))
    b = safetensors(os.path.join(tmp, "loras", "b.safetensors"), pairs("block1"))
    barrier = threading.Barrier(2)
    errors = []

    def run(path, lora_id):
        barrier.wait()
        try:
            registry.add({"path": path, "family": "qwen21", "id": lora_id}, None)
        except Exception as e:
            errors.append(e)

    threads = [threading.Thread(target=run, args=(a, "user-a")), threading.Thread(target=run, args=(b, "user-b"))]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(60)
    assert errors == []
    data = st.read_json(registry_path)
    assert sorted(e["id"] for e in data["loras"]) == ["user-a", "user-b"]
    with open(registry_path, encoding="utf-8") as f:
        raw = f.read()
    assert raw == json.dumps(data, indent=2, ensure_ascii=False) + "\n"
    assert raw.startswith('{\n  "schema": "seed-edit.user-loras.v1",\n  "loras": [\n')
    assert stat.S_IMODE(os.stat(registry_path).st_mode) == 0o600
    assert os.path.isfile(os.path.join(os.path.dirname(registry_path), ".lock"))
    with open(registry_path, "wb") as f:
        f.write(b"{broken")
    text = "the custom LoRA registry %s is unreadable: not valid JSON; fix or delete it, then retry" % registry_path
    assert refused(lambda: registry.add({"path": a, "family": "qwen21", "id": "user-c"}, None)) == (409, text)
    assert refused(lambda: registry.remove("user-a")) == (409, text)
    assert refused(registry.load_entries) == (409, text)
    with open(registry_path, "rb") as f:
        assert f.read() == b"{broken"


# --- CL-T24 (CL48, D16, SC8, SC9): 3.9 and 3.13, the source scan, the imports and the mode ---------------------------

COMPILED = ("seed_lora_registry.py", "bin/seed-edit-lora", "movie_ui_seedgen.py", "qwen_edit.py", "bin/seed-edit",
            "bin/seed-edit-setup", "movie_ui_lib.py", "movie_ui_server.py", "tests/test_seed_lora_registry.py",
            "tests/conftest.py")
SCANNED = ("seed_lora_registry.py", "bin/seed-edit-lora", "tests/test_seed_lora_registry.py")


@pytest.mark.parametrize("python", ["/usr/bin/python3", sys.executable])
def test_cl_t24_every_new_and_changed_file_compiles(python, tmp_path):
    if not os.path.isfile(python):
        pytest.skip("%s is not installed" % python)
    proc = subprocess.run([python, "-m", "py_compile"] + [os.path.join(WS, rel) for rel in COMPILED],
                          capture_output=True, text=True, timeout=120,
                          env=dict(os.environ, PYTHONPYCACHEPREFIX=str(tmp_path)))
    assert proc.returncode == 0, proc.stderr


def test_cl_t24_the_source_scan_the_imports_and_the_mode():
    forbidden = [(re.compile(r"^\s*(import|from)\s+cgi\b", re.M), "cgi"),
                 (re.compile(r"\burllib\b"), "urllib"),
                 (re.compile(r"shell\s*=\s*True"), "shell=True"),
                 (re.compile(r"^\s*match\s+\S.*:\s*$", re.M), "match statement"),
                 (re.compile(r"->[^:\n]*\|"), "X | Y return annotation"),
                 (re.compile(r":\s*[A-Za-z_][\w.\[\], ]*\|\s*None"), "X | None annotation"),
                 (re.compile(r"strict\s*=\s*True\s*\)"), "zip(strict=)"),
                 (re.compile(r"load_module\("), "load_module")]
    for rel in SCANNED:
        with open(os.path.join(WS, rel), encoding="utf-8") as f:
            source = f.read()
        if rel == "tests/test_seed_lora_registry.py":
            start = source.index("    forbidden = [")
            end = source.index("    for rel in SCANNED:", start)
            source = source[:start] + source[end:]
        for regex, what in forbidden:
            assert not regex.search(source), (rel, what)
    imports = r"^(?:import|from)\s+([A-Za-z_][\w.]*)"
    with open(os.path.join(WS, "seed_lora_registry.py"), encoding="utf-8") as f:
        assert re.findall(imports, f.read(), re.M) == ["http.client", "json", "os", "re", "ssl", "lora_catalog",
                                                      "movie_ui_lib", "movie_ui_seedgen"]
    cli = os.path.join(WS, "bin", "seed-edit-lora")
    with open(cli, encoding="utf-8") as f:
        text = f.read()
    assert text.startswith("#!/usr/bin/env python3\n")
    assert re.findall(imports, text, re.M) == ["argparse", "os", "sys", "movie_ui_seedgen", "seed_lora_registry"]
    assert os.access(cli, os.X_OK)
    root = subprocess.run(["git", "-C", WS, "rev-parse", "--show-toplevel"], capture_output=True, text=True)
    if root.returncode != 0:
        pytest.skip("not a git checkout")
    proc = subprocess.run(["git", "-C", WS, "ls-files", "-s", "bin/seed-edit-lora"], capture_output=True, text=True)
    assert proc.stdout.split()[:1] == ["100755"], "bin/seed-edit-lora must be staged with git mode 100755"


# --- Review Focus 2: the CLI resolves relative and ~ paths -------------------------------------------------------------

def test_cl_review_focus_2_the_cli_resolves_relative_and_home_paths(env, registry_path, monkeypatch, capsys):
    tmp = env["tmp"]
    downloads = os.path.join(tmp, "Downloads")
    safetensors(os.path.join(downloads, "lora.safetensors"), pairs("block0"))
    home_file = safetensors(os.path.join(tmp, "home", "loras", "skin.safetensors"), pairs("block1"))
    monkeypatch.chdir(downloads)
    here = os.path.join(os.getcwd(), "lora.safetensors")
    cli = load_cli()
    assert cli.main(["add", "--path", "lora.safetensors", "--family", "qwen2511"]) == 0
    with open(here, "rb") as f:
        sha = hashlib.sha256(f.read()).hexdigest()
    assert capsys.readouterr().out.splitlines() == [
        "seed-edit-lora: " + N_IN_PLACE, "seed-edit-lora: added user-lora: %s (0.00 GiB, sha256 %s)" % (here, sha[:12])]
    assert cli.main(["add", "--path", "./lora.safetensors", "--family", "qwen2511", "--id", "user-again"]) == 2
    assert capsys.readouterr().err == "Error: %s is already in the registry as user-lora\n" % here
    assert cli.main(["add", "--path", "~/loras/skin.safetensors", "--family", "qwen21"]) == 0
    capsys.readouterr()
    assert [(e["id"], e["path"]) for e in st.read_json(registry_path)["loras"]] == [
        ("user-lora", here), ("user-skin", home_file)]


# --- Review Focus 3: Hugging Face URLs pasted the way browsers copy them -----------------------------------------------

def test_cl_review_focus_3_pasted_hugging_face_urls(env, registry_path, monkeypatch):
    asked = fake_fetch(monkeypatch)
    entry, _notes = registry.add({"repo": "https://huggingface.co/%s/" % REPO, "trigger": TRIGGER}, None)
    assert entry["repo"] == REPO and asked == [REPO]
    registry.remove(entry["id"])
    for text in (" https://huggingface.co/" + REPO, "https://huggingface.co/%s/tree/main" % REPO,
                 "https://huggingface.co/%s/blob/main/%s" % (REPO, FILE), "http://huggingface.co/" + REPO,
                 "hf.co/" + REPO, "huggingface.co/" + REPO, "https://huggingface.co/%s?library=diffusers" % REPO,
                 "https://huggingface.co/" + REPO + "\n", REPO + " ", "https://www.huggingface.co/" + REPO):
        assert refused(lambda: registry.add({"repo": text}, None)) == (400, R5 % text), text
    assert asked == [REPO]


# --- Review Focus 4: an unwritable registry is a clean refusal ---------------------------------------------------------

def test_cl_review_focus_4_an_unwritable_registry_is_a_clean_refusal(env, monkeypatch, capsys):
    tmp = env["tmp"]
    blocker = os.path.join(tmp, "blocker")
    with open(blocker, "w", encoding="utf-8") as f:
        f.write("a file, not a directory")
    path = os.path.join(blocker, "user_loras.json")
    monkeypatch.setenv("SEED_EDIT_USER_LORAS", path)
    lora = safetensors(os.path.join(tmp, "loras", "a.safetensors"))
    prefix = "cannot write the custom LoRA registry %s: " % path
    status, text = refused(lambda: registry.add({"path": lora, "family": "qwen21"}, None))
    assert status == 409 and text.startswith(prefix)
    status, text = refused(lambda: registry.remove("user-a"))
    assert status == 409 and text.startswith(prefix)
    assert load_cli().main(["add", "--path", lora, "--family", "qwen21"]) == 2
    err = capsys.readouterr().err
    assert err.startswith("Error: " + prefix) and err.count("\n") == 1
    assert seedgen.qwen_lora_ids() == seedgen.BUILTIN_QWEN_LORA_IDS
    assert capsys.readouterr().err == ""


# --- Fix round 1: a custom LoRA removed mid-operation is a refusal, never a crash ---------------------------------

def test_cl_fix1_availability_error_with_a_removed_lora(registry_path):
    write_registry(registry_path, [hf_entry("user-x")])
    model, loras, error = seedgen.qwen_selection("qwen2511-q4", [{"id": "user-x", "scale": 1}])
    assert error is None
    ok = {"ok": True, "reason": None}
    models = {"qwen": {"models": dict((i, ok) for i in seedgen.QWEN_MODEL_IDS), "loras": {"user-x": ok}}}
    clean = {"model": "qwen", "qwen_model": model, "loras": loras}
    assert seedgen.availability_error(models, None, clean) is None
    os.remove(registry_path)
    assert seedgen.availability_error(models, None, clean) == "LoRA user-x is unavailable: " + seedgen.REMOVED_MSG
    write_registry(registry_path, [hf_entry("user-x")])
    models["qwen"]["loras"] = {}
    assert seedgen.availability_error(models, None, clean) == (
        "LoRA %s is unavailable: %s" % (REPO, lib.PROBE_NOT_REPORTED))


def test_cl_fix1_setup_report_and_unusable_with_a_removed_lora(setup_env, registry_path, capsys):
    e = setup_env
    setup = e["setup"]
    local = safetensors(os.path.join(e["tmp"], "loras", "local.safetensors"))
    write_registry(registry_path, [hf_entry(), local_entry(local)])
    data = st_bytes(pairs("transformer_blocks.0.attn.to_q"))
    pinned = os.path.join(st.pinned_cache(os.path.join(e["tmp"], "zi"), REPO, SHA, {FILE: data}), FILE)
    assert os.path.isfile(pinned)
    item = {"kind": "file", "name": "user-hf", "repo": REPO, "revision": SHA, "file": FILE, "bytes": len(data),
            "license": "apache-2.0", "user": True}
    os.remove(registry_path)
    setup.report(e["venv"], e["hub"], [], ["user-local", "user-hf"], [item])
    assert setup.unusable([item], e["hub"]) == []
    assert setup.finish([item], e["hub"]) == 0
    assert setup.unusable([dict(item, bytes=len(data) + 1)], e["hub"]) == [
        ("user-hf", "%s is %d bytes; the registry recorded %d (delete it and run bin/seed-edit-setup --lora user-hf "
                    "again)" % (pinned, len(data), len(data) + 1))]
