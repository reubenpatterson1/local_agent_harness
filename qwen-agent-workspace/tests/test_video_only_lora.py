"""Unit tests for bin/ltx-mlx-render's video_only_lora: character video LoRAs are rendered
without their audio-stream modules (audio_attn1/2, audio_ff, video_to_audio_attn), which drift
in training and garble the audio. audio_to_video_attn (writes into the video stream) is kept,
the copy is cached by sha256, and only character LoRAs are rewritten."""

import importlib.machinery
import json
import os
import struct

HERE = os.path.dirname(os.path.realpath(__file__))
WS = os.path.dirname(HERE)

BLOCK = "diffusion_model.transformer_blocks.0."
VIDEO = ["attn1.to_q", "attn2.to_k", "audio_to_video_attn.to_v"]
AUDIO = ["audio_attn1.to_q", "audio_attn2.to_k", "video_to_audio_attn.to_v", "audio_ff.net.0.proj"]


def _load_render():
    return importlib.machinery.SourceFileLoader(
        "ltx_mlx_render", os.path.join(WS, "bin", "ltx-mlx-render")).load_module()


def write_lora(path, modules):
    """A safetensors file with a 4-byte F32 lora_A/lora_B per module; each tensor's bytes are
    distinct so a wrong data_offsets copy is caught."""
    header, data = {"__metadata__": {"lora_alpha": "8"}}, b""
    for i, module in enumerate(modules):
        for j, part in enumerate(("lora_A", "lora_B")):
            name = BLOCK + module + "." + part + ".weight"
            value = struct.pack("<f", float(10 * i + j + 1))
            header[name] = {"dtype": "F32", "shape": [1], "data_offsets": [len(data), len(data) + 4]}
            data += value
    blob = json.dumps(header).encode("utf-8")
    with open(path, "wb") as f:
        f.write(struct.pack("<Q", len(blob)) + blob + data)


def read_tensors(path):
    with open(path, "rb") as f:
        size = struct.unpack("<Q", f.read(8))[0]
        header = json.loads(f.read(size))
        data = f.read()
    meta = header.pop("__metadata__", None)
    return meta, {k: data[v["data_offsets"][0]:v["data_offsets"][1]] for k, v in header.items()}


def test_audio_stream_modules_are_dropped(tmp_path):
    r = _load_render()
    r.VIDEO_ONLY_LORA_DIR = str(tmp_path / "cache")
    src = str(tmp_path / "video.safetensors")
    write_lora(src, VIDEO + AUDIO)
    out = r.video_only_lora(src)
    assert out != src and os.path.dirname(out) == r.VIDEO_ONLY_LORA_DIR
    meta, tensors = read_tensors(out)
    _, original = read_tensors(src)
    assert meta == {"lora_alpha": "8"}
    assert sorted(tensors) == sorted(k for k in original if not any(a in k for a in AUDIO))
    assert all(tensors[k] == original[k] for k in tensors)
    assert r.video_only_lora(src) == out  # cached


def test_video_only_file_is_returned_unchanged(tmp_path):
    r = _load_render()
    r.VIDEO_ONLY_LORA_DIR = str(tmp_path / "cache")
    src = str(tmp_path / "video.safetensors")
    write_lora(src, VIDEO)
    assert r.video_only_lora(src) == src
    assert not os.path.exists(r.VIDEO_ONLY_LORA_DIR)


def test_unreadable_or_foreign_file_is_returned_unchanged(tmp_path):
    r = _load_render()
    r.VIDEO_ONLY_LORA_DIR = str(tmp_path / "cache")
    junk = str(tmp_path / "junk.safetensors")
    with open(junk, "wb") as f:
        f.write(b"not a safetensors file at all")
    assert r.video_only_lora(junk) == junk
    missing = str(tmp_path / "missing.safetensors")
    assert r.video_only_lora(missing) == missing


def test_only_character_loras_are_rewritten(tmp_path):
    r = _load_render()
    r.VIDEO_ONLY_LORA_DIR = str(tmp_path / "cache")
    src = str(tmp_path / "video.safetensors")
    write_lora(src, VIDEO + AUDIO)
    units = [{"loras": [{"kind": "character", "path": src}, {"kind": "global", "path": src},
                        {"kind": "catalog", "path": src}]}, {}]
    r.use_video_only_character_loras(units)
    paths = [l["path"] for l in units[0]["loras"]]
    assert paths[0] != src and paths[1:] == [src, src]


if __name__ == "__main__":
    # Minimal runner without pytest: use a temp dir per test.
    import tempfile, traceback
    import pathlib
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    passed = 0
    for fn in fns:
        with tempfile.TemporaryDirectory() as d:
            try:
                fn(pathlib.Path(d)); passed += 1; print("ok   ", fn.__name__)
            except Exception:
                print("FAIL ", fn.__name__); traceback.print_exc()
    print("\n%d/%d passed" % (passed, len(fns)))
