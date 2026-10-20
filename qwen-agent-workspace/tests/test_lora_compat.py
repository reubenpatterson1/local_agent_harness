"""Unit tests for bin/lora-check's static architecture matcher, using synthetic
safetensors files (header + zeroed data) so no real base model or trained LoRA
is needed. Covers: exact bf16 match (PASS), quantized match via scales+group
(PASS), quantized without derivable input dim (PARTIAL), dimension mismatch
(FAIL), wrong-architecture module absent (FAIL), and alpha != rank (FAIL)."""

import importlib.machinery
import json
import math
import os
import struct

HERE = os.path.dirname(os.path.realpath(__file__))
WS = os.path.dirname(HERE)

_DTYPE_BYTES = {"F32": 4, "F16": 2, "BF16": 2, "U32": 4, "I32": 4, "U8": 1}


def _load_checker():
    return importlib.machinery.SourceFileLoader(
        "lora_check", os.path.join(WS, "bin", "lora-check")).load_module()


def write_safetensors(path, tensors, metadata=None):
    """tensors: {name: (dtype, [shape...])}. Writes a valid safetensors file with
    contiguous zeroed data so headers parse and byte offsets are consistent."""
    header, offset = {}, 0
    for name, (dtype, shape) in tensors.items():
        nbytes = _DTYPE_BYTES[dtype] * (math.prod(shape) if shape else 1)
        header[name] = {"dtype": dtype, "shape": shape,
                        "data_offsets": [offset, offset + nbytes]}
        offset += nbytes
    if metadata:
        header["__metadata__"] = {k: str(v) for k, v in metadata.items()}
    blob = json.dumps(header).encode("utf-8")
    with open(path, "wb") as f:
        f.write(struct.pack("<Q", len(blob)))
        f.write(blob)
        f.write(b"\x00" * offset)


def _quant_base(dirpath, group_size=64, with_scales=True, with_config=True):
    os.makedirs(dirpath, exist_ok=True)
    if with_config:
        with open(os.path.join(dirpath, "config.json"), "w") as f:
            json.dump({"quantization": {"bits": 8, "group_size": group_size}}, f)
    tensors = {"transformer.blocks.0.attn.to_q.weight": ("U32", [128, 32])}  # packed
    if with_scales:
        tensors["transformer.blocks.0.attn.to_q.scales"] = ("F16", [128, 128 // group_size])
    write_safetensors(os.path.join(dirpath, "model.safetensors"), tensors)


def _bf16_base(dirpath):
    os.makedirs(dirpath, exist_ok=True)
    write_safetensors(os.path.join(dirpath, "model.safetensors"),
                      {"transformer.blocks.0.attn.to_q.weight": ("BF16", [128, 128])})


def _lora(path, in_f=128, out_f=128, rank=8, alpha=8, module="transformer.blocks.0.attn.to_q"):
    write_safetensors(path, {
        module + ".lora_A.weight": ("F32", [rank, in_f]),
        module + ".lora_B.weight": ("F32", [out_f, rank]),
    }, metadata={"lora_alpha": alpha})


def test_bf16_exact_match_passes(tmp_path):
    chk = _load_checker()
    base = str(tmp_path / "base"); _bf16_base(base)
    lora = str(tmp_path / "ok.safetensors"); _lora(lora)
    status, problems = chk.static_check(lora, base)
    assert status == "PASS", (status, problems)


def test_quantized_match_with_group_passes(tmp_path):
    chk = _load_checker()
    base = str(tmp_path / "qbase"); _quant_base(base, group_size=64)
    lora = str(tmp_path / "ok.safetensors"); _lora(lora, in_f=128, out_f=128)
    status, problems = chk.static_check(lora, base)
    assert status == "PASS", (status, problems)


def test_quantized_without_group_is_partial(tmp_path):
    chk = _load_checker()
    base = str(tmp_path / "qbase"); _quant_base(base, with_config=False)  # no group -> in None
    lora = str(tmp_path / "ok.safetensors"); _lora(lora)
    status, problems = chk.static_check(lora, base)
    assert status == "PARTIAL", (status, problems)


def test_dimension_mismatch_fails(tmp_path):
    chk = _load_checker()
    base = str(tmp_path / "base"); _bf16_base(base)
    lora = str(tmp_path / "bad.safetensors"); _lora(lora, in_f=999)  # wrong input dim
    status, problems = chk.static_check(lora, base)
    assert status == "FAIL", (status, problems)
    assert any("in 999" in p or "dimension" in p for p in problems)


def test_wrong_architecture_module_absent_fails(tmp_path):
    chk = _load_checker()
    base = str(tmp_path / "base"); _bf16_base(base)
    lora = str(tmp_path / "foreign.safetensors")
    _lora(lora, module="some.sdxl.only.block")  # not present in base
    status, problems = chk.static_check(lora, base)
    assert status == "FAIL", (status, problems)
    assert any("absent from the base" in p for p in problems)


def test_alpha_not_equal_rank_fails(tmp_path):
    chk = _load_checker()
    base = str(tmp_path / "base"); _bf16_base(base)
    lora = str(tmp_path / "scaled.safetensors"); _lora(lora, rank=8, alpha=16)
    status, problems = chk.static_check(lora, base)
    assert status == "FAIL", (status, problems)
    assert any("alpha" in p for p in problems)


def test_missing_base_is_unverified(tmp_path):
    chk = _load_checker()
    lora = str(tmp_path / "ok.safetensors"); _lora(lora)
    status, problems = chk.static_check(lora, str(tmp_path / "does-not-exist"))
    assert status == "UNVERIFIED", (status, problems)


if __name__ == "__main__":
    # Minimal runner without pytest: use a temp dir per test.
    import tempfile, traceback
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    passed = 0
    for fn in fns:
        with tempfile.TemporaryDirectory() as d:
            class P:  # tiny tmp_path stand-in
                def __truediv__(self, x): return os.path.join(d, x)
            try:
                fn(P()); passed += 1; print("ok   ", fn.__name__)
            except Exception:
                print("FAIL ", fn.__name__); traceback.print_exc()
    print("\n%d/%d passed" % (passed, len(fns)))
