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
import json
import os
import struct

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
