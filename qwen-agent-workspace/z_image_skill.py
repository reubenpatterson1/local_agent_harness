"""Z-Image-Turbo text-to-image skill (A/B alternative to flux_skill.py).

Generates images from a text prompt using Tongyi-MAI's Z-Image-Turbo model
with an abliterated Qwen3-4B text encoder swapped in, for uncensored
generation. Different base architecture from flux_skill.py (single-stream
DiT vs. Flux's dual-stream MMDiT) -- intended for direct A/B comparison.

Works on Apple Silicon (MPS) and falls back to CPU. CUDA is used if present.
The VAE is kept in float32 on MPS to avoid known NaN-artifact issues.

Usage:
    python3 z_image_skill.py "a girl riding a horse" [output_path]

    # or as a module:
    from z_image_skill import generate_image
    img = generate_image("a girl riding a horse")
    img.save("girl_on_horse.png")

Environment:
    HF_TOKEN  Hugging Face access token (optional; omitted falls back to any
              token cached locally by `huggingface-cli login`, or anonymous
              access for public repos).
    Z_IMAGE_HF_HOME  Directory of a Hugging Face cache (containing a `hub/`
              subdirectory) to load the two models from instead of the global
              HF_HOME. Default: ~/hf_home. The global HF_HOME on this host is
              /Volumes/Ollama/hf_home, a USB volume that reads at ~60 MB/s, so
              the 38 GB of shards take ~10 min to load; an internal copy loads
              in well under a minute. Per model, the scoped cache is used only
              when it already contains `hub/models--<org>--<name>`; otherwise
              that model falls back to the default HF cache, so a missing copy
              degrades to slow, never to a silent re-download into an empty dir.
    Z_IMAGE_QUANTIZE_WEIGHTS  Quantize the transformer's weights via
              optimum-quanto (a lazy import -- not a hard dependency unless
              this is set). Only "int8" is implemented. Confirmed 2026-09-27
              on Tongyi-MAI/Z-Image-Turbo's transformer: cuts its real bf16
              footprint from 11.46 GiB to 5.74 GiB, with no visible quality
              loss in a real test generation. The text encoder and VAE are
              never quantized by this.

Explicit content IS allowed.
"""

import os
import sys

import torch
from diffusers import ZImagePipeline, ZImageTransformer2DModel
from transformers import Qwen3Model

import content_safety

BASE_MODEL_ID = "Tongyi-MAI/Z-Image-Turbo"
TEXT_ENCODER_ID = "BennyDaBall/Qwen3-4b-Z-Image-Turbo-AbliteratedV1"


def _z_image_hf_home() -> str:
    """The scoped cache root: $Z_IMAGE_HF_HOME, else ~/hf_home. Read at call time
    (not import time) so tests and callers can change it without reloading."""
    return os.environ.get("Z_IMAGE_HF_HOME", os.path.expanduser("~/hf_home"))


def _cache_dir_for(model_id: str):
    """`<scoped>/hub` if that cache already holds model_id's repo directory, else
    None (= let transformers/diffusers use the default HF cache). The repo
    directory name follows the hub convention: models--<org>--<name>."""
    hub = os.path.join(_z_image_hf_home(), "hub")
    repo_dir = os.path.join(hub, "models--" + model_id.replace("/", "--"))
    return hub if os.path.isdir(repo_dir) else None


def _pick_device() -> torch.device:
    """Choose the best available device: CUDA > MPS (Apple GPU) > CPU."""
    if torch.cuda.is_available():
        return torch.device("cuda")
    if torch.backends.mps.is_available():
        return torch.device("mps")
    return torch.device("cpu")


def _pick_dtype(device: torch.device):
    """Use bfloat16 on GPU (CUDA/MPS), float32 on CPU for stability."""
    return torch.bfloat16 if device.type in ("cuda", "mps") else torch.float32


QUANTIZE_WEIGHTS_SUPPORTED = ("int8",)


