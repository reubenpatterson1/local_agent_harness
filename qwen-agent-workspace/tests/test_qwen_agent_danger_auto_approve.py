"""Plain-python (no pytest) offline tests for bin/qwen-agent's --danger-auto-approve
flag: the argparse flag itself, the dispatch-site bypass composed on top of the
unmodified should_auto_approve() gate, the [danger-auto] vs [auto] trace labels,
the promote-is-never-bypassed guarantee, and the startup warning. Fully offline --
HOME is a temp directory and every server/subprocess-adjacent call that would leave
the sandbox is monkeypatched; bash and run_python DO run for real, but only trivial
echo/print commands inside a throwaway workspace.

Run: python3 tests/test_qwen_agent_danger_auto_approve.py
"""

import contextlib
import importlib.machinery
import importlib.util
import inspect
import io
import json
import os
import sys
import tempfile
from pathlib import Path

# HOME is redirected BEFORE bin/qwen-agent is loaded, matching the other test
# files' convention.
_HOME = tempfile.mkdtemp(prefix="qwen-agent-daa-test-import-")
os.environ["HOME"] = _HOME

WS = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
_SCRIPT_PATH = os.path.join(WS, "bin", "qwen-agent")

_loader = importlib.machinery.SourceFileLoader("qwen_agent", _SCRIPT_PATH)
_spec = importlib.util.spec_from_loader("qwen_agent", _loader)
qwen_agent = importlib.util.module_from_spec(_spec)
sys.modules["qwen_agent"] = qwen_agent
_loader.exec_module(qwen_agent)

# The ten-tool REPL schema; repl() normally does this after memory_start().
qwen_agent.TOOLS = qwen_agent.build_tools_for_context(None) + qwen_agent._MEMORY_TOOLS
qwen_agent.TOOL_BY_NAME = {t["function"]["name"]: t for t in qwen_agent.TOOLS}
# Route _ui() to stderr so [auto]/[danger-auto] lines do not interleave with PASS.
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


def _ns(danger):
    """An args_ns for dispatch(), with the flag set as requested."""
    ns = qwen_agent.parse_args(["--danger-auto-approve"] if danger else [])
    ns.tool_timeout = 5
    return ns


def _tc(name, args):
    return {"id": "call_1", "type": "function",
            "function": {"name": name, "arguments": json.dumps(args)}}


@contextlib.contextmanager
def _sandbox():
    """A throwaway WORKSPACE plus a _prompt_line stub that counts and denies.

    Any prompt reached while a test isn't expecting one both gets counted (so
    the assertion catches it) and answers "n" (so a leaked prompt can never
    actually let a real command run).
    """
    tmp = tempfile.mkdtemp(prefix="qwen-agent-daa-sandbox-")
    orig_workspace = qwen_agent.WORKSPACE
    orig_prompt = qwen_agent._prompt_line
    calls = []
    # realpath() matches setup()'s own WORKSPACE assignment (Section: WORKSPACE
    # setup) -- on macOS, tempfile.mkdtemp() returns a /var/... path that is
    # itself a symlink to /private/var/..., and resolve_in_workspace() compares
    # against the REALPATH of every candidate, so an un-realpath'd WORKSPACE
    # here would reject every write_file call as "outside the workspace".
    qwen_agent.WORKSPACE = Path(os.path.realpath(tmp))
    qwen_agent._prompt_line = lambda text: (calls.append(text), "n")[1]
    try:
        yield tmp, calls
    finally:
        qwen_agent.WORKSPACE = orig_workspace
        qwen_agent._prompt_line = orig_prompt


def test_flag_default_and_parse():
    check("D1 default is False",
          qwen_agent.parse_args([]).danger_auto_approve is False)
    check("D2 flag parses to True",
          qwen_agent.parse_args(["--danger-auto-approve"]).danger_auto_approve is True)

    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            qwen_agent.parse_args(["--help"])
    except SystemExit:
        pass
    check("D3 flag listed in --help",
          "--danger-auto-approve" in buf.getvalue())


