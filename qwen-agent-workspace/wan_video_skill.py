"""Wan2.2-TI2V-5B image-to-video skill.

Generates a short video from a static image (optionally guided by a text
prompt) using Wan2.2-TI2V-5B (5B-parameter text/image-to-video diffusion
transformer), alongside the existing LTX-Video pipeline in this workspace
(ltx_video_skill.py).

Runs each stage of generation (text encoding; denoising to latents; VAE
decode + safety-screening + export) in its own short-lived subprocess. On
macOS, only *process exit*
reliably returns a component's resident memory to the OS -- there is no
in-process call that does the same. Manual reclamation calls such as
del, gc.collect(), and torch.mps.empty_cache() are deliberately not used
anywhere in this file: process exit is unconditional, complete, and free,
so those calls would only run microseconds before the process dies anyway.
That is why the three stages are three separate OS processes rather than
three phases of one long-lived one. For the same reason, enable_slicing()
and enable_model_cpu_offload() are also never called here: on Apple Silicon
CPU and GPU share one physical memory pool, so shuffling submodules between
"cpu" and "mps" (enable_model_cpu_offload) changes bookkeeping, not
occupancy, and slicing a batch dimension that is always 1 (enable_slicing)
has nothing to slice. Neither would reduce this file's real peak residency;
only the process boundaries between stages do that.

Measured resident sizes for this model's components (informing the
per-stage memory budget below):

    component        resident dtype    resident size
    text_encoder      bf16 (UMT5)       10.58 GiB
    transformer        bf16              9.33 GiB
    vae                fp32              2.62 GiB (stage 2 encode; 1.31 GiB
                                                   at bf16 in stage 3 decode)

Splitting the work into stage1 (text encoder only, 10.58 GiB), stage2
(transformer + vae, 11.95 GiB, no text encoder ever loaded, denoises to
latents -- does NOT decode), and stage3 (vae only, bf16, 1.31 GiB, no transformer
ever loaded -- decodes the latents stage2 wrote, then screens and exports)
means each process's peak footprint is far below the combined figure, and
each one's memory is unconditionally returned to the OS the moment it
exits. Decode was moved out of stage2 and into stage3 on 2026-08-26: every
attempted geometry at or above 320x320 OOM'd inside AutoencoderKLWan's
decode while stage2 still held the transformer's 9.33 GiB plus the
denoise step's allocator cache -- see the FRACTION_STAGE2/FRACTION_STAGE3
comments below for the measured detail.

This file supports two Wan2.2-TI2V-5B checkpoints, selected via
`--model turbo|base`: the distilled "turbo" checkpoint (4 steps, guidance
1.0) and the "base" checkpoint (50 steps, guidance 5.0). Stage 1's output
(text embeddings, embeds.pt) is portable between the two checkpoints
because their text encoders are byte-identical (confirmed via shared HF
cache blobs) -- a run's embeds.pt encoded under one checkpoint can be
reused by the other without re-running stage 1.

Works on Apple Silicon (MPS) and falls back to CPU. CUDA is used if present.

Usage:
    python3 wan_video_skill.py <image_path> ["<prompt>"] [output_path]

    # or as a module:
    from wan_video_skill import generate_video
    frames = generate_video("robot.png", "the robot waves", output_path="robot.mp4")

Environment:
    HF_TOKEN  Hugging Face access token (optional; omitted falls back to any
              token cached locally by `huggingface-cli login`, or anonymous
              access for public repos).

Generated output is screened by content_safety.assert_frames_safe (on a
sample of frames) before being saved or returned; a positive verdict raises
ContentSafetyError and saves nothing.

This module intentionally does not import torch, diffusers, transformers,
or content_safety at import time -- those imports, and all model loading,
happen inside the per-stage functions below, each of which only ever runs
inside its own subprocess.
"""

import argparse
import datetime
import glob
import json
import os
import shutil
import subprocess
import sys
import uuid

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
if _THIS_DIR not in sys.path:
    sys.path.insert(0, _THIS_DIR)

import mps_guard

MODEL_PRESETS = {
    "turbo": {
        "model_id": "yetter-ai/Wan2.2-TI2V-5B-Turbo-Diffusers",
        "num_inference_steps": 4,
        "guidance_scale": 1.0,
        "negative_prompt": "",
    },
    "base": {
        "model_id": "Wan-AI/Wan2.2-TI2V-5B-Diffusers",
        "num_inference_steps": 50,
        "guidance_scale": 5.0,
        # From the checkpoint's own README example -- with CFG at 5.0, an
        # empty negative prompt encodes as a single </s> token followed by
        # 511 zero-padded positions, which produces a real but degraded
        # extrapolation rather than an error. Turbo is unaffected
        # (guidance_scale=1.0 disables CFG entirely, so negatives are never
        # used), which is why this bug didn't show up in the smoke test.
        "negative_prompt": "色调艳丽，过曝，静态，细节模糊不清，字幕，风格，作品，画作，画面，静止，整体发灰，最差质量，低质量，JPEG压缩残留，丑陋的，残缺的，多余的手指，画得不好的手部，画得不好的脸部，畸形的，毁容的，形态畸形的肢体，手指融合，静止不动的画面，杂乱的背景，三条腿，背景人很多，倒着走",
    },
}
DEFAULT_MODEL = "turbo"
DEFAULT_WIDTH = 512
DEFAULT_HEIGHT = 512
DEFAULT_NUM_FRAMES = 49
DEFAULT_FPS = 24
DEFAULT_SEED = 0
MAX_SEQUENCE_LENGTH = 512
RUNS_SUBDIR = "generated/wan_runs"

# Hand-authored bootstrap table (see wan_ceiling.json's own meta.provenance):
# no Wan sweep has ever run on this host, unlike ltx_ceiling.json which is
# machine-generated from real measurements. _check_ceiling below therefore
# refuses (rather than tolerates) an absent/unreadable table -- see that
# function's docstring.
CEILING_TABLE_PATH = os.path.join(_THIS_DIR, "wan_ceiling.json")

