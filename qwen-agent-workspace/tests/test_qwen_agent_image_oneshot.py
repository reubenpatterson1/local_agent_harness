"""Plain-python (no pytest) offline tests for bin/qwen-agent's --image one-shot feature.

Run: python3 tests/test_qwen_agent_image_oneshot.py
Covers the 2026-09-12 --seed-image design's qwen-agent side: --image CLI
validation, the multimodal one-shot user message, and estimate_tokens' image-aware
accounting. Fully offline -- no server call is made; the CLI-rejection cases exit
before setup() ever opens a socket.
"""

import argparse
import ast
import base64
import importlib.machinery
import importlib.util
import json
import os
import subprocess
import sys
import tempfile

WS = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
_SCRIPT_PATH = os.path.join(WS, "bin", "qwen-agent")

_loader = importlib.machinery.SourceFileLoader("qwen_agent", _SCRIPT_PATH)
_spec = importlib.util.spec_from_loader("qwen_agent", _loader)
qwen_agent = importlib.util.module_from_spec(_spec)
sys.modules["qwen_agent"] = qwen_agent
_loader.exec_module(qwen_agent)

qwen_agent.TOOLS = qwen_agent.build_tools_for_context(None)
qwen_agent.TOOL_BY_NAME = {t["function"]["name"]: t for t in qwen_agent.TOOLS}
qwen_agent.ONESHOT = True

TOTAL = 0
FAILED = 0


def check(name, condition, detail=""):
    global TOTAL, FAILED
    TOTAL += 1
    if condition:
        print("PASS %s" % name)
    else:
        FAILED += 1
        print("FAIL %s %s" % (name, detail))


def _png(path, w, h):
    """Write a solid-color PNG at path via PIL."""
    from PIL import Image
    Image.new("RGB", (w, h), (12, 34, 56)).save(path, format="PNG")


def _noisy_png(path, w, h):
    """Write a random-noise PNG at path via PIL.

    Unlike a solid color (which a PNG encoder compresses to a few hundred bytes
    regardless of w/h), random pixel data compresses poorly, so the resulting
    file -- and its base64 payload -- is representative of a real seeded photo's
    size at these dimensions, not a degenerate best case.
    """
    from PIL import Image
    Image.frombytes("RGB", (w, h), os.urandom(w * h * 3)).save(path, format="PNG")


def _ns(**kw):
    """An argparse.Namespace suitable for _oneshot_user_message, defaulting to a
    plain text one-shot ("hello", no image), overridable via kwargs."""
    ns = argparse.Namespace(user_prompt="hello", image=None)
    for key, value in kw.items():
        setattr(ns, key, value)
    return ns


# ---------------------------------------------------------------------------
# Q1-Q3: --image CLI rejections, fully offline
# ---------------------------------------------------------------------------

def test_cli_rejections():
    with tempfile.TemporaryDirectory() as tmp:
        good_png = os.path.join(tmp, "good.png")
        _png(good_png, 4, 4)
        not_a_png = os.path.join(tmp, "not_a.png")
        with open(not_a_png, "w") as f:
            f.write("this is plain text, not a PNG\n")
        missing = os.path.join(tmp, "missing.png")

        # Q1: --image with no --user-prompt
        proc = subprocess.run(
            [sys.executable, _SCRIPT_PATH, "--image", good_png],
            capture_output=True, text=True,
        )
        check("Q1 rc == 2", proc.returncode == 2, "got %r" % proc.returncode)
        check("Q1 stderr mentions requires --user-prompt",
              "--image requires --user-prompt." in proc.stderr, "got %r" % proc.stderr)

        # Q2: --image points at a nonexistent file
        proc = subprocess.run(
            [sys.executable, _SCRIPT_PATH, "--image", missing, "--user-prompt", "hi"],
            capture_output=True, text=True,
        )
        check("Q2 rc == 2", proc.returncode == 2, "got %r" % proc.returncode)
        check("Q2 stderr mentions file not found",
              "--image file not found:" in proc.stderr, "got %r" % proc.stderr)

        # Q3: --image points at a file that is not really a PNG
        proc = subprocess.run(
            [sys.executable, _SCRIPT_PATH, "--image", not_a_png, "--user-prompt", "hi"],
            capture_output=True, text=True,
        )
        check("Q3 rc == 2", proc.returncode == 2, "got %r" % proc.returncode)
        check("Q3 stderr mentions must be a PNG",
              "must be a PNG" in proc.stderr, "got %r" % proc.stderr)


