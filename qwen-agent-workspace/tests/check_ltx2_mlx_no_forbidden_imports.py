"""Forbidden-import checker for ltx2_mlx_video_skill.py.

The new MLX render path exists precisely so that no part of it drags
mps_guard, torch, diffusers, transformers, mlx, PIL or content_safety into
the process. That module shells out to a CLI; it never loads a model. This
checker enforces that invariant structurally.

Modelled on tests/check_ltx_no_forbidden_calls.py: it walks the AST rather
than grepping, so a COMMENT or DOCSTRING that names a forbidden module (and
the module docstring is required to name several of them, to explain why
they are absent) is fine. Only real ast.Import / ast.ImportFrom nodes fail,
at ANY scope -- module level, function body, class body or conditional.
"""

import ast
import os
import sys

_THIS_DIR = os.path.dirname(os.path.realpath(__file__))
DEFAULT_TARGET = os.path.join(os.path.dirname(_THIS_DIR), "ltx2_mlx_video_skill.py")

FORBIDDEN_ROOTS = (
    "mps_guard",
    "torch",
    "diffusers",
    "transformers",
    "mlx",
    "mlx_lm",
    "PIL",
    "content_safety",
)


def find_forbidden_imports(tree):
    """Return a list of (root_module, lineno, description) for every real
    import of a forbidden module, at any scope."""
    hits = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".")[0]
                if root in FORBIDDEN_ROOTS:
                    hits.append((root, node.lineno, "import %s" % alias.name))
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                root = node.module.split(".")[0]
                if root in FORBIDDEN_ROOTS:
                    hits.append((root, node.lineno, "from %s import ..." % node.module))
    return hits


def main():
    target = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_TARGET

    with open(target) as f:
        src = f.read()
    tree = ast.parse(src, filename=target)
    hits = find_forbidden_imports(tree)

    failures = 0
    for root in FORBIDDEN_ROOTS:
        matched = [h for h in hits if h[0] == root]
        if matched:
            failures += 1
            where = ", ".join("line %d (%s)" % (h[1], h[2]) for h in matched)
            print("FAIL no import of %r -- found: %s" % (root, where))
        else:
            print("PASS no import of %r" % root)

    if failures:
        print("RESULT: failed (%d)" % failures)
        return 1
    print("RESULT: ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
