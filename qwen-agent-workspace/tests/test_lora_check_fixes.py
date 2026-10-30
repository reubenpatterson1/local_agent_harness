"""Tests for the location library's two bin/lora-check fixes (docs/superpowers/specs/
2026-10-29-location-lora-design.md, Sections 5.7 and 5.8, test table 6.8: LC1-LC8, KPI LK9, with
the plan's ruling pin LC9): bare 2-D base parameters (scale/shift tables) are base targets, and a
LoRA whose modules lie partly outside the transformer blocks gets a low-RAM warning from
bin/lora-check, bin/lora-catalog add and bin/lora-catalog verify, without changing any PASS/FAIL
status, problem count or exit code.

Run from the workspace root: python3 -m pytest -q -p no:cacheprovider tests/test_lora_check_fixes.py
Stdlib plus pytest. Every LoRA and base model is a synthetic safetensors file (a header and
zeroed data) under tmp_path; no test reads the real HOME, renders, contacts a model server or
touches port 8178 (the autouse story_env fixture: HOME, CHARACTER_LIBRARY_DIR,
LOCATION_LIBRARY_DIR and LORA_CATALOG_DIR under tmp_path; no HF_HOME).
"""

import importlib.machinery
import inspect
import json
import math
import os
import struct
import subprocess
import sys

import pytest

WS = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
sys.path.insert(0, WS)
sys.path.insert(0, os.path.join(WS, "tests"))

import story_engine_testutil as seu  # noqa: E402

CHECK_PATH = os.path.join(WS, "bin", "lora-check")
CATALOG_CLI = os.path.join(WS, "bin", "lora-catalog")
chk = importlib.machinery.SourceFileLoader("lora_check_for_location", CHECK_PATH).load_module()
_BYTES = {"F32": 4, "BF16": 2, "F16": 2, "U32": 4}
TABLES = ("scale_shift_table", "audio_scale_shift_table", "prompt_scale_shift_table",
          "audio_prompt_scale_shift_table", "scale_shift_table_a2v_ca_video",
          "scale_shift_table_a2v_ca_audio")
WARNING = ("44 of 1724 modules are outside the transformer blocks and are skipped in low-RAM "
           "mode; render with --no-low-ram to use them")
ARCH_UNVERIFIED = ("arch: architecture UNVERIFIED: none of the declared base models are on disk "
                   "yet; run bin/lora-check once the base is installed\n")


@pytest.fixture(autouse=True)
def story_env(monkeypatch, tmp_path):
    return seu.set_story_env(monkeypatch, tmp_path)


def write_safetensors(path, tensors, metadata=None):
    """tensors: {name: (dtype, shape)}, in order; zeroed data with consistent offsets (as
    tests/test_lora_compat.py)."""
    header, offset = {}, 0
    for name, (dtype, shape) in tensors.items():
        nbytes = _BYTES[dtype] * math.prod(shape)
        header[name] = {"dtype": dtype, "shape": shape, "data_offsets": [offset, offset + nbytes]}
        offset += nbytes
    if metadata:
        header["__metadata__"] = {k: str(v) for k, v in metadata.items()}
    blob = json.dumps(header).encode("utf-8")
    with open(path, "wb") as f:
        f.write(struct.pack("<Q", len(blob)) + blob + b"\x00" * offset)
    return path


def _modules(blocks=48, linears=29, top_linears=42):
    """[(module, out, in)]: per block the linears and the six tables, then the top-level linears
    and the two top-level tables (the measured 1724-pair ComfyUI LTX-2.3 layout)."""
    out = []
    for b in range(blocks):
        out += [("transformer_blocks.%d.lin%02d" % (b, k), 8, 8) for k in range(linears)]
        out += [("transformer_blocks.%d.%s" % (b, t), 9, 8) for t in TABLES]
    out += [("top%02d" % k, 8, 8) for k in range(top_linears)]
    out += [(t, 2, 8) for t in TABLES[:2]]
    return out


def comfy_lora(path, modules, rank=4):
    tensors = {}
    for module, out_f, in_f in modules:
        tensors["diffusion_model.%s.lora_A.weight" % module] = ("F32", [rank, in_f])
        tensors["diffusion_model.%s.lora_B.weight" % module] = ("F32", [out_f, rank])
    return write_safetensors(path, tensors, metadata={"lora_alpha": rank})


def mlx_base(directory, modules):
    """A bf16 base whose linears are <module>.weight and whose tables are bare 2-D keys."""
    os.makedirs(directory, exist_ok=True)
    tensors = {}
    for module, out_f, in_f in modules:
        name = "transformer.%s" % module
        tensors[name if "table" in module else name + ".weight"] = ("BF16", [out_f, in_f])
    write_safetensors(os.path.join(directory, "model.safetensors"), tensors)
    return directory