# ---------------------------------------------------------------------------
# Q4: _oneshot_user_message shape
# ---------------------------------------------------------------------------

def test_user_message_shape():
    # Q4a: no image -> plain string content, unchanged from today's shape.
    msg = qwen_agent._oneshot_user_message(_ns())
    check("Q4a no-image message shape", msg == {"role": "user", "content": "hello"},
          "got %r" % (msg,))
    check("Q4a content is a str", isinstance(msg["content"], str), "got %r" % type(msg["content"]))

    with tempfile.TemporaryDirectory() as tmp:
        png_path = os.path.join(tmp, "seed.png")
        _png(png_path, 8, 6)
        with open(png_path, "rb") as f:
            raw_bytes = f.read()

        msg = qwen_agent._oneshot_user_message(_ns(image=png_path))
        content = msg["content"]
        is_list_of_2 = isinstance(content, list) and len(content) == 2
        check("Q4b content is a list of length 2", is_list_of_2, "got %r" % (content,))
        # Guarded on is_list_of_2 below: a mutation that drops the image_url part
        # (returning plain string content instead) must FAIL these checks visibly
        # rather than crash with an unrelated AttributeError/IndexError.
        part0 = content[0] if is_list_of_2 else None
        part1 = content[1] if is_list_of_2 else None
        check("Q4b content[0] is the text part",
              is_list_of_2 and part0 == {"type": "text", "text": "hello"},
              "got %r" % (part0,))
        check("Q4b content[1] type is image_url",
              is_list_of_2 and isinstance(part1, dict) and part1.get("type") == "image_url",
              "got %r" % (part1,))
        url = (part1.get("image_url", {}).get("url", "")
               if is_list_of_2 and isinstance(part1, dict) else "")
        check("Q4b url starts with data:image/png;base64,",
              url.startswith("data:image/png;base64,"), "got %r" % url[:40])

        # Q4c: round-trip -- decoding the base64 payload reproduces the raw bytes
        # exactly, proving no resize/re-encode happens in qwen-agent.
        b64_payload = url.split(",", 1)[1] if "," in url else ""
        check("Q4c base64 round-trips to the original bytes",
              bool(b64_payload) and base64.b64decode(b64_payload) == raw_bytes,
              "mismatched bytes")

        # Q4d: the message must be JSON-serialisable (it is sent as JSON).
        try:
            json.dumps(msg)
            dumped_ok = True
        except Exception as e:
            dumped_ok = False
            _ = e
        check("Q4d json.dumps(msg) does not raise", dumped_ok)


# ---------------------------------------------------------------------------
# Q5: image-aware token accounting
# ---------------------------------------------------------------------------