def _quantize_weights_env():
    """$Z_IMAGE_QUANTIZE_WEIGHTS if set, else None (no quantization, unchanged
    behavior). Read at call time, not import time. Raises ValueError for any
    value other than the currently-implemented ones."""
    value = os.environ.get("Z_IMAGE_QUANTIZE_WEIGHTS")
    if not value:
        return None
    if value not in QUANTIZE_WEIGHTS_SUPPORTED:
        raise ValueError(
            "Z_IMAGE_QUANTIZE_WEIGHTS=%r is not supported; only %r is currently "
            "implemented" % (value, QUANTIZE_WEIGHTS_SUPPORTED))
    return value


def _quantize_transformer(transformer, qtype_name):
    """Quantize transformer's weights in place to qtype_name ("int8" only, so
    far), via optimum-quanto. Imported lazily so it is not a hard dependency
    unless Z_IMAGE_QUANTIZE_WEIGHTS is actually set."""
    from optimum.quanto import freeze, qint8, quantize
    qtype_map = {"int8": qint8}
    print(f"[z_image_skill] quantizing transformer weights to {qtype_name} ...")
    quantize(transformer, weights=qtype_map[qtype_name])
    freeze(transformer)


def load_pipeline(lora_path=None, loras=None):
    """Load the Z-Image-Turbo pipeline with the abliterated text encoder, moved to the
    best device.

    lora_path: local .safetensors file or HF repo ID, prep for future fine-tuning.
    Omitted unless explicitly set; when given, it is fused into the transformer at
    strength 1.0 (diffusers' ZImageLoraLoaderMixin.load_lora_weights + fuse_lora),
    so every later generate_image() call uses it with no per-call overhead.

    loras: a list of (local .safetensors path, strength) pairs, mutually exclusive with
    lora_path; each is loaded under the adapter name lora0, lora1, ..., checked to have
    registered on the transformer, weighted with set_adapters, and fused in ONE fuse_lora.

    $Z_IMAGE_QUANTIZE_WEIGHTS (see the module docstring) quantizes the transformer
    only, before it is handed to the pipeline; omitted unless explicitly set."""
    if lora_path is not None and loras:
        raise ValueError("lora_path and loras are mutually exclusive")
    device = _pick_device()
    dtype = _pick_dtype(device)
    token = os.environ.get("HF_TOKEN")
    quantize_weights = _quantize_weights_env()
    if quantize_weights and (lora_path is not None or loras):
        raise ValueError(
            "Z_IMAGE_QUANTIZE_WEIGHTS=%s cannot be combined with a LoRA: fuse_lora into "
            "quantized weights is a silent no-op, so the image would render without it; "
            "unset Z_IMAGE_QUANTIZE_WEIGHTS to use LoRAs" % quantize_weights)
    print(f"[z_image_skill] loading {BASE_MODEL_ID} + {TEXT_ENCODER_ID} on {device.type} ({dtype}) ...")
    te_cache = _cache_dir_for(TEXT_ENCODER_ID)
    base_cache = _cache_dir_for(BASE_MODEL_ID)
    print(f"[z_image_skill] cache: {TEXT_ENCODER_ID} <- {te_cache or 'default HF cache'}")
    print(f"[z_image_skill] cache: {BASE_MODEL_ID} <- {base_cache or 'default HF cache'}")
    text_encoder = Qwen3Model.from_pretrained(TEXT_ENCODER_ID, dtype=dtype, token=token, cache_dir=te_cache)

    pipeline_kwargs = dict(text_encoder=text_encoder, torch_dtype=dtype, token=token, cache_dir=base_cache)
    if quantize_weights:
        print(f"[z_image_skill] loading transformer separately for quantization "
              f"(Z_IMAGE_QUANTIZE_WEIGHTS={quantize_weights}) ...")
        transformer = ZImageTransformer2DModel.from_pretrained(
            BASE_MODEL_ID, subfolder="transformer", torch_dtype=dtype, token=token, cache_dir=base_cache)
        _quantize_transformer(transformer, quantize_weights)
        pipeline_kwargs["transformer"] = transformer

    pipeline = ZImagePipeline.from_pretrained(BASE_MODEL_ID, **pipeline_kwargs).to(device)
    pipeline.vae.to(torch.float32)
    if lora_path is not None:
        print(f"[z_image_skill] loading LoRA {lora_path} (fused at strength 1.0)")
        pipeline.load_lora_weights(lora_path)
        pipeline.fuse_lora(lora_scale=1.0)
    elif loras:
        names = []
        for i, (path, strength) in enumerate(loras):
            name = "lora%d" % i
            print(f"[z_image_skill] loading LoRA {path} as adapter {name} (strength {strength})")
            pipeline.load_lora_weights(path, adapter_name=name)
            if name not in pipeline.get_list_adapters().get("transformer", []):
                raise ValueError(f"LoRA {path} matched no Z-Image transformer weights; it is not "
                                 f"a compatible Z-Image LoRA")
            names.append(name)
        pipeline.set_adapters(names, adapter_weights=[float(s) for _, s in loras])
        pipeline.fuse_lora(adapter_names=names, lora_scale=1.0)
        print(f"[z_image_skill] fused {len(names)} LoRA adapter(s)")
    return pipeline