def _old_checker(tmp_path, monkeypatch):
    """bin/lora-check as it was at d210c26, from git show (skips outside a git checkout that has
    d210c26); QWEN_AGENT_WORKSPACE points its lora_catalog load at this workspace."""
    old = subprocess.run(["git", "-C", WS, "show", "d210c26:./bin/lora-check"],
                         capture_output=True, text=True)
    if old.returncode != 0:
        pytest.skip("not a git checkout with d210c26")
    path = str(tmp_path / "lora_check_d210c26.py")
    with open(path, "w", encoding="utf-8") as f:
        f.write(old.stdout)
    with monkeypatch.context() as m:
        m.setenv("QWEN_AGENT_WORKSPACE", WS)
        return importlib.machinery.SourceFileLoader("lora_check_d210c26", path).load_module()


# --- LC1, LC2: bare 2-D parameters are base targets (L4.7) -------------------------------------

def test_lc1_scale_shift_tables_match(tmp_path, monkeypatch):
    modules = [("transformer_blocks.0.attn1.to_q", 64, 64),
               ("transformer_blocks.0.scale_shift_table", 9, 4096), ("scale_shift_table", 2, 4096)]
    base = mlx_base(str(tmp_path / "base"), modules)
    lora = comfy_lora(str(tmp_path / "tables.safetensors"), modules, rank=8)
    assert chk.base_linear_map(base) == {"transformer_blocks.0.attn1.to_q": (64, 64, False),
                                         "transformer_blocks.0.scale_shift_table": (9, 4096, False),
                                         "scale_shift_table": (2, 4096, False)}
    assert chk.static_check(lora, base) == ("PASS", [])
    status, problems = _old_checker(tmp_path, monkeypatch).static_check(lora, base)
    assert status == "FAIL" and "2/3 target modules absent from the base" in problems[0]


def test_lc2_quant_keys_are_not_targets_and_weight_entries_win(tmp_path):
    base = str(tmp_path / "qbase")
    os.makedirs(base)
    with open(os.path.join(base, "config.json"), "w") as f:
        json.dump({"quantization": {"bits": 8, "group_size": 64}}, f)
    write_safetensors(os.path.join(base, "model.safetensors"), {
        "transformer.blocks.0.attn.to_q.weight": ("U32", [128, 32]),
        "transformer.blocks.0.attn.to_q.scales": ("F16", [128, 2]),
        "transformer.blocks.0.attn.to_q.biases": ("F16", [128, 2]),
        "transformer.blocks.0.attn.to_q.bias": ("F16", [128, 2]),
        "transformer.blocks.0.attn.to_k.qzeros": ("F16", [128, 2])})
    assert chk.base_linear_map(base) == {"blocks.0.attn.to_q": (128, 128, True)}
    for order in ("bare first", "weight first"):
        other = str(tmp_path / order.replace(" ", "-"))
        os.makedirs(other)
        tensors = [("transformer.x", ("BF16", [9, 9])), ("transformer.x.weight", ("BF16", [4, 8]))]
        write_safetensors(os.path.join(other, "model.safetensors"),
                          dict(tensors if order == "bare first" else tensors[::-1]))
        assert chk.base_linear_map(other) == {"x": (4, 8, False)}, order


# --- LC3, LC4, LC8, LC9: the 1724-pair LoRA and the low-RAM warning (L4.8, LK9) ---------------

def test_lc3_the_1724_pair_lora_is_not_fail(tmp_path, monkeypatch):
    modules = _modules()
    assert len(modules) == 48 * 29 + 288 + 42 + 2 == 1724
    base = mlx_base(str(tmp_path / "base"), modules)
    lora = comfy_lora(str(tmp_path / "comfy.safetensors"), modules)
    status, problems = chk.static_check(lora, base)
    assert status != "FAIL" and not any("absent" in p for p in problems), problems
    header = chk.lc.read_safetensors_header(lora)
    assert chk.low_ram_skipped(header) == (44, 1724)
    assert chk.LOW_RAM_WARNING % (44, 1724) == WARNING
    assert chk.low_ram_warning(header) == WARNING
    status, problems = _old_checker(tmp_path, monkeypatch).static_check(lora, base)
    assert status == "FAIL" and "290/1724 target modules absent" in problems[0]


def test_lc4_lora_check_reports_the_warning(tmp_path, capsys):
    modules = _modules()
    base = mlx_base(str(tmp_path / "base"), modules)
    lora = comfy_lora(str(tmp_path / "comfy.safetensors"), modules)
    assert chk.main(["--json", "--video-base", base, lora]) == 0
    (result,) = json.loads(capsys.readouterr().out)["results"]
    assert (result["target"], result["status"], result["warnings"]) == ("video", "PASS", [WARNING])
    assert chk.main(["--video-base", base, lora]) == 0
    out = capsys.readouterr().out
    assert "[PASS] %s  (video, arg)\n    ! %s\n" % (lora, WARNING) in out
    assert out.endswith("\n1 checked, 0 FAIL, 0 unverified/partial\n")
    stills = write_safetensors(str(tmp_path / "stills.safetensors"), {
        "single_blocks.0.img_attn.lora_A.weight": ("F32", [4, 8]),
        "single_blocks.0.img_attn.lora_B.weight": ("F32", [8, 4])}, metadata={"lora_alpha": 4})
    assert chk.main(["--json", "--stills-base", str(tmp_path / "none"), stills]) == 0
    (result,) = json.loads(capsys.readouterr().out)["results"]
    assert (result["target"], result["warnings"]) == ("stills", [])