FRACTION_STAGE1 = 0.40
# 0.55 was the hand-authored bootstrap value. Raised to 0.65 on 2026-08-26
# after four consecutive clean MPS-allocator OOMs (256x256x9 aside, every
# geometry tried -- 512x512x49, 384x384x49 twice, 384x384x25, 320x320x25 --
# failed inside the stage-2 VAE decode within 300-500 MB of the 20.59 GiB
# cap) while host-level pressure stayed nil: swap growth was exactly zero
# across all four runs and the Sentinel never fired. The failures were
# PyTorch's own watermark refusing the budget, not the host running out of
# memory. 0.65 -> 24.34 GiB cap; the Sentinel + disk/swap gates remain the
# real backstop for genuine host pressure.
# With decode split out into stage 3 (see _stage3_screen_and_export), 0.65
# may have slack to come back down once a real post-split measurement
# exists -- not changed here, left at the value above pending that
# measurement.
FRACTION_STAGE2 = 0.65
# Raised from 0.10 on 2026-08-26 after moving VAE decode into this stage
# (see _stage3_screen_and_export): stage 3 now holds the fp32 VAE (2.62
# GiB) plus framewise-decode activations, which were empirically the OOM
# driver in the old stage2 (multiple ~0.3-0.8 GiB single allocations
# observed at 320-512px). 0.45 -> ~16.85 GiB cap, generous for VAE+decode
# alone; measure and trim later.
# Raised again 0.45 -> 0.65 same day: the first decode-split run at
# 512x512x49 proved the fp32 framewise decode ALONE needs ~17 GiB (13.05
# GiB allocated + 3.66 other, died 0.26 GiB over the 16.85 cap inside
# RMS_norm at autoencoder_kl_wan.py:206, in a fresh process holding only
# the 2.62 GiB VAE). The transformer-rent theory explained stage 2's OOMs
# but decode's own activation footprint at 512px is the second, larger
# term. 0.65 -> 24.34 GiB cap, ~7.5 GiB above observed need. bf16 decode
# (halving this) is a follow-up option once an fp32 A/B baseline exists.
FRACTION_STAGE3 = 0.65


def _pick_device():
    """Choose the best available device: CUDA > MPS (Apple GPU) > CPU."""
    import torch

    if torch.cuda.is_available():
        return torch.device("cuda")
    if torch.backends.mps.is_available():
        return torch.device("mps")
    return torch.device("cpu")


def _pick_dtype(device):
    """Use bfloat16 on GPU (CUDA/MPS), float32 on CPU for stability."""
    import torch

    return torch.bfloat16 if device.type in ("cuda", "mps") else torch.float32


def _validate_geometry(width, height, num_frames):
    """Raise ValueError naming the offending value and the rule it broke."""
    if width % 32 != 0:
        raise ValueError(
            "width=%d must satisfy width %% 32 == 0 "
            "(vae scale_factor_spatial 16 x transformer patch_size 2 = 32)" % width
        )
    if height % 32 != 0:
        raise ValueError(
            "height=%d must satisfy height %% 32 == 0 "
            "(vae scale_factor_spatial 16 x transformer patch_size 2 = 32)" % height
        )
    # Looser than LTX's (num_frames - 1) % 8 == 0 rule: Wan's VAE
    # scale_factor_temporal is 4, not 8, so only every-4th-frame alignment
    # is required here.
    if (num_frames - 1) % 4 != 0:
        raise ValueError(
            "num_frames=%d must satisfy (num_frames - 1) %% 4 == 0 "
            "(vae scale_factor_temporal 4)" % num_frames
        )


def _check_ceiling(width, height, num_frames, allow_override):
    """Refuse (raise mps_guard.HostSafetyError) a request not covered by the
    hand-authored wan_ceiling.json bootstrap table.

    Deliberately STRICTER than ltx_video_skill.py's _check_ceiling: that
    function tolerates an absent/unreadable table and infers a bound from
    smaller measured resolutions, because mps_guard was calibrated against
    real, measured LTX runs. There is no such calibration for Wan on this
    host -- wan_ceiling.json is a hand-authored, NOT-measured bootstrap
    (see its own meta.provenance) -- so this function refuses outright
    rather than inferring anything, unless allow_override is given.
    """
    if allow_override:
        sys.stderr.write(
            "[wan_video_skill] --allow-override: skipping the ceiling pre-check "
            "(mps_guard watermark cap + sentinel remain the runtime backstop; "
            "an over-budget run will still fail cleanly, not freeze).\n"
        )
        return

    try:
        with open(CEILING_TABLE_PATH) as f:
            table = json.load(f)
    except (OSError, ValueError) as e:
        raise mps_guard.HostSafetyError(
            "HOST SAFETY REFUSAL: wan_ceiling.json is absent or unreadable. Unlike\n"
            "ltx_video_skill.py's _check_ceiling (which tolerates absence because mps_guard\n"
            "was calibrated on real, measured LTX runs), a missing table here is a hard\n"
            "refusal: Wan has no measured ceiling on this host yet. Run\n"
            "tests/measure_wan_ceiling.py (not yet built) to generate a measured table, or\n"
            "pass --allow-override to bypass this pre-check (the watermark cap + sentinel\n"
            "remain the runtime backstop).\n"
            "Underlying error: %s: %s" % (type(e).__name__, e)
        )

    ceiling = table["ceiling"]
    key = "%dx%d" % (width, height)

    if key not in ceiling:
        raise mps_guard.HostSafetyError(
            "HOST SAFETY REFUSAL: resolution %s has no entry in wan_ceiling.json. Available\n"
            "resolutions: %s. Unlike ltx_video_skill.py, no dominated-by-smaller-resolution\n"
            "inference is performed for Wan -- this table is hand-authored, not measured, so\n"
            "there is no basis to infer a bound for an untested resolution. Choose one of the\n"
            "available resolutions or pass --allow-override."
            % (key, sorted(ceiling.keys()))
        )

    max_frames = ceiling[key]
    if num_frames > max_frames:
        raise mps_guard.HostSafetyError(
            "HOST SAFETY REFUSAL: %s supports at most %d frames in wan_ceiling.json, but this\n"
            "request asks for %d frames. Reduce num_frames to <= %d, choose a different\n"
            "resolution, or pass --allow-override."
            % (key, max_frames, num_frames, max_frames)
        )


def _read_request(run_dir):
    with open(os.path.join(run_dir, "request.json")) as f:
        return json.load(f)