# Lazily-loaded singleton so importing the module doesn't load the model.
_pipeline = None
_pipeline_loras = None


def _get_pipeline(lora_path=None, loras=None):
    """lora_path only takes effect on the FIRST call that constructs the singleton
    (same constraint as Z_IMAGE_HF_HOME): a later call with a different lora_path
    against an already-loaded pipeline is silently ignored. A later call with a
    different loras set raises RuntimeError instead: that set needs a new process."""
    global _pipeline, _pipeline_loras
    key = tuple((str(p), float(s)) for p, s in loras) if loras else None
    if _pipeline is None:
        _pipeline = (load_pipeline(lora_path=lora_path, loras=loras) if loras
                     else load_pipeline(lora_path=lora_path))
        _pipeline_loras = key
    elif key is not None and key != _pipeline_loras:
        raise RuntimeError("z_image_skill's pipeline is already loaded with LoRA set %r; LoRA set "
                           "%r needs a new process" % (_pipeline_loras, key))
    return _pipeline


def generate_image(prompt: str, output_path: str = None, lora_path=None, loras=None, **kwargs):
    """Generate an image from a text prompt using Z-Image-Turbo with the abliterated text encoder.

    Args:
        prompt: Text describing the desired image.
        output_path: Optional file path to save the PNG. If given, the image
            is saved there.
        lora_path: local .safetensors file or HF repo ID, prep for future
            fine-tuning; forwarded to load_pipeline() (see its docstring for
            the singleton-timing caveat). Omitted unless explicitly set.
        loras: list of (local .safetensors path, strength) pairs, mutually exclusive
            with lora_path; fused once when the singleton is built, and a later call
            with a different set raises RuntimeError (see load_pipeline).
        **kwargs: Extra args forwarded to the pipeline call (e.g. height,
            width). Defaults num_inference_steps=9, guidance_scale=0.0 (this
            is a distilled turbo model -- higher steps/CFG do not help), and
            generator=torch.Generator("cpu") (MPS generators are unsupported
            for this model; CPU generator keeps seeds reproducible).

    Returns:
        PIL.Image.Image: The generated image.
    """
    pipeline = (_get_pipeline(lora_path=lora_path, loras=loras) if loras
                else _get_pipeline(lora_path=lora_path))
    kwargs.setdefault("num_inference_steps", 9)
    kwargs.setdefault("guidance_scale", 0.0)
    kwargs.setdefault("generator", torch.Generator("cpu"))
    result = pipeline(prompt, **kwargs)
    image = result.images[0]
    content_safety.assert_image_safe(image, skill="z_image_skill", prompt=prompt)
    if output_path:
        image.save(output_path)
        print(f"[z_image_skill] saved image to {output_path}")
    return image


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 z_image_skill.py \"<prompt>\" [output_path]")
        sys.exit(1)
    prompt = sys.argv[1]
    out = sys.argv[2] if len(sys.argv) > 2 else "z_image_output.png"
    img = generate_image(prompt, output_path=out)
    img.show()