def test_lc8_a_character_lora_gives_no_warning(tmp_path, capsys):
    modules = [("transformer_blocks.%d.attn1.to_q" % b, 8, 8) for b in range(3)]
    base = mlx_base(str(tmp_path / "base"), modules)
    lora = str(tmp_path / "character.safetensors")
    tensors = {}
    for module, _out, _in in modules:
        tensors[module + ".lora_A.weight"] = ("F32", [4, 8])
        tensors[module + ".lora_B.weight"] = ("F32", [8, 4])
    write_safetensors(lora, tensors, metadata={"lora_alpha": 4})
    header = chk.lc.read_safetensors_header(lora)
    assert chk.low_ram_skipped(header) == (0, 3) and chk.low_ram_warning(header) is None
    assert chk.main(["--json", "--video-base", base, lora]) == 0
    assert json.loads(capsys.readouterr().out)["results"][0]["warnings"] == []


def test_lc9_a_lora_with_no_module_in_the_blocks_gives_no_warning(tmp_path):
    # Plan ruling: the warning is for a LoRA the low-RAM path skips in part; a LoRA with no module
    # under transformer_blocks. (the synthetic fixtures of the existing catalog tests) gets none.
    lora = seu.lora_file(str(tmp_path), "fake")
    header = chk.lc.read_safetensors_header(lora)
    assert chk.low_ram_skipped(header) == (1, 1) and chk.low_ram_warning(header) is None


def test_lc5_static_check_is_unchanged():
    assert list(inspect.signature(chk.static_check).parameters) == ["lora_path", "base_dir"]
    with open(os.path.join(WS, "bin", "ltx-movie"), encoding="utf-8") as f:
        assert "status, problems = checker.static_check(path, base)" in f.read()


# --- LC6, LC7: bin/lora-catalog add and verify (L4.8) --------------------------------------------

def _catalog(*argv):
    return subprocess.run([sys.executable, CATALOG_CLI] + list(argv), cwd=WS, capture_output=True,
                          text=True, timeout=300)


def test_lc6_lc7_lora_catalog_warns_and_keeps_its_exit_codes(tmp_path, story_env):
    lora = comfy_lora(str(tmp_path / "comfy.safetensors"), _modules())
    add = ["add", lora, "--kind", "motion", "--target", "video", "--base-model", seu.VIDEO_MODEL,
           "--description", "a comfy motion", "--use-when", "a chase"]
    first = _catalog(*(add[:2] + ["--id", "comfy-one"] + add[2:]))
    assert (first.returncode, first.stderr) == (0, ARCH_UNVERIFIED + "warning: %s\n" % WARNING)
    assert first.stdout.startswith("added comfy-one (motion, video, rank 4, sha256 ")
    copy = str(tmp_path / "comfy-copy.safetensors")
    with open(lora, "rb") as src, open(copy, "wb") as dst:
        dst.write(src.read() + b"\x00")
    second = _catalog(*(["add", copy, "--id", "comfy-two"] + add[2:] + ["--no-arch-check"]))
    assert (second.returncode, second.stderr) == (0, "warning: %s\n" % WARNING)
    with open(os.path.join(story_env["catalog"], "catalog.json")) as f:
        assert [e["id"] for e in json.load(f)["entries"]] == ["comfy-one", "comfy-two"]
    plain = seu.lora_file(str(tmp_path / "files"), "plain")
    third = _catalog(*(["add", plain, "--id", "plain-motion"] + add[2:]))
    assert (third.returncode, third.stderr) == (0, ARCH_UNVERIFIED)
    verify = _catalog("verify")
    assert verify.returncode == 0
    assert verify.stdout == ("OK comfy-one\nWARN comfy-one: %s\nOK comfy-two\nWARN comfy-two: %s\n"
                             "OK plain-motion\nverified 3 entries: 0 problem(s)\n" % (WARNING,
                                                                                    WARNING))
    os.remove(copy)
    broken = _catalog("verify")
    assert broken.returncode == 1
    lines = broken.stdout.splitlines()
    assert lines[:2] == ["OK comfy-one", "WARN comfy-one: %s" % WARNING]
    assert lines[2].startswith("FAIL comfy-two: ") and not any(
        line.startswith("WARN comfy-two") for line in lines)
    assert lines[-1].startswith("verified 3 entries: ") and lines[-1].endswith(" problem(s)")
