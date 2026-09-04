"""Comment-aware guard for the stage3 content-safety screening call.

This exists because `content_safety.assert_frames_safe` was silently
commented out in `_stage3_screen_and_export` during an unrelated edit on
2026-08-25, while the stage3 success message still claimed frames were
"screened" -- the code stopped screening but kept advertising that it had.

A plain `grep` for `assert_frames_safe` would have found the commented-out
call and reported "present" even though it never ran. The forbidden-call
checker (`check_ltx_no_forbidden_calls.py`) is the mirror image of this
problem: it makes sure specific APIs are never CALLED. This checker makes
sure one specific, REQUIRED API call is ALWAYS live -- so it must do the
opposite of a bare grep: strip comments first via `tokenize`, then parse
the comment-stripped source with `ast`, so a commented-out call can never
satisfy the check.
"""

import ast
import io
import os
import sys
import tokenize

DEFAULT_TARGET = os.path.join(
    os.path.dirname(os.path.dirname(os.path.realpath(__file__))), "ltx_video_skill.py"
)

TARGET_FUNCTION = "_stage3_screen_and_export"
REQUIRED_CALLEE = "assert_frames_safe"


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


def _is_false_const(node):
    return isinstance(node, ast.Constant) and node.value is False


def _find_target_function(tree):
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == TARGET_FUNCTION:
            return node
    return None


def _reachable_body(stmts):
    """Yield statements reachable at "statement level", skipping the
    bodies of `if False:` blocks (dead code), but descending into `try`,
    `with`, and live `if` bodies so a call nested inside them still
    counts as reachable.
    """
    for stmt in stmts:
        yield stmt
        if isinstance(stmt, ast.If):
            if _is_false_const(stmt.test):
                # dead branch -- do not descend
                continue
            for s in _reachable_body(stmt.body):
                yield s
            for s in _reachable_body(stmt.orelse):
                yield s
        elif isinstance(stmt, ast.Try):
            for s in _reachable_body(stmt.body):
                yield s
            for handler in stmt.handlers:
                for s in _reachable_body(handler.body):
                    yield s
            for s in _reachable_body(stmt.orelse):
                yield s
            for s in _reachable_body(stmt.finalbody):
                yield s
        elif isinstance(stmt, ast.With):
            for s in _reachable_body(stmt.body):
                yield s
        elif isinstance(stmt, (ast.For, ast.While)):
            for s in _reachable_body(stmt.body):
                yield s
            for s in _reachable_body(stmt.orelse):
                yield s


def _find_live_call(func_node):
    """Return the lineno of a live, reachable assert_frames_safe call
    inside func_node, or None if there isn't one.
    """
    for stmt in _reachable_body(func_node.body):
        for node in ast.walk(stmt):
            if isinstance(node, ast.Call) and _callee_name(node.func) == REQUIRED_CALLEE:
                return node.lineno
    return None


def main():
    target = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_TARGET

    with open(target) as f:
        src = f.read()

    stripped = _strip_comments(src)
    tree = ast.parse(stripped, filename=target)

    failures = 0

    func_node = _find_target_function(tree)
    if func_node is None:
        failures += 1
        print("FAIL function %s() not found in %s" % (TARGET_FUNCTION, target))
        live_lineno = None
    else:
        print("PASS function %s() found" % TARGET_FUNCTION)
        live_lineno = _find_live_call(func_node)
        if live_lineno is None:
            failures += 1
            print(
                "FAIL no live (uncommented, reachable) call to %s() found inside %s()"
                % (REQUIRED_CALLEE, TARGET_FUNCTION)
            )
        else:
            print(
                "PASS live call to %s() found inside %s() at line %d"
                % (REQUIRED_CALLEE, TARGET_FUNCTION, live_lineno)
            )

    # The "screened" success message is only truthful if the live call above
    # exists. If it does not, the claim is a failure regardless of whether
    # the literal "screened" string is present in the source.
    if live_lineno is None:
        failures += 1
        print(
            "FAIL %s() is absent/dead, so any 'screened' success message would overclaim"
            % REQUIRED_CALLEE
        )
    else:
        print("PASS 'screened' claim is backed by a live %s() call" % REQUIRED_CALLEE)

    if failures:
        print("RESULT: failed (%d)" % failures)
        return 1
    print("RESULT: ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