def _stage1_encode(run_dir):
    """Encode prompt + negative prompt with the UMT5 text encoder only.

    Never instantiates the full pipeline. Resident weights: ~10.58 GiB
    (text_encoder in bf16). This process exits when the function returns,
    which is what actually releases that memory -- see the note near the
    top of this file about not adding del / gc.collect() / torch.mps.empty_cache() calls.
    """
    mps_guard.set_watermark(FRACTION_STAGE1)
    mps_guard.preflight("stage1", FRACTION_STAGE1, require_servers_down=True)

    request = _read_request(run_dir)

    with mps_guard.Sentinel("stage1", run_dir) as sent:
        import torch
        from transformers import AutoTokenizer, UMT5EncoderModel
        from diffusers.pipelines.wan.pipeline_wan_i2v import prompt_clean

        token = os.environ.get("HF_TOKEN")
        device = _pick_device()
        model_id = request["model_id"]

        tok = AutoTokenizer.from_pretrained(model_id, subfolder="tokenizer", token=token)
        te = UMT5EncoderModel.from_pretrained(
            model_id, subfolder="text_encoder", dtype=torch.bfloat16, token=token
        )
        te.eval()
        te.to(device)

        @torch.no_grad()
        def _encode(text):
            # Replicates diffusers' WanImageToVideoPipeline._get_t5_prompt_embeds.
            text = prompt_clean(text)
            ti = tok(
                [text],
                padding="max_length",
                max_length=MAX_SEQUENCE_LENGTH,
                truncation=True,
                add_special_tokens=True,
                return_attention_mask=True,
                return_tensors="pt",
            )
            mask = ti.attention_mask
            seq_lens = mask.gt(0).sum(dim=1).long()
            emb = te(
                input_ids=ti.input_ids.to(device), attention_mask=mask.to(device)
            ).last_hidden_state
            emb = emb.to(dtype=torch.bfloat16, device=device)
            emb = [u[:v] for u, v in zip(emb, seq_lens)]
            emb = torch.stack(
                [
                    torch.cat([u, u.new_zeros(MAX_SEQUENCE_LENGTH - u.size(0), u.size(1))])
                    for u in emb
                ],
                dim=0,
            )
            return emb

        prompt_embeds = _encode(request["prompt"])
        negative_prompt_embeds = _encode(request["negative_prompt"])
        assert prompt_embeds.shape == (1, 512, 4096), prompt_embeds.shape
        assert negative_prompt_embeds.shape == (1, 512, 4096), negative_prompt_embeds.shape

        import diffusers
        import transformers

        # NO attention masks are saved here -- a deliberate divergence from
        # ltx_video_skill.py's stage1, which does save prompt_attention_mask /
        # negative_prompt_attention_mask. WanImageToVideoPipeline.__call__
        # takes no *_attention_mask parameters at all (unlike LTX's
        # LTXConditionPipeline.__call__), so there is nothing to pass one to.
        torch.save(
            {
                "prompt_embeds": prompt_embeds.cpu(),
                "negative_prompt_embeds": negative_prompt_embeds.cpu(),
                "meta": {
                    "model_id": model_id,
                    "prompt": request["prompt"],
                    "negative_prompt": request["negative_prompt"],
                    "max_sequence_length": MAX_SEQUENCE_LENGTH,
                    "dtype": "bfloat16",
                    "diffusers_version": diffusers.__version__,
                    "transformers_version": transformers.__version__,
                },
            },
            os.path.join(run_dir, "embeds.pt"),
        )

    mps_guard.write_peaks(run_dir, "stage1", sent.peak)
    print("[wan_video_skill] stage1: wrote %s" % os.path.join(run_dir, "embeds.pt"))


