"""Comment-aware forbidden-API checker for ltx_video_skill.py.

A plain `grep` cannot tell the difference between a *call* to a forbidden
API and a *comment* that merely names it -- grepping for the bare
substring `enable_slicing` matches both `pipeline.vae.enable_slicing()`
and `# Deliberately NOT calling pipeline.vae.enable_slicing()`. An earlier
version of this check used that kind of bare grep, which forced the
explanatory comments describing *why* these APIs are correctly avoided to
be paraphrased into uselessness (a future reader grepping for the real
API name would find nothing).

The actual invariant is "the code must not CALL these APIs", never "the
file must not MENTION them" -- comments and docstrings are expected, and
required, to name them. So this checker:

  1. Strips comment tokens (via `tokenize`) before parsing, then walks the
     resulting AST looking for actual `Call` nodes to the forbidden APIs
     and any `del` statements. Docstrings survive as `ast.Constant` string
     nodes, which is fine: we only ever inspect call/attribute nodes, never
     string contents, for the negative check.
  2. Separately checks the raw, unstripped source text for the literal
     substrings that the explanatory comments are required to contain, to
     make sure those explanations were not accidentally deleted.
"""

import ast
import io
import sys
import tokenize

DEFAULT_TARGET = "/Users/reubenpatterson/qwen-agent-workspace/ltx_video_skill.py"

FORBIDDEN_CALL_SUFFIXES = (
    "enable_model_cpu_offload",
    "enable_sequential_cpu_offload",
    "enable_slicing",
    "empty_cache",
)

REQUIRED_SUBSTRINGS = (
    "enable_model_cpu_offload",
    "enable_slicing",
    "gc.collect()",
    "torch.mps.empty_cache()",
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


def _callee_name(func):
    """Return the trailing name of a Call's callee (attr or plain id)."""
    if isinstance(func, ast.Attribute):
        return func.attr
    if isinstance(func, ast.Name):
        return func.id
    return None


def _is_gc_collect(func):
    return (
        isinstance(func, ast.Attribute)
        and func.attr == "collect"
        and isinstance(func.value, ast.Name)
        and func.value.id == "gc"
    )


def _find_violations(tree):
    """Return a list of (category, lineno, text) forbidden-call/del sites."""
    violations = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            name = _callee_name(node.func)
            if name and any(name.endswith(suffix) for suffix in FORBIDDEN_CALL_SUFFIXES):
                violations.append((name, node.lineno, "call to %s()" % name))
            elif _is_gc_collect(node.func):
                violations.append(("gc.collect", node.lineno, "call to gc.collect()"))
        elif isinstance(node, ast.Delete):
            violations.append(("del", node.lineno, "del statement"))
    return violations


def main():
    target = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_TARGET

    with open(target) as f:
        src = f.read()

    stripped = _strip_comments(src)
    tree = ast.parse(stripped, filename=target)
    violations = _find_violations(tree)

    failures = 0

    # Negative checks: forbidden APIs must never be CALLED.
    negative_categories = [
        ("enable_model_cpu_offload", "no calls to enable_model_cpu_offload()"),
        ("enable_sequential_cpu_offload", "no calls to enable_sequential_cpu_offload()"),
        ("enable_slicing", "no calls to enable_slicing()"),
        ("empty_cache", "no calls to *.empty_cache()"),
        ("gc.collect", "no calls to gc.collect()"),
        ("del", "no del statements"),
    ]
    for category, desc in negative_categories:
        hits = [v for v in violations if v[0] == category]
        if hits:
            failures += 1
            locations = ", ".join("line %d (%s)" % (v[1], v[2]) for v in hits)
            print("FAIL %s -- found: %s" % (desc, locations))
        else:
            print("PASS %s" % desc)

    # Positive checks: the explanatory comments must still name these APIs.
    for substring in REQUIRED_SUBSTRINGS:
        desc = "source mentions %r (comment/docstring)" % substring
        if substring in src:
            print("PASS %s" % desc)
        else:
            failures += 1
            print("FAIL %s" % desc)

    if failures:
        print("RESULT: failed (%d)" % failures)
        return 1
    print("RESULT: ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
