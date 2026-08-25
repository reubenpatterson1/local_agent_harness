"""Output-side content screening for the local image/video generation skills.

Inspects generated pixels (not prompt text) after generation completes and
before the result is saved or returned. This is an NSFW/explicit-content
classifier, NOT a CSAM classifier -- no open-weights CSAM classifier exists;
real CSAM detection is hash-matching against known-material databases. A
positive verdict raises ContentSafetyError; it never returns a placeholder
or blanked image, and never saves the flagged output.
"""
import datetime
import json
import os

import numpy as np
import torch
from PIL import Image

CLASSIFIER_MODEL_ID = "Falconsai/nsfw_image_detection"
NSFW_LABEL = "nsfw"
BLOCK_THRESHOLD = 0.5
VIDEO_SAMPLE_FRAMES = 8
LOG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "content_safety.log")


class ContentSafetyError(RuntimeError):
    """Generated output was classified as unsafe. The output was not saved."""


_classifier = None


def _get_classifier():
    global _classifier
    if _classifier is None:
        from transformers import pipeline
        print("[content_safety] loading %s on cpu ..." % CLASSIFIER_MODEL_ID)
        _classifier = pipeline(
            "image-classification",
            model=CLASSIFIER_MODEL_ID,
            device="cpu",
            dtype=torch.float32,
            token=os.environ.get("HF_TOKEN"),
        )
    return _classifier


def _to_pil(frame):
    """Accept a PIL image or an HWC array; return RGB PIL."""
    if isinstance(frame, Image.Image):
        return frame.convert("RGB")
    arr = np.asarray(frame)
    if arr.dtype.kind == "f":
        arr = (np.clip(arr, 0.0, 1.0) * 255.0).round().astype("uint8")
    else:
        arr = arr.astype("uint8")
    return Image.fromarray(arr).convert("RGB")


def _nsfw_score(frame):
    """P(nsfw) in [0,1] for one frame."""
    preds = _get_classifier()(_to_pil(frame))
    for p in preds:
        if str(p["label"]).lower() == NSFW_LABEL:
            return float(p["score"])
    return 0.0


def _sample_indices(n, k):
    """Evenly spaced frame indices, always including 0 and n-1."""
    if n <= 0:
        return []
    k = min(k, n)
    if k == 1:
        return [0]
    return sorted({round(i * (n - 1) / (k - 1)) for i in range(k)})


def _log(record):
    record["ts"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def assert_image_safe(image, *, skill, prompt):
    score = _nsfw_score(image)
    blocked = score >= BLOCK_THRESHOLD
    _log({
        "skill": skill, "kind": "image", "prompt": prompt,
        "verdict": "blocked" if blocked else "allowed",
        "max_nsfw_score": round(score, 4),
        "frames_checked": 1, "frames_flagged": 1 if blocked else 0,
        "classifier": CLASSIFIER_MODEL_ID, "threshold": BLOCK_THRESHOLD,
    })
    if blocked:
        raise ContentSafetyError(
            "CONTENT SAFETY BLOCK: generated image classified NSFW "
            "(p=%.4f >= %.2f) by %s. The image was NOT saved."
            % (score, BLOCK_THRESHOLD, CLASSIFIER_MODEL_ID)
        )


def assert_frames_safe(frames, *, skill, prompt):
    idxs = _sample_indices(len(frames), VIDEO_SAMPLE_FRAMES)
    scores = [(i, _nsfw_score(frames[i])) for i in idxs]
    flagged = [i for i, s in scores if s >= BLOCK_THRESHOLD]
    max_score = max([s for _, s in scores], default=0.0)
    _log({
        "skill": skill, "kind": "video", "prompt": prompt,
        "verdict": "blocked" if flagged else "allowed",
        "max_nsfw_score": round(max_score, 4),
        "frames_total": len(frames), "frames_checked": len(idxs),
        "frames_flagged": len(flagged), "flagged_indices": flagged,
        "classifier": CLASSIFIER_MODEL_ID, "threshold": BLOCK_THRESHOLD,
    })
    if flagged:
        raise ContentSafetyError(
            "CONTENT SAFETY BLOCK: %d of %d sampled frames classified NSFW "
            "(max p=%.4f >= %.2f) by %s. The video was NOT saved."
            % (len(flagged), len(idxs), max_score, BLOCK_THRESHOLD, CLASSIFIER_MODEL_ID)
        )