def test_gate_function_unchanged():
    check("D4 promote never auto-approved",
          qwen_agent.should_auto_approve("promote", {}) is False)
    check("D5 bash gated by default",
          qwen_agent.should_auto_approve("bash", {}) is False)
    check("D6 run_python gated by default",
          qwen_agent.should_auto_approve("run_python", {}) is False)
    check("D6b generate_image gated by default",
          qwen_agent.should_auto_approve("generate_image", {}) is False)
    check("D7 should_auto_approve stayed flag-blind",
          "danger" not in inspect.getsource(qwen_agent.should_auto_approve))
    auto = qwen_agent.AUTO_APPROVE_TOOLS
    check("D8 AUTO_APPROVE_TOOLS excludes the gated tier",
          "bash" not in auto and "run_python" not in auto
          and "write_file" not in auto and "generate_image" not in auto)


def test_flag_off_still_prompts():
    with _sandbox() as (tmp, calls):
        ns = _ns(False)

        rec = qwen_agent.dispatch(_tc("bash", {"command": "echo D9"}), 1, 1, ns, [])
        check("D9 bash denied, flag off",
              rec["outcome"] == "denied" and len(calls) == 1)

        rec = qwen_agent.dispatch(_tc("run_python", {"code": "print('D10')"}), 2, 2, ns, [])
        check("D10 run_python denied, flag off",
              rec["outcome"] == "denied" and len(calls) == 2)

        existing = os.path.join(tmp, "x.txt")
        with open(existing, "w", encoding="utf-8") as f:
            f.write("old")
        rec = qwen_agent.dispatch(
            _tc("write_file", {"path": "x.txt", "content": "new"}), 3, 3, ns, [])
        check("D11 overwriting write_file denied, flag off",
              rec["outcome"] == "denied" and len(calls) == 3)

        rec = qwen_agent.dispatch(
            _tc("write_file", {"path": "new.txt", "content": "fresh"}), 4, 4, ns, [])
        check("D12 new-file write_file still auto-approved",
              rec["outcome"] == "approved" and len(calls) == 3)

        orig_gen = qwen_agent.exec_generate_image
        qwen_agent.exec_generate_image = lambda args: "FAKE_IMAGE_RESULT"
        try:
            rec = qwen_agent.dispatch(
                _tc("generate_image", {"prompt": "a cat"}), 5, 5, ns, [])
        finally:
            qwen_agent.exec_generate_image = orig_gen
        check("D12b generate_image denied, flag off",
              rec["outcome"] == "denied" and len(calls) == 4)


def test_flag_on_bypasses_confirm():
    with _sandbox() as (tmp, calls):
        ns = _ns(True)

        rec = qwen_agent.dispatch(_tc("bash", {"command": "echo D13"}), 1, 1, ns, [])
        check("D13 bash bypassed, flag on",
              rec["outcome"] == "approved" and "D13" in rec["result"] and len(calls) == 0)

        rec = qwen_agent.dispatch(_tc("run_python", {"code": "print('D14')"}), 2, 2, ns, [])
        check("D14 run_python bypassed, flag on",
              rec["outcome"] == "approved" and "D14" in rec["result"] and len(calls) == 0)

        existing = os.path.join(tmp, "x.txt")
        with open(existing, "w", encoding="utf-8") as f:
            f.write("old")
        rec = qwen_agent.dispatch(
            _tc("write_file", {"path": "x.txt", "content": "new content"}), 3, 3, ns, [])
        with open(existing, "r", encoding="utf-8") as f:
            on_disk = f.read()
        check("D15 overwriting write_file bypassed, flag on",
              rec["outcome"] == "approved" and len(calls) == 0 and on_disk == "new content")

        orig_gen = qwen_agent.exec_generate_image
        qwen_agent.exec_generate_image = lambda args: "FAKE_IMAGE_RESULT"
        try:
            err = io.StringIO()
            with contextlib.redirect_stderr(err):
                rec = qwen_agent.dispatch(
                    _tc("generate_image", {"prompt": "a dog"}), 4, 4, ns, [])
        finally:
            qwen_agent.exec_generate_image = orig_gen
        out = err.getvalue()
        check("D16 generate_image bypassed and traced [danger-auto], flag on",
              len(calls) == 0
              and "[danger-auto] generate_image" in out
              and "[auto] generate_image" not in out)


