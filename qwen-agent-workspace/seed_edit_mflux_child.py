"""seed_edit_mflux_child.py -- bin/seed-edit's mflux q4 child: load Qwen-Image-Edit-2511 once from a
local q4 directory with the Lightning LoRA as a local file, then edit the source into every job of
a spec file (docs/superpowers/specs/2026-11-02-seed-generator-design.md, Section 3).

  ~/mflux-edit/.venv/bin/python seed_edit_mflux_child.py --spec SPEC

Runs under the mflux venv's Python (mflux pinned to 0.24.0). It never screens: bin/seed-edit
screens each pending image before giving it its final name. After saving each job's image it
prints "seed-edit-child done <n> <seconds>". guidance is the spec's (always 1.0) and the LoRA is
never baked into the quantized weights.

Exit codes: 0 every job saved; 2 mflux missing or older than 0.22.0 (refused before the spec is
read; an older mflux would run Qwen-Image-Edit-2509); 3 the parent died; anything else is a crash.
Top-level imports are standard library only; mlx and mflux are imported inside main after the
version gate.
"""

import argparse
import importlib.metadata
import json
import os
import re
import sys
import threading
import time

MIN_VERSION = (0, 22, 0)


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
        print("seed-edit-child: mflux %s is missing or older than 0.22.0; refusing (it would run "
              "Qwen-Image-Edit-2509)" % version, flush=True)
        return 2
    with open(args.spec, encoding="utf-8") as f:
        spec = json.load(f)
    import mlx.core as mx
    from mflux.models.common.config.model_config import ModelConfig
    from mflux.models.qwen.variants.edit.qwen_image_edit import QwenImageEdit
    config = ModelConfig.qwen_image_edit_2511()
    print("seed-edit-child: mflux %s, model %s, transformer overrides %s"
          % (version, config.model_name, config.transformer_overrides), flush=True)
    model = QwenImageEdit(model_path=spec["model_path"], quantize=None, model_config=config,
                          lora_paths=[spec["lora_path"]], lora_scales=[1.0], bake_lora=False)
    peak = getattr(mx, "get_peak_memory", None) or mx.metal.get_peak_memory
    for job in spec["jobs"]:
        started = time.monotonic()
        result = model.generate_image(seed=job["seed"], prompt=spec["prompt"],
                                      image_paths=[spec["source"]],
                                      num_inference_steps=spec["steps"], guidance=spec["guidance"],
                                      negative_prompt=" ", width=spec["width"], height=spec["height"])
        result.image.save(job["output_path"])
        seconds = time.monotonic() - started
        print("seed-edit-child: mlx peak memory %.2f GiB" % (peak() / 2 ** 30), flush=True)
        print("seed-edit-child done %d %.1f" % (job["n"], seconds), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
