"""Structural no_grad checker for vae.decode()/vae.encode() calls.

Modelled on check_ltx_no_forbidden_calls.py: a plain `grep` cannot tell
whether a `vae.decode(...)` call is lexically enclosed by a
`with torch.no_grad():` block (or a function decorated with
`@torch.no_grad()`) -- it can only see that the text `no_grad` appears
somewhere in the file. Both wan_video_skill.py (2026-08-27, four failed
decode attempts before the missing no_grad gave itself away via a linear
swap-growth curve) and ltx_video_skill.py's stage-1 T5 encode (dropped
peak MPS from 13.09 GiB back to 8.87 GiB) learned this the hard way: this
is not a defensive nicety, it is load-bearing, and it is exactly the kind
of thing a future edit could silently drop without any test noticing.

So this checker:

  1. Strips comment tokens (via `tokenize`) before parsing, then walks the
     resulting AST with an explicit parent stack, looking for `Call` nodes
     whose callee is `.decode(...)` or `.encode(...)` on a receiver whose
     source text contains "vae". Enclosure by `with torch.no_grad():` or
     by a function decorated `@torch.no_grad()` is checked structurally,
     against the parent stack -- never textually.
  2. Separately re-checks that ltx_video_skill.py's `_stage1_encode`'s
     nested `_encode` still carries its `@torch.no_grad()` decorator, since
     that one is a bare `Call` to T5 rather than to `vae`, and so would not
     otherwise be caught by the general walk above.
  3. Checks the raw, unstripped source text for the literal substring the
     explanatory comment is required to contain, to make sure that
     explanation was not accidentally deleted.
"""

import ast
import io
import sys
import tokenize

DEFAULT_TARGET = "/Users/reubenpatterson/qwen-agent-workspace/ltx_video_skill.py"

REQUIRED_SUBSTRINGS = (
    "torch.no_grad() is load-bearing",
)


def _strip_comments(src):
    """Return a copy of src with every COMMENT token blanked to spaces."""
    lines = src.split("\n")
    tokens = tokenize.generate_tokens(io.StringIO(src).readline)
    for tok in tokens:
        if tok.type == tokenize.COMMENT:
            (srow, scol) = tok.start
            (erow, ecol) = tok.end
            # comment tokens never span multiple lines
            line = lines[srow - 1]
            lines[srow - 1] = line[:scol] + " " * (ecol - scol) + line[ecol:]
    return "\n".join(lines)


def _is_torch_no_grad_call(node):
    """True if node is the Call `torch.no_grad()`."""
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "no_grad"
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "torch"
    )


def _enclosed_by_no_grad(stack):
    """True if any ancestor in `stack` (outermost first) is either a
    `with torch.no_grad():` statement or a function decorated
    `@torch.no_grad()`. Structural, not textual: it walks the explicit
    parent stack built during the AST traversal below.
    """
    for ancestor in stack:
        if isinstance(ancestor, ast.With):
            for item in ancestor.items:
                if _is_torch_no_grad_call(item.context_expr):
                    return True
        elif isinstance(ancestor, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for dec in ancestor.decorator_list:
                if _is_torch_no_grad_call(dec):
                    return True
    return False


def _walk_with_stack(node, stack, visit):
    """Recursive AST walk that maintains an explicit ancestor stack
    (outermost first), so enclosure checks are structural rather than
    relying on line-number heuristics.
    """
    visit(node, stack)
    stack.append(node)
    for child in ast.iter_child_nodes(node):
        _walk_with_stack(child, stack, visit)
    stack.pop()


def _find_unenclosed_vae_calls(tree, src):
    """Return a list of (lineno, expr_text) for vae .decode()/.encode()
    calls not lexically enclosed by torch.no_grad().
    """
    violations = []

    def visit(node, stack):
        if not isinstance(node, ast.Call):
            return
        func = node.func
        if not (isinstance(func, ast.Attribute) and func.attr in ("decode", "encode")):
            return
        receiver_src = ast.get_source_segment(src, func.value) or ""
        if "vae" not in receiver_src:
            return
        if not _enclosed_by_no_grad(stack):
            expr = ast.get_source_segment(src, node) or ("<line %d>" % node.lineno)
            violations.append((node.lineno, expr))

    _walk_with_stack(tree, [], visit)
    return violations


def _stage1_encode_nested_encode_ok(tree):
    """Positive check: `_stage1_encode`'s nested `_encode` must still carry
    an `@torch.no_grad()` decorator (currently ltx_video_skill.py:370).
    Not every target has `_stage1_encode` (e.g. wan_video_skill.py) -- the
    check is a no-op (treated as ok) when the function is simply absent,
    and only fails when `_stage1_encode` is present but its nested
    `_encode` has lost the decorator.
    """
    stage1 = None
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "_stage1_encode":
            stage1 = node
            break
    if stage1 is None:
        return True, "not present"

    nested_encode = None
    for node in ast.walk(stage1):
        if isinstance(node, ast.FunctionDef) and node.name == "_encode":
            nested_encode = node
            break
    if nested_encode is None:
        return False, "_stage1_encode has no nested _encode"

    has_decorator = any(_is_torch_no_grad_call(dec) for dec in nested_encode.decorator_list)
    if not has_decorator:
        return False, "_stage1_encode's nested _encode lost @torch.no_grad()"
    return True, "ok"


def main():
    target = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_TARGET

    with open(target) as f:
        src = f.read()

    stripped = _strip_comments(src)
    tree = ast.parse(stripped, filename=target)

    failures = 0

    # Negative/structural check: every vae .decode()/.encode() call must be
    # lexically enclosed by torch.no_grad().
    violations = _find_unenclosed_vae_calls(tree, stripped)
    if violations:
        for lineno, expr in violations:
            failures += 1
            print("FAIL %s:%d %s not under no_grad" % (target, lineno, expr))
    else:
        print("PASS all vae .decode()/.encode() calls are under no_grad")

    # Positive check: _stage1_encode's nested _encode still decorated.
    ok, detail = _stage1_encode_nested_encode_ok(tree)
    if ok:
        print("PASS _stage1_encode's nested _encode carries @torch.no_grad() (%s)" % detail)
    else:
        failures += 1
        print("FAIL %s" % detail)

    # Required-substring check: the explanatory comment must survive.
    for substring in REQUIRED_SUBSTRINGS:
        desc = "source mentions %r (comment/docstring)" % substring
        if substring in src:
            print("PASS %s" % desc)
        else:
            failures += 1
            print("FAIL %s" % desc)

    if failures:
        print("RESULT: FAIL (%d)" % failures)
        return 1
    print("RESULT: ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
