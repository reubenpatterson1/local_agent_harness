"""Flux text-to-image skill.

Generates images from a text prompt using the Flux.1-dev-abliterated model
loaded from Hugging Face (served from the local cache once downloaded; a
backup copy of the cache lives on the SSD at /Volumes/Ollama/models/huggingface_cache).

Works on Apple Silicon (MPS) and falls back to CPU. CUDA is used if present.

Usage:
    python3 flux_skill.py "a girl riding a horse" [output_path]

    # or as a module:
    from flux_skill import generate_image
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
from diffusers import AutoPipelineForText2Image

import content_safety

MODEL_ID = "SicariusSicariiStuff/flux.1dev-abliteratedv2"


def _pick_device() -> torch.device:
    """Choose the best available device: CUDA > MPS (Apple GPU) > CPU."""
    if torch.cuda.is_available():
        return torch.device("cuda")
    if torch.backends.mps.is_available():
        return torch.device("mps")
    return torch.device("cpu")


def _pick_dtype(device: torch.device):
    """Use float16 on GPU (CUDA/MPS), float32 on CPU for stability."""
    return torch.float16 if device.type in ("cuda", "mps") else torch.float32


def load_pipeline():
    """Load the Flux pipeline once and return it, moved to the best device."""
    device = _pick_device()
    dtype = _pick_dtype(device)
    token = os.environ.get("HF_TOKEN")
    print(f"[flux_skill] loading {MODEL_ID} on {device.type} ({dtype}) ...")
    pipeline = AutoPipelineForText2Image.from_pretrained(
        MODEL_ID,
        torch_dtype=dtype,
        token=token,
    ).to(device)
    return pipeline


# Lazily-loaded singleton so importing the module doesn't load the model.
_pipeline = None


def _get_pipeline():
    global _pipeline
    if _pipeline is None:
        _pipeline = load_pipeline()
    return _pipeline


def generate_image(prompt: str, output_path: str = None, **kwargs):
    """Generate an image from a text prompt using the Flux abliterated model.

    Args:
        prompt: Text describing the desired image.
        output_path: Optional file path to save the PNG. If given, the image
            is saved there.
        **kwargs: Extra args forwarded to the pipeline call (e.g.
            num_inference_steps, guidance_scale, height, width).

    Returns:
        PIL.Image.Image: The generated image.
    """
    pipeline = _get_pipeline()
    result = pipeline(prompt, **kwargs)
    image = result.images[0]
    content_safety.assert_image_safe(image, skill="flux_skill", prompt=prompt)
    if output_path:
        image.save(output_path)
        print(f"[flux_skill] saved image to {output_path}")
    return image


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 flux_skill.py \"<prompt>\" [output_path]")
        sys.exit(1)
    prompt = sys.argv[1]
    out = sys.argv[2] if len(sys.argv) > 2 else "flux_output.png"
    img = generate_image(prompt, output_path=out)
    img.show()