def test_promote_is_never_bypassed():
    home = tempfile.mkdtemp(prefix="qwen-agent-daa-promote-")
    os.environ["HOME"] = home
    qwen_agent.MEMORY_ENABLED = True
    with contextlib.redirect_stderr(io.StringIO()):
        qwen_agent.memory_start("/tmp/ws")

    with _sandbox() as (tmp, calls):
        ns = _ns(True)
        rec = qwen_agent.dispatch(_tc("promote", {"text": "one"}), 1, 1, ns, [])
        check("D17 danger-auto-approve does not affect promote (denied)",
              rec["outcome"] == "denied" and len(calls) == 1)

    with _sandbox() as (tmp, calls):
        ns = _ns(True)
        orig_auto = qwen_agent.AUTO_APPROVE_TOOLS
        qwen_agent.AUTO_APPROVE_TOOLS = orig_auto + ("promote",)
        try:
            rec = qwen_agent.dispatch(_tc("promote", {"text": "two"}), 1, 1, ns, [])
            check("D18 danger-auto-approve does not affect promote (tampered tuple)",
                  rec["outcome"] == "denied" and len(calls) == 1)
        finally:
            qwen_agent.AUTO_APPROVE_TOOLS = orig_auto

    with _sandbox() as (tmp, calls):
        ns = _ns(True)
        qwen_agent._prompt_line = lambda text: (calls.append(text), "y")[1]
        rec = qwen_agent.dispatch(_tc("promote", {"text": "three"}), 1, 1, ns, [])
        check("D19 danger-auto-approve does not affect promote (prompt reached, y)",
              rec["outcome"] == "approved" and len(calls) == 1)

    check("D19b dispatch source still guards promote by name",
          'name != "promote"' in inspect.getsource(qwen_agent.dispatch))


def test_trace_labels():
    with _sandbox() as (tmp, calls):
        ns = _ns(True)
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            qwen_agent.dispatch(_tc("bash", {"command": "echo D20"}), 1, 1, ns, [])
        out = err.getvalue()
        check("D20 bash traced [danger-auto]",
              "[danger-auto] bash " in out and "[auto] bash" not in out)

    orig_search = qwen_agent.exec_search
    qwen_agent.exec_search = lambda a, t: "OK: stub"
    try:
        with _sandbox() as (tmp, calls):
            ns = _ns(True)
            err = io.StringIO()
            with contextlib.redirect_stderr(err):
                qwen_agent.dispatch(_tc("search", {"query": "q"}), 1, 1, ns, [])
            out = err.getvalue()
            check("D21 search stays [auto], flag on",
                  "[auto] search " in out and "[danger-auto]" not in out)
    finally:
        qwen_agent.exec_search = orig_search

    with _sandbox() as (tmp, calls):
        ns = _ns(True)
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            qwen_agent.dispatch(
                _tc("write_file", {"path": "brandnew.txt", "content": "hi"}), 1, 1, ns, [])
        out = err.getvalue()
        check("D22 new-file write_file stays [auto], flag on",
              "[auto] write_file" in out and "[danger-auto]" not in out)

    with _sandbox() as (tmp, calls):
        existing = os.path.join(tmp, "exist.txt")
        with open(existing, "w", encoding="utf-8") as f:
            f.write("old")
        ns = _ns(True)
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            qwen_agent.dispatch(
                _tc("write_file", {"path": "exist.txt", "content": "new"}), 1, 1, ns, [])
        out = err.getvalue()
        check("D23 overwriting write_file traced [danger-auto]",
              "[danger-auto] write_file" in out)

    orig_gen = qwen_agent.exec_generate_image
    qwen_agent.exec_generate_image = lambda args: "FAKE"
    try:
        with _sandbox() as (tmp, calls):
            ns = _ns(True)
            err = io.StringIO()
            with contextlib.redirect_stderr(err):
                qwen_agent.dispatch(_tc("generate_image", {"prompt": "sun"}), 1, 1, ns, [])
            out = err.getvalue()
            check("D23b generate_image traced [danger-auto]",
                  "[danger-auto] generate_image" in out)
    finally:
        qwen_agent.exec_generate_image = orig_gen

    orig_search = qwen_agent.exec_search
    qwen_agent.exec_search = lambda a, t: "OK: stub"
    try:
        with _sandbox() as (tmp, calls):
            ns = _ns(False)
            err = io.StringIO()
            with contextlib.redirect_stderr(err):
                qwen_agent.dispatch(_tc("search", {"query": "q"}), 1, 1, ns, [])
            out = err.getvalue()
            check("D24 search stays [auto], flag off",
                  "[auto] search " in out)
    finally:
        qwen_agent.exec_search = orig_search


