"""seed_edit_mflux_child.py -- bin/seed-edit's mflux child: load one Qwen registry model of family
qwen21 (Qwen-Image-2.1, QwenImage21Edit) or qwen2511 (Qwen-Image-Edit-2511, QwenImageEdit) once from
a local pinned snapshot with its LoRAs as local files, then edit the source into every job of a
spec file (docs/superpowers/specs/2026-11-02-seed-generator-design.md, Section 3, amended by
docs/superpowers/specs/2026-11-02-seed-models-design.md, Section 4).

  ~/mflux-edit/.venv/bin/python seed_edit_mflux_child.py --spec SPEC

The spec carries family, model_path, lora_paths and lora_scales (equal-length lists, possibly
empty), width, height, steps, guidance (always 1.0), scheduler (qwen21 only) and jobs, each {n,
seed, prompt, source, output_path}; a spec-level prompt and source (the shape before
docs/superpowers/specs/2026-11-03-qwen-edit-models-design.md) are used for jobs that carry none.
Runs under the mflux venv's Python (mflux pinned to 0.24.0). It never screens: bin/seed-edit
screens each pending image before giving it its final name. After saving each job's image as RGB
it prints "seed-edit-child done <n> <seconds>". LoRAs are never baked into the quantized weights.

Exit codes: 0 every job saved; 2 mflux missing or older than 0.24.0 (refused before the spec is
read) or an unknown family (refused before mlx or mflux is imported); 3 the parent died; anything
else is a crash. Top-level imports are standard library only; mlx and mflux are imported inside
main after both gates.
"""

import argparse
import importlib.metadata
import json
import os
import re
import sys
import threading
import time

MIN_VERSION = (0, 24, 0)
FAMILIES = {
    "qwen21": ("mflux.models.qwen21.variants.edit.qwen_image_21_edit", "QwenImage21Edit", "qwen_image_21"),
    "qwen2511": ("mflux.models.qwen.variants.edit.qwen_image_edit", "QwenImageEdit", "qwen_image_edit_2511"),
}


def parse_version(text):
    m = re.match(r"(\d+)\.(\d+)\.(\d+)", text or "")
    return tuple(int(g) for g in m.groups()) if m else None


def exit_with_parent(poll_s=2.0):
    parent = os.getppid()

    def _watch():
        while True:
            time.sleep(poll_s)
            if os.getppid() != parent:
                os._exit(3)

    threading.Thread(target=_watch, daemon=True).start()


def main(argv=None):
    parser = argparse.ArgumentParser(prog="seed_edit_mflux_child.py")
    parser.add_argument("--spec", required=True)
    args = parser.parse_args(argv)
    exit_with_parent()
    try:
        version = importlib.metadata.version("mflux")
    except importlib.metadata.PackageNotFoundError:
        version = None
    parsed = parse_version(version)
    if parsed is None or parsed < MIN_VERSION:
        print("seed-edit-child: mflux %s is missing or older than 0.24.0; refusing (run bin/seed-edit-setup)"
              % version, flush=True)
        return 2
    with open(args.spec, encoding="utf-8") as f:
        spec = json.load(f)
    family = spec.get("family")
    if family not in FAMILIES:
        print("seed-edit-child: unknown model family %r; refusing" % (family,), flush=True)
        return 2
    import mlx.core as mx
    from mflux.models.common.config.model_config import ModelConfig
    module_name, class_name, config_name = FAMILIES[family]
    model_class = getattr(importlib.import_module(module_name), class_name)
    config = getattr(ModelConfig, config_name)()
    loras = [[os.path.basename(p), s] for p, s in zip(spec["lora_paths"], spec["lora_scales"])]
    print("seed-edit-child: mflux %s, family %s, model %s, transformer overrides %s, scheduler %s, LoRAs %s"
          % (version, family, config.model_name, getattr(config, "transformer_overrides", None),
             spec["scheduler"], json.dumps(loras)), flush=True)
    model = model_class(model_path=spec["model_path"], quantize=None, model_config=config,
                        lora_paths=spec["lora_paths"] or None, lora_scales=spec["lora_scales"] or None,
                        bake_lora=False)
    peak = getattr(mx, "get_peak_memory", None) or mx.metal.get_peak_memory
    for job in spec["jobs"]:
        started = time.monotonic()
        prompt = job["prompt"] if "prompt" in job else spec["prompt"]
        source = job["source"] if "source" in job else spec["source"]
        kwargs = {"seed": job["seed"], "prompt": prompt, "image_paths": [source],
                  "num_inference_steps": spec["steps"], "guidance": spec["guidance"],
                  "width": spec["width"], "height": spec["height"]}
        if family == "qwen21":
            kwargs["scheduler"] = spec["scheduler"]
        else:
            kwargs["negative_prompt"] = " "
        result = model.generate_image(**kwargs)
        result.image.convert("RGB").save(job["output_path"])
        seconds = time.monotonic() - started
        print("seed-edit-child: mlx peak memory %.2f GiB" % (peak() / 2 ** 30), flush=True)
        print("seed-edit-child done %d %.1f" % (job["n"], seconds), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