def _stage2_denoise(run_dir):
    """Load the transformer + VAE (no text encoder) and denoise to latents.

    Resident weights: 9.33 (transformer, bf16) + 2.62 (vae, fp32) = 11.95 GiB.
    The VAE is loaded here only to encode the conditioning image (see the
    comment on the vae= load below); it is NOT used to decode this stage's
    output. Decode happens in _stage3_screen_and_export, in a fresh process
    that never holds the transformer -- see the module docstring.
    """
    request = _read_request(run_dir)
    mps_guard.set_watermark(FRACTION_STAGE2)
    mps_guard.preflight("stage2", FRACTION_STAGE2, require_servers_down=True)

    with mps_guard.Sentinel("stage2", run_dir) as sent:
        import torch
        from diffusers import AutoencoderKLWan, WanImageToVideoPipeline, WanPipeline
        from diffusers.utils import load_image

        token = os.environ.get("HF_TOKEN")
        device = _pick_device()
        model_id = request["model_id"]

        # The VAE is loaded fp32 -- not bf16 like LTX's VAE -- because it is
        # used TWICE with two different precision requirements: it encodes
        # the anchor conditioning frame (image=...) via sample_mode="argmax"
        # inside WanImageToVideoPipeline.__call__, and it decodes the final
        # output latents. This is a genuine model difference from LTX, not a
        # copy-paste artifact -- do not "fix" this to bf16 to match LTX.
        vae = AutoencoderKLWan.from_pretrained(
            model_id, subfolder="vae", torch_dtype=torch.float32, token=token
        )
        # text_encoder=None must be passed explicitly (not omitted) so the
        # ~10.58 GiB of UMT5 shards are never read in this process.
        mode = request.get("mode", "i2v")
        if mode == "t2v":
            # Pure text-to-video. Verified against this host's cached
            # checkpoints (both Wan-AI/Wan2.2-TI2V-5B-Diffusers and
            # yetter-ai/Wan2.2-TI2V-5B-Turbo-Diffusers ship a model_index.json
            # with "_class_name": "WanPipeline", "expand_timesteps": true,
            # "boundary_ratio": null -- this checkpoint IS natively a
            # WanPipeline (plain T2V) checkpoint; WanImageToVideoPipeline is
            # just an alternate class this same checkpoint also loads under,
            # used for the i2v branch below. WanImageToVideoPipeline itself
            # cannot do T2V -- its check_inputs (pipeline_wan_i2v.py) raises
            # ValueError when both image and image_embeds are None.
            pipeline = WanPipeline.from_pretrained(
                model_id, vae=vae, text_encoder=None, torch_dtype=torch.bfloat16, token=token
            )
        else:
            pipeline = WanImageToVideoPipeline.from_pretrained(
                model_id, vae=vae, text_encoder=None, torch_dtype=torch.bfloat16, token=token
            )
        pipeline.to(device.type)

        # Unlike ltx_video_skill.py, this file never calls
        # pipeline.vae.enable_tiling() and never sets a
        # use_framewise_decoding attribute. AutoencoderKLWan has no
        # use_framewise_decoding attribute at all -- its _decode already
        # loops over one latent frame at a time internally BY CONSTRUCTION,
        # so setting that attribute here would silently create a new,
        # meaningless attribute on the instance rather than configuring
        # anything real. enable_tiling() is also deliberately never called:
        # at these resolutions the tile_sample_min sizes are small enough
        # that tiling would actually trigger, adding visible seams for no
        # memory benefit, since decode is already framewise.
        assert pipeline.config.expand_timesteps is True
        assert pipeline.config.boundary_ratio is None
        assert pipeline.scheduler.config.use_flow_sigmas is True
        assert pipeline.scheduler.config.flow_shift == 5.0
        assert pipeline.vae.use_tiling is False
        assert pipeline.transformer.config.image_dim is None
        # The entire stage-1/stage-2 memory split depends on the ~10.58 GiB
        # UMT5 text encoder never being resident here. text_encoder=None
        # above suppresses it only via an incidental diffusers implementation
        # path (text_encoder is absent from _optional_components but gets
        # reinserted as None via the passed_class_obj rescue in
        # pipeline_utils.py) -- assert the outcome directly rather than
        # trusting that path silently keeps working across a diffusers
        # upgrade.
        assert pipeline.text_encoder is None

        data = torch.load(os.path.join(run_dir, "embeds.pt"), map_location="cpu")
        if (
            data["meta"]["prompt"] != request["prompt"]
            or data["meta"]["negative_prompt"] != request["negative_prompt"]
        ):
            raise RuntimeError(
                "stale embeds.pt: it was encoded for prompt=%r negative_prompt=%r "
                "but request.json now asks for prompt=%r negative_prompt=%r"
                % (
                    data["meta"]["prompt"],
                    data["meta"]["negative_prompt"],
                    request["prompt"],
                    request["negative_prompt"],
                )
            )
        # data["meta"]["model_id"] is NOT checked against request["model_id"]
        # here -- the turbo and base checkpoints' text-encoder shards are
        # byte-identical (verified via shared HF cache blobs), so embeddings
        # are portable between them. meta["model_id"] is recorded purely for
        # forensics, not as a compatibility gate.

        prompt_embeds = data["prompt_embeds"].to(device)
        negative_prompt_embeds = data["negative_prompt_embeds"].to(device)

        # WanImageToVideoPipeline silently DROPS a second/last_image argument
        # when expand_timesteps is True (asserted above) -- refusing rather
        # than producing a clip that silently ignores half its inputs.
        if request.get("last_image_path") is not None or len(request.get("conditions", [])) > 1:
            raise ValueError(
                "wan_video_skill supports exactly one conditioning image at frame 0. "
                "WanImageToVideoPipeline silently DROPS a second/last_image argument when "
                "expand_timesteps is True -- refusing rather than producing a clip that "
                "silently ignores half its inputs."
            )

        # Conditioning images fully control the generated content -- the
        # anchor frame is hard-written into the latent grid -- so an unsafe
        # input essentially guarantees an unsafe output. The stage-3 OUTPUT
        # screening (content_safety.assert_frames_safe, in
        # _stage3_screen_and_export below) is LIVE and active -- it is NOT
        # commented out. This stage-2 INPUT screening below is an optional,
        # currently-disabled add-on that can be enabled independently of
        # stage-3; enabling it does not require -- and must NOT be taken as
        # license to -- disabling the live stage-3 output screening.
        #cond_image = load_image(request["image_path"])
        #try:
        #    content_safety.assert_frames_safe([cond_image], skill="wan_video_skill", prompt=request["prompt"])
        #except content_safety.ContentSafetyError:
        #    raise

        # output_type="latent" instead of "pil" -- verified against the
        # installed diffusers/pipelines/wan/pipeline_wan_i2v.py
        # (WanImageToVideoPipeline.__call__, lines 814-841): the
        # expand_timesteps first-frame compositing at lines 816-817
        # ("latents = (1 - first_frame_mask) * condition + first_frame_mask
        # * latents") runs unconditionally, before the output_type check, so
        # the returned latents already have the conditioning image baked in.
        # But the "if not output_type == 'latent':" block at lines 819-831 --
        # which builds latents_mean/latents_std from vae.config and applies
        # them, then calls self.vae.decode(...) -- is SKIPPED for
        # output_type="latent": line 832 just does "video = latents" with no
        # denormalization or decode. WanPipelineOutput.frames (line 841,
        # pipeline_output.py:9-20) is a plain torch.Tensor in this branch, not
        # a per-video list -- there is no [0] to index, unlike the old
        # result.frames[0] under output_type="pil". Stage 3 must apply the
        # latents_mean/latents_std denormalization and the decode itself.
        #
        # The t2v branch below (plain WanPipeline, no image=) hits the exact
        # same output_type="latent" short-circuit in pipeline_wan.py,
        # WanPipeline.__call__ lines 656-670 -- identical denorm/decode code
        # (same VAE, same latent space) with no first-frame compositing step
        # at all, since there is no conditioning image to bake in. Stage 3's
        # decode is therefore correct unmodified for both modes.
        common_kwargs = dict(
            prompt=None,
            negative_prompt=None,
            prompt_embeds=prompt_embeds,
            negative_prompt_embeds=negative_prompt_embeds,
            height=request["height"],
            width=request["width"],
            num_frames=request["num_frames"],
            num_inference_steps=request["num_inference_steps"],
            guidance_scale=request["guidance_scale"],
            generator=torch.Generator("cpu").manual_seed(request["seed"]),
            output_type="latent",
            max_sequence_length=MAX_SEQUENCE_LENGTH,
        )
        if mode == "t2v":
            result = pipeline(**common_kwargs)
        else:
            result = pipeline(image=load_image(request["image_path"]), **common_kwargs)

        latents = result.frames
        latents_path = os.path.join(run_dir, "latents.pt")
        torch.save(
            {
                "latents": latents.cpu(),
                "meta": {
                    "model_id": model_id,
                    "width": request["width"],
                    "height": request["height"],
                    "num_frames": request["num_frames"],
                    "seed": request["seed"],
                },
            },
            latents_path,
        )

    mps_guard.write_peaks(run_dir, "stage2", sent.peak)
    print("[wan_video_skill] stage2: wrote %s" % latents_path)