def test_image_token_accounting():
    check("Q5a IMAGE_TOKENS == 2048", qwen_agent.IMAGE_TOKENS == 2048,
          "got %r" % qwen_agent.IMAGE_TOKENS)

    huge_url = "data:image/png;base64," + "A" * 2_000_000
    msg_with_image = {"role": "user", "content": [
        {"type": "text", "text": "x" * 300},
        {"type": "image_url", "image_url": {"url": huge_url}},
    ]}
    estimate_with_image = qwen_agent.estimate_tokens([msg_with_image], False)
    check("Q5b huge base64 image estimates under 3000 tokens",
          estimate_with_image < 3000, "got %r" % estimate_with_image)

    msg_without_image = {"role": "user", "content": [
        {"type": "text", "text": "x" * 300},
    ]}
    estimate_without_image = qwen_agent.estimate_tokens([msg_without_image], False)
    # NOTE: checked against the literal 2048, not qwen_agent.IMAGE_TOKENS -- a
    # self-referential check (">= qwen_agent.IMAGE_TOKENS") is trivially satisfied
    # even after mutating IMAGE_TOKENS to 0, since the constant used as the pass
    # bar would shrink right along with the thing being measured.
    check("Q5c image part costs at least IMAGE_TOKENS (2048) more",
          estimate_with_image - estimate_without_image >= 2048,
          "with=%r without=%r" % (estimate_with_image, estimate_without_image))

    msg_two_images = {"role": "user", "content": [
        {"type": "text", "text": "x" * 300},
        {"type": "image_url", "image_url": {"url": huge_url}},
        {"type": "image_url", "image_url": {"url": huge_url}},
    ]}
    estimate_two_images = qwen_agent.estimate_tokens([msg_two_images], False)
    # NOTE: same reasoning as Q5c -- checked against the literal 2048, not
    # qwen_agent.IMAGE_TOKENS, so mutating the constant to 0 cannot vacuously
    # satisfy this by shrinking both sides of the comparison together.
    check("Q5d second image costs exactly IMAGE_TOKENS (2048) more",
          estimate_two_images - estimate_with_image == 2048,
          "two=%r one=%r" % (estimate_two_images, estimate_with_image))

    # Q5e: CRITICAL regression check. For plain string-content messages,
    # estimate_tokens must equal EXACTLY what the old, pre-refactor unconditional
    # formula produced -- proof this refactor moved no text-only number at all.
    msgs = [
        {"role": "system", "content": "you are a helpful assistant" * 5},
        {"role": "user", "content": "hello there, how are you today?"},
        {"role": "assistant", "content": "I am doing well, thank you for asking!" * 3},
    ]
    old_formula_total = sum(
        len(json.dumps(m)) // qwen_agent.CHARS_PER_TOKEN + qwen_agent.PER_MESSAGE_TOKENS
        for m in msgs
    )
    new_total = qwen_agent.estimate_tokens(msgs, False)
    check("Q5e string-content messages: byte-identical to the old formula",
          new_total == old_formula_total, "old=%r new=%r" % (old_formula_total, new_total))

    # Q5f: a realistic seeded Phase-1-sized prompt still fits, with real headroom.
    # A 1024x768 NOISY (not solid-color) PNG: matches bin/ltx-movie's
    # SEED_DOWNSCALE_MAX_EDGE (1024px long edge) and does not compress away to a
    # trivial size, so this genuinely exercises the "big real photo" case F1 was
    # written for, not a few-hundred-byte degenerate best case.
    with tempfile.TemporaryDirectory() as tmp:
        png_path = os.path.join(tmp, "seed.png")
        _noisy_png(png_path, 1024, 768)
        system_msg = qwen_agent.build_system_message(qwen_agent.WORKSPACE)
        user_msg = qwen_agent._oneshot_user_message(_ns(image=png_path))
        total = qwen_agent.estimate_tokens([system_msg, user_msg], True)
        budget = qwen_agent.CONTEXT_WINDOW - qwen_agent.CONTEXT_FLOOR
        check("Q5f seeded Phase-1-sized prompt fits with real headroom to spare",
              total < budget, "got %r, budget %r" % (total, budget))


# ---------------------------------------------------------------------------
# Q6-Q7: source guards
# ---------------------------------------------------------------------------

def test_source_guards():
    with open(_SCRIPT_PATH) as f:
        src = f.read()

    check("Q6a oneshot() calls _oneshot_user_message(args_ns)",
          "messages = [system_msg, _oneshot_user_message(args_ns)]" in src)

    old_literal = '{"role": "user", "content": args_ns.user_prompt}'
    check("Q6b the old literal appears exactly once (inside _oneshot_user_message only)",
          src.count(old_literal) == 1, "got %d" % src.count(old_literal))

    tree = ast.parse(src, filename=_SCRIPT_PATH)
    heavy = ("PIL", "numpy", "torch", "requests")
    violations = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.split(".")[0] in heavy:
                    violations.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module and node.module.split(".")[0] in heavy:
                violations.append(node.module)
    check("Q6c no import of PIL/numpy/torch/requests anywhere", not violations,
          "found: %r" % violations)

    check("Q6d module docstring still says standard-library-only",
          "standard-library-only" in (ast.get_docstring(tree) or ""))

    # Q7: the REPL path (repl()) is untouched by this feature.
    # NOTE: checked via repl()'s own AST node, not the raw text between "def
    # repl(args_ns):" and "def oneshot(args_ns):" -- Step 4 places
    # _oneshot_user_message (which legitimately contains "image_url") textually
    # between the two, as a sibling function, so a plain substring slice would
    # false-fail on code that was never part of repl() at all.
    repl_node = next(
        n for n in ast.walk(tree)
        if isinstance(n, ast.FunctionDef) and n.name == "repl"
    )
    repl_src = ast.get_source_segment(src, repl_node)
    check("Q7 repl() body mentions neither --image nor image_url",
          "--image" not in repl_src and "image_url" not in repl_src)


if __name__ == "__main__":
    test_cli_rejections()
    test_user_message_shape()
    test_image_token_accounting()
    test_source_guards()

    print("OK %d/%d" % (TOTAL - FAILED, TOTAL))
    sys.exit(0 if FAILED == 0 else 1)
