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

Generated output is screened by content_safety.assert_image_safe before
being saved or returned; a positive verdict raises ContentSafetyError and
saves nothing.
"""

import os
import sys

import torch
from diffusers import ZImagePipeline
from transformers import Qwen3Model

import content_safety

BASE_MODEL_ID = "Tongyi-MAI/Z-Image-Turbo"
TEXT_ENCODER_ID = "BennyDaBall/Qwen3-4b-Z-Image-Turbo-AbliteratedV1"


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


def load_pipeline():
    """Load the Z-Image-Turbo pipeline with the abliterated text encoder, moved to the best device."""
    device = _pick_device()
    dtype = _pick_dtype(device)
    token = os.environ.get("HF_TOKEN")
    print(f"[z_image_skill] loading {BASE_MODEL_ID} + {TEXT_ENCODER_ID} on {device.type} ({dtype}) ...")
    text_encoder = Qwen3Model.from_pretrained(TEXT_ENCODER_ID, dtype=dtype, token=token)
    pipeline = ZImagePipeline.from_pretrained(
        BASE_MODEL_ID,
        text_encoder=text_encoder,
        torch_dtype=dtype,
        token=token,
    ).to(device)
    pipeline.vae.to(torch.float32)
    return pipeline


# Lazily-loaded singleton so importing the module doesn't load the model.
_pipeline = None


def _get_pipeline():
    global _pipeline
    if _pipeline is None:
        _pipeline = load_pipeline()
    return _pipeline


def generate_image(prompt: str, output_path: str = None, **kwargs):
    """Generate an image from a text prompt using Z-Image-Turbo with the abliterated text encoder.

    Args:
        prompt: Text describing the desired image.
        output_path: Optional file path to save the PNG. If given, the image
            is saved there.
        **kwargs: Extra args forwarded to the pipeline call (e.g. height,
            width). Defaults num_inference_steps=9, guidance_scale=0.0 (this
            is a distilled turbo model -- higher steps/CFG do not help), and
            generator=torch.Generator("cpu") (MPS generators are unsupported
            for this model; CPU generator keeps seeds reproducible).

    Returns:
        PIL.Image.Image: The generated image.
    """
    pipeline = _get_pipeline()
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