def _stage3_screen_and_export(run_dir):
    """Decode latents to frames, screen for unsafe content, export to mp4.

    No diffusion transformer is resident in this process -- only the 2.62
    GiB fp32 VAE (loaded fresh here, in a process that never held the 9.33
    GiB transformer) plus the ~86M param fp32 NSFW classifier pinned to CPU.
    """
    mps_guard.set_watermark(FRACTION_STAGE3)
    mps_guard.preflight("stage3", FRACTION_STAGE3, require_servers_down=True)

    request = _read_request(run_dir)

    with mps_guard.Sentinel("stage3", run_dir) as sent:
        import torch
        from diffusers import AutoencoderKLWan, VideoProcessor
        from diffusers.utils import export_to_video
        import content_safety

        latents_path = os.path.join(run_dir, "latents.pt")
        if not os.path.isfile(latents_path):
            raise RuntimeError(
                "%s is missing -- stage2 must run (or be resumed) before stage3 "
                "can decode." % latents_path
            )
        data = torch.load(latents_path, map_location="cpu")
        latents = data["latents"]

        token = os.environ.get("HF_TOKEN")
        device = _pick_device()
        model_id = request["model_id"]

        # Loaded bf16, unlike stage 2's fp32 VAE load. Measured 2026-08-27:
        # fp32 framewise decode at 512x512x49 needs ~25 GiB and chased two
        # successive caps (died needing 16.97 vs 16.85, then 24.7 vs 24.34 --
        # the second attempt at the final unpatchify, autoencoder_kl_wan.py
        # :118). bf16 is the Turbo checkpoint's NATIVE shipped VAE dtype
        # (its README loads everything bf16); fp32 was this file's
        # conservative override, kept only in stage 2 where the VAE merely
        # encodes one conditioning frame.
        vae = AutoencoderKLWan.from_pretrained(
            model_id, subfolder="vae", torch_dtype=torch.bfloat16, token=token
        )
        vae.to(device)
        # Same rationale as stage 2: AutoencoderKLWan's decode already loops
        # framewise internally by construction, so tiling would only add
        # seams at these resolutions for no memory benefit. (Tiling was
        # briefly enabled on 2026-08-27 chasing what looked like allocator
        # fragmentation; the real cause was the missing no_grad below, and
        # with that fixed, tiling is back off to avoid blend seams.)
        assert vae.use_tiling is False

        latents = latents.to(device)

        # torch.no_grad() is load-bearing here, learned the hard way twice
        # in this workspace. The diffusers pipeline's __call__ is decorated
        # @torch.no_grad(), so decode-inside-the-pipeline never needs it --
        # but this stage calls vae.decode() directly, and without no_grad
        # the autograd graph retains every conv/norm activation across all
        # latent frames: measured on 2026-08-27 as a perfectly linear
        # ~3.7 GiB per 2 s climb that filled ANY watermark cap it was given
        # (16.85, then 24.34) regardless of dtype (fp32/bf16) or tiling --
        # four failed decode attempts before the curve gave it away. Same
        # mechanism as the stage-1 encode incident recorded in
        # ltx_video_skill.py (8.87 -> 13.09 GiB with the graph retained).
        with torch.no_grad():
            # Denormalization copied verbatim from the installed
            # diffusers/pipelines/wan/pipeline_wan_i2v.py,
            # WanImageToVideoPipeline.__call__, lines 819-830 (the
            # "if not output_type == 'latent':" branch) -- this is the step
            # stage 2 skipped by requesting output_type="latent".
            latents = latents.to(vae.dtype)
            latents_mean = (
                torch.tensor(vae.config.latents_mean)
                .view(1, vae.config.z_dim, 1, 1, 1)
                .to(latents.device, latents.dtype)
            )
            latents_std = 1.0 / torch.tensor(vae.config.latents_std).view(
                1, vae.config.z_dim, 1, 1, 1
            ).to(latents.device, latents.dtype)
            latents = latents / latents_std + latents_mean
            video = vae.decode(latents, return_dict=False)[0]

        # Postprocessing replicated from the same file's
        # WanImageToVideoPipeline.__init__ (line 196:
        # "self.video_processor = VideoProcessor(vae_scale_factor=
        # self.vae_scale_factor_spatial)", itself vae.config.scale_factor_spatial
        # per line 195) and __call__ line 831
        # ("video = self.video_processor.postprocess_video(video,
        # output_type=output_type)"). WanPipelineOutput.frames is then this
        # postprocessed video directly (line 841), and stage 2's old
        # output_type="pil" code indexed result.frames[0] to get the single
        # video's PIL list out of the batch -- same indexing applied here.
        video_processor = VideoProcessor(vae_scale_factor=vae.config.scale_factor_spatial)
        video = video_processor.postprocess_video(video, output_type="pil")
        frames = video[0]

        if len(frames) != request["num_frames"]:
            raise RuntimeError(
                "decoded %d frames from latents.pt, expected %d." % (len(frames), request["num_frames"])
            )

        frames_dir = os.path.join(run_dir, "frames")
        shutil.rmtree(frames_dir, ignore_errors=True)
        os.makedirs(frames_dir)
        for i, frame in enumerate(frames):
            frame.save(os.path.join(frames_dir, "frame_%05d.png" % i))

        try:
            content_safety.assert_frames_safe(
                frames, skill="wan_video_skill", prompt=request["prompt"]
            )
        except content_safety.ContentSafetyError:
            # No flagged pixels persist -- honours the "saves nothing"
            # contract. latents.pt is a direct encoding of the blocked
            # frames -- deleting only the PNGs would leave a one-command
            # path (re-running stage3) to regenerate the blocked content, so
            # it is removed here too.
            shutil.rmtree(frames_dir)
            os.remove(latents_path)
            raise

        if request["output_path"] is not None:
            # No frame_rate argument -- Wan has no separate motion-conditioning
            # rate the way LTX does; fps is the only playback-rate concept here.
            export_to_video(frames, request["output_path"], fps=request["fps"])

    mps_guard.write_peaks(run_dir, "stage3", sent.peak)
    # "screened" is load-bearing: only print it on the path where
    # assert_frames_safe actually ran and did not raise above -- never
    # reintroduce this as a bare print if screening is ever conditionally skipped.
    summary = "[wan_video_skill] stage3: screened %d frames" % len(frames)
    if request["output_path"] is not None:
        summary += ", exported to %s" % request["output_path"]
    print(summary)


def _sentinel_abort_line(run_dir, stage_name):
    path = os.path.join(run_dir, "mem_%s.jsonl" % stage_name)
    try:
        with open(path) as f:
            for line in f:
                if '"sentinel_abort"' in line:
                    return line.strip()
    except OSError:
        pass
    return "(no sentinel_abort record found in %s)" % path