def test_auto_key_covers_bash_and_run_python():
    check("D25 _auto_key bash",
          qwen_agent._auto_key("bash", {"command": "echo hello"}, {}) == "echo hello")
    check("D26 _auto_key run_python",
          qwen_agent._auto_key("run_python", {"code": "print(1)"}, {}) == "print(1)")

    key = qwen_agent._auto_key("bash", {"command": "a" * 300}, {})
    check("D27 _auto_key bash clipped",
          key.endswith("...") and len(key) == qwen_agent.TRACE_KEY_CHARS + 3)

    check("D28 _auto_key bash collapses control chars",
          qwen_agent._auto_key("bash", {"command": "a\nb"}, {}) == "a b")

    with _sandbox() as (tmp, calls):
        ns = _ns(True)
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            qwen_agent.dispatch(_tc("bash", {"command": "echo D29key"}), 1, 1, ns, [])
        out = err.getvalue()
        check("D29 end-to-end danger-auto trace line includes the key",
              "[danger-auto] bash echo D29key -> " in out)


def test_warning_and_source_guards():
    orig_oneshot = qwen_agent.ONESHOT
    qwen_agent.ONESHOT = True
    out = io.StringIO()
    err = io.StringIO()
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            qwen_agent.print_danger_auto_warning()
    finally:
        qwen_agent.ONESHOT = orig_oneshot
    check("D30 warning goes to stderr only",
          "--danger-auto-approve IS ON" in err.getvalue() and out.getvalue() == "")
    check("D31 warning mentions NOT sandboxed and promote",
          "NOT sandboxed" in err.getvalue() and "promote" in err.getvalue())

    check("D32 flag documented in HELP_TEXT and module docstring",
          "--danger-auto-approve" in qwen_agent.HELP_TEXT
          and "--danger-auto-approve" in qwen_agent.__doc__)

    check("D33 flag not forwarded to skill subprocess argv",
          "--danger-auto-approve" not in inspect.getsource(qwen_agent.exec_delegate_to_skill))


if __name__ == "__main__":
    test_flag_default_and_parse()
    test_gate_function_unchanged()
    test_flag_off_still_prompts()
    test_flag_on_bypasses_confirm()
    test_promote_is_never_bypassed()
    test_trace_labels()
    test_auto_key_covers_bash_and_run_python()
    test_warning_and_source_guards()

    print("OK %d/%d" % (TOTAL - FAILED, TOTAL))
    sys.exit(0 if FAILED == 0 else 1)
