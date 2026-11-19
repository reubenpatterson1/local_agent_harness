"""seed_lora_registry -- the run-time checks of the custom (user-added) Qwen edit LoRAs
(docs/superpowers/specs/2026-11-17-custom-edit-loras-design.md, Sections 2.2 and 3.3): the LoRA pair rule of
a safetensors header (CL19), a local LoRA's presence and size, and a downloaded Hugging Face LoRA's size and
header (CL22b). qwen_edit.lora_problem and bin/seed-edit-setup import it inside the functions that use it.

Standard library plus lora_catalog (its read_safetensors_header, reused unchanged). Valid on Python 3.9 and
3.13; %-formatting only.
"""

import os

import lora_catalog

PAIR_SUBSTITUTIONS = ((".lora_A.", ".lora_B."), (".lora_down.", ".lora_up."), (".lora.down.", ".lora.up."))
M_LOCAL_MISSING = ("%s is missing or not a regular file (restore it, or re-run bin/seed-edit-lora add after "
                   "bin/seed-edit-lora remove %s)")
M_LOCAL_CHANGED = ("%s is %d bytes; the registry recorded %d (the file changed since it was added: re-run "
                   "bin/seed-edit-lora add after bin/seed-edit-lora remove %s)")
M_HF_SIZE = "%s is %d bytes; the registry recorded %d (delete it and run bin/seed-edit-setup --lora %s again)"
M_HF_NOT_ST = "%s is not a safetensors file (bin/seed-edit-lora remove %s)"
M_HF_NO_PAIRS = ("%s has no LoRA weight pairs in its safetensors header, so mflux would apply nothing "
                 "(bin/seed-edit-lora remove %s)")


def lora_pair_count(header):
    """Custom edit LoRAs spec CL19 (D6): the number of header keys K for which one PAIR_SUBSTITUTIONS swap on
    K + "." (first occurrence) names another key of the header."""
    count = 0
    for key in header:
        probe = key + "."
        for a, b in PAIR_SUBSTITUTIONS:
            if a in probe and probe.replace(a, b, 1)[:-1] in header:
                count += 1
                break
    return count


def local_problem(lora):
    """Custom edit LoRAs spec CL22b: None when a local custom LoRA's file is still a regular file of its recorded
    size (no hash, no header read), else the refusal text."""
    real = os.path.realpath(lora["path"])
    if not os.path.isfile(real):
        return M_LOCAL_MISSING % (lora["path"], lora["id"])
    size = os.path.getsize(real)
    if size != lora["bytes"]:
        return M_LOCAL_CHANGED % (lora["path"], size, lora["bytes"], lora["id"])
    return None


def downloaded_problem(lora, path):
    """Custom edit LoRAs spec CL22b: None when the downloaded file at path of a Hugging Face custom LoRA has its
    recorded size and a safetensors header with LoRA pairs, else the refusal text."""
    real = os.path.realpath(path)
    size = os.path.getsize(real)
    if size != lora["bytes"]:
        return M_HF_SIZE % (path, size, lora["bytes"], lora["id"])
    try:
        header = lora_catalog.read_safetensors_header(real)
    except lora_catalog.CatalogError:
        return M_HF_NOT_ST % (path, lora["id"])
    if lora_pair_count(header) == 0:
        return M_HF_NO_PAIRS % (path, lora["id"])
    return None