def _release_page_cache(run_dir, image_path, prompt, output_path):
    """Evict the page cache between stage 1 and stage 2.

    Stage 1 mmaps ~11.36 GB of UMT5 shards (not T5's 17.74 GiB), which can
    similarly move a chunk of `filebacked`/`active` memory into the
    filesystem cache and lower psutil.available, in the same way documented
    for ltx_video_skill.py's stage 1 (T5 shards) -- see that file's
    _release_page_cache for the measured LTX numbers. The mechanism is the
    same OS-level page-cache behaviour; only the shard size differs here.

    An in-process alternative -- committing and freeing MPS memory to force
    eviction -- was considered and rejected for the same reason documented
    in ltx_video_skill.py: eviction only begins once free memory is
    consumed, so forcing it that way costs far more than `sudo purge` does
    directly.

    Wrapped in try/except so a failure here can never break a run that
    would otherwise succeed.
    """
    try:
        before = mps_guard.snapshot()
        # -n: non-interactive. Without it, a missing cached sudo credential
        # would block on a password prompt that never arrives in this
        # context, rather than failing immediately.
        proc = subprocess.run(
            ["/usr/bin/sudo", "-n", "/usr/sbin/purge"],
            capture_output=True,
            text=True,
            timeout=120,
        )
        if proc.returncode == 0:
            after = mps_guard.snapshot()
            print(
                "[wan_video_skill] page cache released: avail %.2f -> %.2f GiB, "
                "filebacked %.2f -> %.2f GiB"
                % (
                    before["avail_gib"],
                    after["avail_gib"],
                    before["filebacked_gib"],
                    after["filebacked_gib"],
                )
            )
        else:
            if image_path is None:
                resume_line = '  python3 wan_video_skill.py --t2v --resume %s "%s"' % (
                    run_dir,
                    prompt,
                )
            else:
                resume_line = '  python3 wan_video_skill.py --resume %s %s "%s"' % (
                    run_dir,
                    image_path,
                    prompt,
                )
            if output_path:
                resume_line += " %s" % output_path
            sys.stderr.write(
                "[wan_video_skill] note: could not run `sudo purge` (no cached credentials).\n"
                "Stage 1 leaves ~11.36 GB of the UMT5 shards in the filesystem cache, which\n"
                "lowers reported available memory and may cause stage 2 to be refused. If that\n"
                "happens, run `sudo purge` in a terminal and resume without redoing stage 1:\n"
                + resume_line
                + "\n"
            )
    except Exception as e:
        print("[wan_video_skill] note: _release_page_cache failed (continuing): %s" % e)


# The only kwargs generate_video() actually understands. A prior version of
# this file had a multi-condition refusal that checked for `last_image_path`
# and `conditions` keys, but nothing ever wrote those keys into kwargs or
# request.json, so the refusal could never fire -- a caller passing
# last_frame_path=... (LTX's kwarg name) or any other unsupported kwarg was
# silently ignored via **kwargs instead of raising. Whitelisting closes that
# hole for every unsupported kwarg, not just the conditioning ones.
_GENERATE_VIDEO_KWARGS = frozenset({
    "model", "width", "height", "num_frames", "num_inference_steps",
    "guidance_scale", "fps", "negative_prompt", "seed", "allow_override",
    "resume_run_dir",
})


def generate_video(image_path: str, prompt: str = "", output_path: str = None, **kwargs):
    """Generate a short video from a static image using Wan2.2-TI2V-5B.

    Runs three subprocess stages in order (text encoding, denoising, safety
    screening + export), each with its own memory ceiling -- see the module
    docstring for why.

    Args:
        image_path: Path to the input image (local file path or URL), or
            None for text-to-video mode (no conditioning image at all --
            requires a non-empty prompt).
        prompt: Optional text description guiding the motion/content.
            Required (non-empty) when image_path is None.
        output_path: Optional file path to save the MP4. If given, the video
            is saved there.
        **kwargs: model (preset key, default "turbo"), width, height,
            num_frames, num_inference_steps, guidance_scale, fps,
            negative_prompt, seed (default 0), allow_override (default
            False), resume_run_dir (default None; see below).

            wide, last_frame_path, keyframes, and frame_rate are NOT
            supported -- Wan has no equivalent concepts in this
            implementation. Passing any of these, or any other unrecognized
            kwarg, raises TypeError immediately (see _GENERATE_VIDEO_KWARGS)
            rather than silently ignoring it.

    When resume_run_dir is given, stage 1 (if embeds.pt already exists) and
    stage 2 (if latents.pt already exists) are skipped in favour of the
    existing run directory's outputs, rather than starting a fresh run.
    Stage 3 (decode + screen + export) always runs on resume, since it is
    idempotent. request.json is not rewritten; prompt and image_path are
    only checked against it for a stale-embeds mismatch.

    Returns:
        list[PIL.Image.Image]: the generated video frames.
    """
    unknown = set(kwargs) - _GENERATE_VIDEO_KWARGS
    if unknown:
        raise TypeError(
            "generate_video() got unsupported keyword argument(s) %s -- "
            "supported: %s. (last_frame_path/keyframes/wide/frame_rate are "
            "LTX-specific and have no Wan equivalent in this file.)"
            % (sorted(unknown), sorted(_GENERATE_VIDEO_KWARGS))
        )
    if image_path is None:
        # Text-to-video: no conditioning image at all. Checked here, before
        # any run dir creation or torch/diffusers import, so an empty prompt
        # fails fast and cheaply.
        if not isinstance(prompt, str) or not prompt.strip():
            raise ValueError(
                "prompt must be a non-empty string when image_path is None "
                "(text-to-video mode)"
            )
    elif not os.path.isfile(image_path) and "://" not in image_path:
        raise ValueError("image_path %r does not exist" % image_path)

    model = kwargs.get("model", DEFAULT_MODEL)
    if model not in MODEL_PRESETS:
        raise ValueError(
            "unknown model preset %r: choose one of %s" % (model, sorted(MODEL_PRESETS.keys()))
        )
    preset = MODEL_PRESETS[model]
    model_id = preset["model_id"]

    width = kwargs.get("width", DEFAULT_WIDTH)
    height = kwargs.get("height", DEFAULT_HEIGHT)
    num_frames = kwargs.get("num_frames", DEFAULT_NUM_FRAMES)
    num_inference_steps = kwargs.get("num_inference_steps", preset["num_inference_steps"])
    guidance_scale = kwargs.get("guidance_scale", preset["guidance_scale"])
    fps = kwargs.get("fps", DEFAULT_FPS)
    negative_prompt = kwargs.get("negative_prompt", preset["negative_prompt"])
    seed = kwargs.get("seed", DEFAULT_SEED)
    allow_override = kwargs.get("allow_override", False)
    resume_run_dir = kwargs.get("resume_run_dir", None)

    _validate_geometry(width, height, num_frames)

    # --allow-override bypasses ONLY the advisory ceiling-table pre-check.
    # It does not touch mps_guard.preflight, the MPS watermark cap, or the
    # stage-2 Sentinel -- those run in the stage-2 subprocess and remain the
    # authoritative runtime backstop, so an overridden run that is genuinely
    # too big still fails as a clean OOM-at-cap or sentinel abort, not a
    # frozen host. (The allow_override bypass note itself is printed inside
    # _check_ceiling, not here.)
    if resume_run_dir is not None:
        sys.stderr.write(
            "[wan_video_skill] resume: ceiling pre-check skipped (geometry fixed by "
            "the existing run; mps_guard remains the runtime backstop).\n"
        )
    else:
        _check_ceiling(width, height, num_frames, allow_override)

    skip_stage1 = False
    skip_stage2 = False

    if resume_run_dir is not None:
        run_dir = os.path.abspath(resume_run_dir)
        request_path = os.path.join(run_dir, "request.json")
        if not os.path.isdir(run_dir) or not os.path.isfile(request_path):
            raise ValueError(
                "resume_run_dir=%r does not exist or has no request.json" % run_dir
            )

        request = _read_request(run_dir)

        if request["prompt"] != prompt:
            raise ValueError(
                "resume_run_dir=%r request.json has prompt=%r, which does not match "
                "the given prompt=%r -- refusing rather than silently generating from "
                "stale embeds" % (run_dir, request["prompt"], prompt)
            )
        if request["image_path"] is None or image_path is None:
            # t2v run (image_path is None on one or both sides): os.path.abspath
            # would crash on None, so compare the raw values directly instead.
            if request["image_path"] != image_path:
                raise ValueError(
                    "resume_run_dir=%r request.json has image_path=%r, which does not match "
                    "the given image_path=%r -- refusing rather than silently generating from "
                    "stale embeds" % (run_dir, request["image_path"], image_path)
                )
        else:
            abs_request_image_path = os.path.abspath(request["image_path"])
            abs_image_path = os.path.abspath(image_path)
            if abs_request_image_path != abs_image_path:
                raise ValueError(
                    "resume_run_dir=%r request.json has image_path=%r, which does not match "
                    "the given image_path=%r -- refusing rather than silently generating from "
                    "stale embeds" % (run_dir, abs_request_image_path, abs_image_path)
                )

        embeds_path = os.path.join(run_dir, "embeds.pt")
        if os.path.exists(embeds_path):
            skip_stage1 = True
            print("[wan_video_skill] resume: reusing existing embeds.pt, skipping stage 1")

        latents_path = os.path.join(run_dir, "latents.pt")
        if os.path.exists(latents_path):
            skip_stage2 = True
            print("[wan_video_skill] resume: reusing existing latents.pt, skipping stage 2")
        # Stage 3 always runs on resume, even when latents.pt already
        # exists: decode + screen + export is idempotent, and any
        # pre-existing frames/ dir is cleared and rewritten deterministically
        # by _stage3_screen_and_export itself (see its shutil.rmtree +
        # os.makedirs at the top of the frame-writing step), so there is
        # nothing to skip or pre-clear here.
    else:
        workspace = os.path.dirname(os.path.abspath(__file__))
        run_id = "%s-%s" % (
            datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ"),
            uuid.uuid4().hex[:8],
        )
        run_dir = os.path.join(workspace, RUNS_SUBDIR, run_id)
        os.makedirs(run_dir)

        request = {
            "model": model,
            "model_id": model_id,
            "image_path": (
                None if image_path is None
                else image_path if "://" in image_path
                else os.path.abspath(image_path)
            ),
            "mode": "t2v" if image_path is None else "i2v",
            "prompt": prompt,
            "negative_prompt": negative_prompt,
            "output_path": output_path,
            "width": width,
            "height": height,
            "num_frames": num_frames,
            "num_inference_steps": num_inference_steps,
            "guidance_scale": guidance_scale,
            "fps": fps,
            "seed": seed,
            "allow_override": allow_override,
            # Recorded for provenance only -- the stages hardcode their VAE
            # dtypes regardless of this field (stage 2 encodes the
            # conditioning frame at fp32, stage 3 decodes at bf16 -- see
            # each stage's comments). Do not wire this into an actual config
            # path; changing it here has no effect on what the stages do.
            "vae_dtype": "fp32-encode/bf16-decode",
            "max_sequence_length": MAX_SEQUENCE_LENGTH,
        }
        with open(os.path.join(run_dir, "request.json"), "w") as f:
            json.dump(request, f, indent=2)

    for n in (1, 2, 3):
        if n == 1 and skip_stage1:
            continue
        if n == 2 and skip_stage2:
            continue

        proc = subprocess.run(
            [sys.executable, os.path.abspath(__file__), "--stage", str(n), "--run-dir", run_dir],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            check=False,
        )
        print(proc.stdout)
        with open(os.path.join(run_dir, "stage%d.log" % n), "w") as f:
            f.write(proc.stdout)

        if proc.returncode == mps_guard.SENTINEL_EXIT_CODE:
            raise RuntimeError(
                "stage%d aborted by mps_guard sentinel: %s"
                % (n, _sentinel_abort_line(run_dir, "stage%d" % n))
            )
        if proc.returncode != 0:
            log_lines = (proc.stdout or "").splitlines()
            marker = "HOST SAFETY REFUSAL:"
            refusal_index = None
            for i, log_line in enumerate(log_lines):
                if marker in log_line:
                    refusal_index = i
                    first = log_line[log_line.index(marker):]
                    break
            if refusal_index is not None:
                refusal_block = "\n".join([first] + log_lines[refusal_index + 1:])
                raise RuntimeError(
                    "stage%d refused by mps_guard:\n\n%s" % (n, refusal_block)
                )
            tail = "\n".join(log_lines[-40:])
            raise RuntimeError(
                "stage%d failed with exit code %d, last 40 lines of log:\n%s"
                % (n, proc.returncode, tail)
            )

        if n == 1:
            _release_page_cache(run_dir, image_path, prompt, output_path)

    frames_dir = os.path.join(run_dir, "frames")
    paths = sorted(glob.glob(os.path.join(frames_dir, "*.png")))
    from PIL import Image

    frames = [Image.open(p).convert("RGB") for p in paths]

    generate_video.last_run_dir = run_dir
    print("[wan_video_skill] run_dir: %s" % run_dir)
    return frames


if __name__ == "__main__":
    if "--stage" in sys.argv:
        parser = argparse.ArgumentParser()
        parser.add_argument("--stage", type=int, choices=[1, 2, 3], required=True)
        parser.add_argument("--run-dir", dest="run_dir", required=True)
        args = parser.parse_args()
        if args.stage == 1:
            _stage1_encode(args.run_dir)
        elif args.stage == 2:
            _stage2_denoise(args.run_dir)
        elif args.stage == 3:
            _stage3_screen_and_export(args.run_dir)
        sys.exit(0)

    USAGE = (
        'Usage: python3 wan_video_skill.py [--resume RUN_DIR] [--model turbo|base]\n'
        '       [--width N] [--height N] [--num-frames N] [--steps N] [--guidance F]\n'
        '       [--fps N] [--seed N] [--allow-override] [--t2v]\n'
        '       <image_path> ["<prompt>"] [output_path]\n'
        '       (with --t2v: "<prompt>" [output_path] -- no image_path)'
    )

    # --t2v is scanned and stripped BEFORE the positional handling below, in
    # the same style as --allow-override.
    t2v_arg = False
    if "--t2v" in sys.argv:
        t2v_arg = True
        sys.argv.remove("--t2v")

    # Flags are scanned and stripped BEFORE the positional handling below,
    # matching ltx_video_skill.py's --resume/--width/etc. style.
    resume_run_dir = None
    if "--resume" in sys.argv:
        idx = sys.argv.index("--resume")
        if idx + 1 >= len(sys.argv):
            print(USAGE)
            sys.exit(1)
        resume_run_dir = sys.argv[idx + 1]
        sys.argv[idx : idx + 2] = []

    model_arg = None
    if "--model" in sys.argv:
        idx = sys.argv.index("--model")
        if idx + 1 >= len(sys.argv):
            print(USAGE)
            sys.exit(1)
        model_arg = sys.argv[idx + 1]
        sys.argv[idx : idx + 2] = []

    width_arg = None
    if "--width" in sys.argv:
        idx = sys.argv.index("--width")
        if idx + 1 >= len(sys.argv):
            print(USAGE)
            sys.exit(1)
        try:
            width_arg = int(sys.argv[idx + 1])
        except ValueError:
            print("--width requires an integer", file=sys.stderr)
            sys.exit(2)
        sys.argv[idx : idx + 2] = []

    height_arg = None
    if "--height" in sys.argv:
        idx = sys.argv.index("--height")
        if idx + 1 >= len(sys.argv):
            print(USAGE)
            sys.exit(1)
        try:
            height_arg = int(sys.argv[idx + 1])
        except ValueError:
            print("--height requires an integer", file=sys.stderr)
            sys.exit(2)
        sys.argv[idx : idx + 2] = []

    num_frames_arg = None
    if "--num-frames" in sys.argv:
        idx = sys.argv.index("--num-frames")
        if idx + 1 >= len(sys.argv):
            print(USAGE)
            sys.exit(1)
        try:
            num_frames_arg = int(sys.argv[idx + 1])
        except ValueError:
            print("--num-frames requires an integer", file=sys.stderr)
            sys.exit(2)
        sys.argv[idx : idx + 2] = []

    steps_arg = None
    if "--steps" in sys.argv:
        idx = sys.argv.index("--steps")
        if idx + 1 >= len(sys.argv):
            print(USAGE)
            sys.exit(1)
        try:
            steps_arg = int(sys.argv[idx + 1])
        except ValueError:
            print("--steps requires an integer", file=sys.stderr)
            sys.exit(2)
        sys.argv[idx : idx + 2] = []

    guidance_arg = None
    if "--guidance" in sys.argv:
        idx = sys.argv.index("--guidance")
        if idx + 1 >= len(sys.argv):
            print(USAGE)
            sys.exit(1)
        try:
            guidance_arg = float(sys.argv[idx + 1])
        except ValueError:
            print("--guidance requires a number", file=sys.stderr)
            sys.exit(2)
        sys.argv[idx : idx + 2] = []

    fps_arg = None
    if "--fps" in sys.argv:
        idx = sys.argv.index("--fps")
        if idx + 1 >= len(sys.argv):
            print(USAGE)
            sys.exit(1)
        try:
            fps_arg = int(sys.argv[idx + 1])
        except ValueError:
            print("--fps requires an integer", file=sys.stderr)
            sys.exit(2)
        sys.argv[idx : idx + 2] = []

    seed_arg = None
    if "--seed" in sys.argv:
        idx = sys.argv.index("--seed")
        if idx + 1 >= len(sys.argv):
            print(USAGE)
            sys.exit(1)
        try:
            seed_arg = int(sys.argv[idx + 1])
        except ValueError:
            print("--seed requires an integer", file=sys.stderr)
            sys.exit(2)
        sys.argv[idx : idx + 2] = []

    allow_override_arg = False
    if "--allow-override" in sys.argv:
        allow_override_arg = True
        sys.argv.remove("--allow-override")

    if len(sys.argv) < 2:
        print(USAGE)
        sys.exit(1)
    if t2v_arg:
        image_path = None
        prompt = sys.argv[1]
        out = sys.argv[2] if len(sys.argv) > 2 else "wan_video_output.mp4"
    else:
        image_path = sys.argv[1]
        prompt = sys.argv[2] if len(sys.argv) > 2 else ""
        out = sys.argv[3] if len(sys.argv) > 3 else "wan_video_output.mp4"
    extra = {
        "resume_run_dir": resume_run_dir,
        "allow_override": allow_override_arg,
    }
    if model_arg is not None:
        extra["model"] = model_arg
    if width_arg is not None:
        extra["width"] = width_arg
    if height_arg is not None:
        extra["height"] = height_arg
    if num_frames_arg is not None:
        extra["num_frames"] = num_frames_arg
    if steps_arg is not None:
        extra["num_inference_steps"] = steps_arg
    if guidance_arg is not None:
        extra["guidance_scale"] = guidance_arg
    if fps_arg is not None:
        extra["fps"] = fps_arg
    if seed_arg is not None:
        extra["seed"] = seed_arg
    generate_video(
        image_path,
        prompt,
        output_path=out,
        **extra,
    )
