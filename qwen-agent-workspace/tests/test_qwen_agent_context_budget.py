"""Plain-python (no pytest) offline tests for bin/qwen-agent's context budget.

Run: python3 tests/test_qwen_agent_context_budget.py
Covers the 2026-09-02 context-budget design: window discovery, the token
estimator, tool-result eviction, the pre-send budget cliff, and
finish_reason == "length" handling. Fully offline -- every server call is
monkeypatched; nothing here touches the network, a subprocess, or the model.
"""

import ast
import copy
import importlib.machinery
import importlib.util
import io
import json
import os
import sys
import tempfile
import urllib.error
import urllib.request
import contextlib

WS = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
_SCRIPT_PATH = os.path.join(WS, "bin", "qwen-agent")

_loader = importlib.machinery.SourceFileLoader("qwen_agent", _SCRIPT_PATH)
_spec = importlib.util.spec_from_loader("qwen_agent", _loader)
qwen_agent = importlib.util.module_from_spec(_spec)
sys.modules["qwen_agent"] = qwen_agent
_loader.exec_module(qwen_agent)

# Captured before the test module touches anything: proves importing the script
# runs no setup, builds no tools, and opens no socket (the __main__ guard holds).
_TOOLS_AT_IMPORT = qwen_agent.TOOLS
_WORKSPACE_AT_IMPORT = qwen_agent.WORKSPACE
_CONTEXT_WINDOW_AT_IMPORT = qwen_agent.CONTEXT_WINDOW

# The eight-tool schema the REPL uses; main() normally does this.
qwen_agent.TOOLS = qwen_agent.build_tools_for_context(None)
qwen_agent.TOOL_BY_NAME = {t["function"]["name"]: t for t in qwen_agent.TOOLS}
# Route _ui() to stderr so eviction notices do not interleave with PASS lines.
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


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

SYSTEM_MSG = qwen_agent.build_system_message("/tmp/qwen-agent-test-ws")
BLOB_LINE = "    x = compute_value(alpha, beta, gamma)  # inline note\n"


def python_blob(n_chars):
    """Deterministic n-char block of indented Python -- the worst realistic case."""
    return (BLOB_LINE * (n_chars // len(BLOB_LINE) + 1))[:n_chars]


BLOB = python_blob(4000)


def make_args(**overrides):
    ns = qwen_agent.parse_args([])
    for key, value in overrides.items():
        setattr(ns, key, value)
    return ns


def set_window(n):
    qwen_agent.CONTEXT_WINDOW = n


def tool_call_response(index, finish_reason="tool_calls"):
    return {"choices": [{"finish_reason": finish_reason, "message": {
        "content": "",
        "tool_calls": [{"id": "call_%d" % index, "type": "function", "function": {
            "name": "bash",
            "arguments": json.dumps({"command": "echo %d" % index})}}]}}]}


def text_response(text, finish_reason="stop"):
    return {"choices": [{"finish_reason": finish_reason,
                         "message": {"content": text}}]}


def make_fake_chat(script):
    """Return (fake_chat_completion, calls). `script(n, messages, include_tools)`
    receives the 1-based call number and returns the canned response dict."""
    calls = []

    def fake(base_url, messages, args_ns, include_tools=True):
        calls.append({
            "estimate": qwen_agent.estimate_tokens(messages, include_tools),
            "include_tools": include_tools,
            "messages": copy.deepcopy(messages),
        })
        return script(len(calls), messages, include_tools)

    return fake, calls


def fake_dispatch_ok(tc, i, n, args_ns, history):
    """Minimal record: run_turn reads exactly outcome, result and tool, and sets
    round and id itself."""
    return {"tool": tc["function"]["name"], "outcome": "approved", "result": BLOB}


def _dispatch_must_not_be_called(*a, **kw):
    raise AssertionError("dispatch must not be called")


# ---------------------------------------------------------------------------
# C0: import is side-effect free
# ---------------------------------------------------------------------------

def test_import_is_side_effect_free():
    try:
        check("C0 TOOLS None at import", _TOOLS_AT_IMPORT is None)
        check("C0 WORKSPACE None at import", _WORKSPACE_AT_IMPORT is None)
        check("C0 CONTEXT_WINDOW defaults",
              _CONTEXT_WINDOW_AT_IMPORT == qwen_agent.DEFAULT_CONTEXT_WINDOW == 16384)
    finally:
        qwen_agent.CONTEXT_WINDOW = qwen_agent.DEFAULT_CONTEXT_WINDOW


# ---------------------------------------------------------------------------
# C1: estimator is monotone and over-estimates
# ---------------------------------------------------------------------------

def test_estimator():
    try:
        msgs = [SYSTEM_MSG]
        msgs.append({"role": "user", "content": "hi"})
        msgs.append({"role": "tool", "tool_call_id": "call_1_1", "content": BLOB})

        check("C1 monotone",
              qwen_agent.estimate_tokens(msgs[:1], False)
              < qwen_agent.estimate_tokens(msgs[:2], False)
              < qwen_agent.estimate_tokens(msgs[:3], False))

        check("C1 4000-char python result >= 1300 tokens",
              qwen_agent.estimate_tokens([msgs[2]], False) >= 1300)

        check("C1 tools term is additive",
              qwen_agent.estimate_tokens(msgs, True) - qwen_agent.estimate_tokens(msgs, False)
              == len(json.dumps(qwen_agent.TOOLS)) // 3)

        orig_tools = qwen_agent.TOOLS
        qwen_agent.TOOLS = None
        try:
            check("C1 tools term is zero when TOOLS is None",
                  qwen_agent.estimate_tokens(msgs, True) == qwen_agent.estimate_tokens(msgs, False))
        finally:
            qwen_agent.TOOLS = orig_tools

        check("C1 deterministic",
              qwen_agent.estimate_tokens(msgs, True) == qwen_agent.estimate_tokens(msgs, True))
    finally:
        qwen_agent.CONTEXT_WINDOW = qwen_agent.DEFAULT_CONTEXT_WINDOW


# ---------------------------------------------------------------------------
# C2: replay -- 12 rounds of 4000-char results never exceed the budget
# ---------------------------------------------------------------------------

def test_replay_eviction():
    set_window(16384)
    args = make_args(max_tokens=1536, max_rounds=12, think=False)
    messages = [copy.deepcopy(SYSTEM_MSG), {"role": "user", "content": "analyse the repo"}]
    before = copy.deepcopy(messages[:2])

    def script(n, msgs, include_tools):
        if not include_tools:
            return text_response("done")
        return tool_call_response(n)

    fake_chat, calls = make_fake_chat(script)
    orig_chat = qwen_agent.chat_completion
    orig_dispatch = qwen_agent.dispatch
    try:
        qwen_agent.chat_completion = fake_chat
        qwen_agent.dispatch = fake_dispatch_ok

        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            result = qwen_agent.run_turn(messages, args, 1)

        budget = qwen_agent.context_budget(args)
        check("C2 status is max_rounds", result["status"] == "max_rounds")
        check("C2 13 chat calls", len(calls) == 13, "got %d" % len(calls))
        check("C2 every call within budget",
              all(c["estimate"] <= budget for c in calls))

        evicted = any(m.get("role") == "tool"
                      and (m.get("content") or "").startswith("[result evicted")
                      for m in messages)
        check("C2 eviction happened", evicted)

        newest_intact = True
        for c in calls:
            tool_msgs = [m for m in c["messages"] if m.get("role") == "tool"]
            if tool_msgs and tool_msgs[-1].get("content") != BLOB:
                newest_intact = False
                break
        check("C2 newest tool result never evicted", newest_intact)

        final_tool_msgs = [m for m in messages if m.get("role") == "tool"]
        check("C2 final newest tool result intact",
              bool(final_tool_msgs) and final_tool_msgs[-1].get("content") == BLOB)

        named = any(m.get("content") == "[result evicted to free context: 4000 chars from bash]"
                    for m in messages)
        check("C2 stub names the tool and the size", named)

        check("C2 system message untouched", messages[0] == before[0])
        check("C2 user message untouched", messages[1] == before[1])

        assistant_evicted = any(
            m.get("role") == "assistant"
            and (m.get("content") or "").startswith("[result evicted")
            for m in messages)
        check("C2 no assistant message evicted", not assistant_evicted)

        text = stderr.getvalue()
        check("C2 eviction notice printed",
              "[context] evicted" in text and "16384-token window" in text)
    finally:
        qwen_agent.chat_completion = orig_chat
        qwen_agent.dispatch = orig_dispatch
        qwen_agent.CONTEXT_WINDOW = qwen_agent.DEFAULT_CONTEXT_WINDOW


# ---------------------------------------------------------------------------
# C3: the cliff -- a window too small for the tool schema
# ---------------------------------------------------------------------------

def test_cliff():
    set_window(4096)
    args = make_args(max_tokens=1536, max_rounds=10)
    messages = [copy.deepcopy(SYSTEM_MSG), {"role": "user", "content": "hello"}]

    def script(n, msgs, include_tools):
        return text_response("summary")

    fake_chat, calls = make_fake_chat(script)
    orig_chat = qwen_agent.chat_completion
    orig_dispatch = qwen_agent.dispatch
    try:
        qwen_agent.chat_completion = fake_chat
        qwen_agent.dispatch = _dispatch_must_not_be_called

        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            result = qwen_agent.run_turn(messages, args, 1)

        check("C3 status is context_budget", result["status"] == "context_budget")
        check("C3 error names the budget",
              result["error"].startswith("context budget exhausted:")
              and "4096-token window" in result["error"])
        check("C3 answer came from the forced summary", result["answer"] == "summary")
        check("C3 exactly one chat call", len(calls) == 1, "got %d" % len(calls))
        check("C3 that call had tools disabled", calls[0]["include_tools"] is False)
        check("C3 no over-budget call was sent",
              all(c["estimate"] <= qwen_agent.context_budget(args) for c in calls))
    finally:
        qwen_agent.chat_completion = orig_chat
        qwen_agent.dispatch = orig_dispatch
        qwen_agent.CONTEXT_WINDOW = qwen_agent.DEFAULT_CONTEXT_WINDOW


# ---------------------------------------------------------------------------
# C4: finish_reason == "length" with tool calls
# ---------------------------------------------------------------------------

def test_truncated_with_tool_calls():
    set_window(16384)
    args = make_args(max_tokens=1536, max_rounds=5)
    messages = [copy.deepcopy(SYSTEM_MSG), {"role": "user", "content": "do something"}]

    def script(n, msgs, include_tools):
        if n == 1:
            resp = tool_call_response(1, finish_reason="length")
            resp["choices"][0]["message"]["content"] = "I will run "
            return resp
        return text_response("recovered")

    fake_chat, calls = make_fake_chat(script)
    orig_chat = qwen_agent.chat_completion
    orig_dispatch = qwen_agent.dispatch
    try:
        qwen_agent.chat_completion = fake_chat
        qwen_agent.dispatch = _dispatch_must_not_be_called

        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            result = qwen_agent.run_turn(messages, args, 1)

        check("C4 status is truncated", result["status"] == "truncated")
        check("C4 error names max_tokens",
              result["error"] ==
              "model output was cut off at max_tokens (1536); tool calls discarded")
        check("C4 forced summary ran once",
              len(calls) == 2 and calls[1]["include_tools"] is False)
        check("C4 answer is the summary", result["answer"] == "recovered")

        check("C4 no tool message appended",
              not any(m.get("role") == "tool" for m in messages))

        assistant_msgs = [m for m in messages if m.get("role") == "assistant"]
        first_assistant = assistant_msgs[0] if assistant_msgs else {}
        check("C4 echo has no tool_calls",
              "tool_calls" not in first_assistant
              and first_assistant.get("content") == "I will run ")
    finally:
        qwen_agent.chat_completion = orig_chat
        qwen_agent.dispatch = orig_dispatch
        qwen_agent.CONTEXT_WINDOW = qwen_agent.DEFAULT_CONTEXT_WINDOW


# ---------------------------------------------------------------------------
# C5: finish_reason == "length" without tool calls
# ---------------------------------------------------------------------------

def test_truncated_without_tool_calls():
    set_window(16384)
    args = make_args(max_tokens=1536, max_rounds=5)
    messages = [copy.deepcopy(SYSTEM_MSG), {"role": "user", "content": "do something"}]

    def script(n, msgs, include_tools):
        return text_response("partial answer", finish_reason="length")

    fake_chat, calls = make_fake_chat(script)
    orig_chat = qwen_agent.chat_completion
    try:
        qwen_agent.chat_completion = fake_chat

        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            result = qwen_agent.run_turn(messages, args, 1)

        check("C5 status is ok", result["status"] == "ok")
        check("C5 answer preserved", result["answer"] == "partial answer")
        check("C5 one chat call", len(calls) == 1, "got %d" % len(calls))
        check("C5 stderr note",
              "[note: answer was cut off at max_tokens=1536]" in stderr.getvalue())
    finally:
        qwen_agent.chat_completion = orig_chat
        qwen_agent.CONTEXT_WINDOW = qwen_agent.DEFAULT_CONTEXT_WINDOW


# ---------------------------------------------------------------------------
# C6: context-window discovery
# ---------------------------------------------------------------------------

class _FakeResponse(object):
    def __init__(self, payload):
        self._payload = payload.encode("utf-8")

    def read(self):
        return self._payload

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_window_discovery():
    orig_urlopen = urllib.request.urlopen
    try:
        payload = {"data": [
            {"id": "other", "context_length": 4096},
            {"id": "qwen38-6bit", "context_length": 16384,
             "max_context_length": 16384, "max_model_len": 16384},
        ]}
        urllib.request.urlopen = lambda *a, **kw: _FakeResponse(json.dumps(payload))
        check("C6 exact id match",
              qwen_agent.discover_context_window("http://x/v1", "qwen38-6bit", None) == 16384)

        payload = {"data": [{"id": "other", "context_length": 8192}]}
        urllib.request.urlopen = lambda *a, **kw: _FakeResponse(json.dumps(payload))
        check("C6 falls back to the first entry",
              qwen_agent.discover_context_window("http://x/v1", "qwen38-6bit", None) == 8192)

        payload = {"data": [{"id": "qwen38-6bit", "max_model_len": 32768}]}
        urllib.request.urlopen = lambda *a, **kw: _FakeResponse(json.dumps(payload))
        check("C6 falls back through the key list",
              qwen_agent.discover_context_window("http://x/v1", "qwen38-6bit", None) == 32768)

        payload = {"data": [{"id": "qwen38-6bit"}]}
        urllib.request.urlopen = lambda *a, **kw: _FakeResponse(json.dumps(payload))
        check("C6 no field -> default",
              qwen_agent.discover_context_window("http://x/v1", "qwen38-6bit", None) == 16384)

        def raise_urlerror(*a, **kw):
            raise urllib.error.URLError("refused")
        urllib.request.urlopen = raise_urlerror
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            value = qwen_agent.discover_context_window("http://x/v1", "qwen38-6bit", None)
        check("C6 urlopen failure -> default, no exception",
              value == 16384 and "could not read the context window" in stderr.getvalue())

        payload = {"data": []}
        urllib.request.urlopen = lambda *a, **kw: _FakeResponse(json.dumps(payload))
        check("C6 empty data -> default",
              qwen_agent.discover_context_window("http://x/v1", "qwen38-6bit", None) == 16384)
    finally:
        urllib.request.urlopen = orig_urlopen
        qwen_agent.CONTEXT_WINDOW = qwen_agent.DEFAULT_CONTEXT_WINDOW


# ---------------------------------------------------------------------------
# C7: --context-window overrides discovery; discovery fills in otherwise
# ---------------------------------------------------------------------------

def test_setup_window_resolution():
    orig_preflight = qwen_agent.preflight
    orig_searxng = qwen_agent.searxng_probe
    orig_discover = qwen_agent.discover_context_window
    orig_workspace = qwen_agent.WORKSPACE
    orig_cw = qwen_agent.CONTEXT_WINDOW
    tmpdir = tempfile.mkdtemp()
    try:
        qwen_agent.preflight = lambda *a, **kw: None
        qwen_agent.searxng_probe = lambda *a, **kw: None

        check("C7 flag parses",
              qwen_agent.parse_args(["--context-window", "8192"]).context_window == 8192)
        check("C7 default is None",
              qwen_agent.parse_args([]).context_window is None)

        def _discover_must_not_be_called(*a, **kw):
            raise AssertionError("discover_context_window must not be called")
        qwen_agent.discover_context_window = _discover_must_not_be_called
        qwen_agent.setup(make_args(context_window=8192, workspace=tmpdir))
        check("C7 flag wins", qwen_agent.CONTEXT_WINDOW == 8192)

        qwen_agent.discover_context_window = lambda *a: 4321
        qwen_agent.setup(make_args(context_window=None, workspace=tmpdir))
        check("C7 discovery used when unset", qwen_agent.CONTEXT_WINDOW == 4321)
    finally:
        qwen_agent.preflight = orig_preflight
        qwen_agent.searxng_probe = orig_searxng
        qwen_agent.discover_context_window = orig_discover
        qwen_agent.WORKSPACE = orig_workspace
        qwen_agent.CONTEXT_WINDOW = orig_cw


# ---------------------------------------------------------------------------
# C8: source guards
# ---------------------------------------------------------------------------

def test_source_guards():
    with open(_SCRIPT_PATH) as f:
        src = f.read()

    check("C8 no stale 8192-token string", "8192-token" not in src)

    check("C8 both overflow messages parameterised",
          src.count("%d-token window. Use /resume to continue from this session's "
                    "checkpoints, or /reset to start clean.]") == 2)

    import_names = set()
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                import_names.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            import_names.add(node.module)
    expected = {
        "argparse", "ast", "base64", "datetime", "html.parser", "json", "operator", "os",
        "re", "signal", "subprocess", "sys", "time", "urllib.error",
        "urllib.parse", "urllib.request", "uuid", "pathlib",
    }
    check("C8 no new imports", import_names == expected,
          "got %r" % (import_names,))

    check("C8 context-window flag forwarded to children",
          '"--context-window", str(CONTEXT_WINDOW),' in src)

    check("C8 RESULT_CHAR_LIMIT unchanged", "RESULT_CHAR_LIMIT = 4000" in src)


# ---------------------------------------------------------------------------
# C9: multi-turn REPL eviction -- earlier turns' tool results stay eligible
# ---------------------------------------------------------------------------

def test_repl_multi_turn_eviction():
    set_window(16384)
    args = make_args(max_tokens=1536, max_rounds=5, think=False)
    messages = [copy.deepcopy(SYSTEM_MSG)]

    def script(n, msgs, include_tools):
        if not include_tools:
            return text_response("done")
        return tool_call_response(n)

    fake_chat, calls = make_fake_chat(script)
    orig_chat = qwen_agent.chat_completion
    orig_dispatch = qwen_agent.dispatch
    try:
        qwen_agent.chat_completion = fake_chat
        qwen_agent.dispatch = fake_dispatch_ok

        results = []
        evicted_counts = []
        for turn in range(1, 7):
            snapshot = len(messages)
            messages.append({"role": "user", "content": "turn %d" % turn})
            stderr = io.StringIO()
            with contextlib.redirect_stderr(stderr):
                result = qwen_agent.run_turn(messages, args, snapshot)
            results.append(result)
            evicted_counts.append(sum(
                1 for m in messages
                if m.get("role") == "tool"
                and (m.get("content") or "").startswith("[result evicted")))

        check("C9 no turn ends context_budget",
              all(r["status"] == "max_rounds" for r in results),
              "got %r" % ([r["status"] for r in results],))

        check("C9 every turn ran all tool rounds",
              all(r["rounds"] == 6 for r in results),
              "got %r" % ([r["rounds"] for r in results],))

        check("C9 eviction count increases once over budget",
              all(evicted_counts[i] <= evicted_counts[i + 1]
                  for i in range(len(evicted_counts) - 1))
              and evicted_counts[-1] >= 10,
              "got %r" % (evicted_counts,))

        check("C9 every call within budget",
              all(c["estimate"] <= qwen_agent.context_budget(args) for c in calls))

        check("C9 system message intact", messages[0] == SYSTEM_MSG)

        final_tool_msgs = [m for m in messages if m.get("role") == "tool"]
        check("C9 newest tool result intact",
              bool(final_tool_msgs) and final_tool_msgs[-1].get("content") == BLOB)
    finally:
        qwen_agent.chat_completion = orig_chat
        qwen_agent.dispatch = orig_dispatch
        qwen_agent.CONTEXT_WINDOW = qwen_agent.DEFAULT_CONTEXT_WINDOW


# ---------------------------------------------------------------------------
# C10: forced summary itself cannot fit the budget -- no chat call at all
# ---------------------------------------------------------------------------

def test_forced_summary_exhaustion():
    set_window(2600)
    args = make_args(max_tokens=1536, max_rounds=3)
    messages = [copy.deepcopy(SYSTEM_MSG), {"role": "user", "content": "hello"}]

    chat_calls = []

    def fake_chat_must_not_be_called(*a, **kw):
        chat_calls.append(1)
        raise AssertionError("chat_completion must not be called")

    orig_chat = qwen_agent.chat_completion
    orig_dispatch = qwen_agent.dispatch
    try:
        qwen_agent.chat_completion = fake_chat_must_not_be_called
        qwen_agent.dispatch = _dispatch_must_not_be_called

        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            result = qwen_agent.run_turn(messages, args, 1)

        check("C10 status is context_budget", result["status"] == "context_budget")
        check("C10 answer is None", result["answer"] is None)
        check("C10 no chat call made", len(chat_calls) == 0)
        check("C10 forced summary prompt left in messages",
              any(m.get("role") == "user"
                  and m.get("content") == qwen_agent.FORCED_SUMMARY_PROMPT
                  for m in messages))
        check("C10 stderr names exhaustion",
              "context budget exhausted" in stderr.getvalue())
    finally:
        qwen_agent.chat_completion = orig_chat
        qwen_agent.dispatch = orig_dispatch
        qwen_agent.CONTEXT_WINDOW = qwen_agent.DEFAULT_CONTEXT_WINDOW


# ---------------------------------------------------------------------------
# C11: a transport-failure rollback keeps evictions already made
# ---------------------------------------------------------------------------

def test_rollback_keeps_evictions():
    set_window(16384)
    args = make_args(max_tokens=1536, max_rounds=5, think=False)
    messages = [copy.deepcopy(SYSTEM_MSG)]

    def script(n, msgs, include_tools):
        if not include_tools:
            return text_response("done")
        return tool_call_response(n)

    fake_chat, calls = make_fake_chat(script)
    orig_chat = qwen_agent.chat_completion
    orig_dispatch = qwen_agent.dispatch
    try:
        qwen_agent.chat_completion = fake_chat
        qwen_agent.dispatch = fake_dispatch_ok

        for turn in range(1, 3):
            snapshot = len(messages)
            messages.append({"role": "user", "content": "turn %d" % turn})
            stderr = io.StringIO()
            with contextlib.redirect_stderr(stderr):
                qwen_agent.run_turn(messages, args, snapshot)

        def evicted_count():
            return sum(
                1 for m in messages
                if m.get("role") == "tool"
                and (m.get("content") or "").startswith("[result evicted"))

        def evicted_indices():
            return set(
                i for i, m in enumerate(messages)
                if m.get("role") == "tool"
                and (m.get("content") or "").startswith("[result evicted"))

        stubs_before = evicted_indices()
        check("C11 precondition: evictions occurred", len(stubs_before) > 0)

        def fake_chat_fails(base_url, msgs, args_ns, include_tools=True):
            raise urllib.error.URLError("refused")

        qwen_agent.chat_completion = fake_chat_fails

        snapshot = len(messages)
        messages.append({"role": "user", "content": "turn 3"})
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            result = qwen_agent.run_turn(messages, args, snapshot)

        check("C11 status is network_error", result["status"] == "network_error")
        check("C11 transcript rolled back to snapshot", len(messages) == snapshot)
        # The failed turn may legitimately evict MORE before the request is sent
        # (tools re-enabled after a tools-off forced summary raises the estimate),
        # so the invariant is that no pre-existing stub is ever un-stubbed.
        check("C11 evictions survive rollback", stubs_before <= evicted_indices())
    finally:
        qwen_agent.chat_completion = orig_chat
        qwen_agent.dispatch = orig_dispatch
        qwen_agent.CONTEXT_WINDOW = qwen_agent.DEFAULT_CONTEXT_WINDOW


# ---------------------------------------------------------------------------
# C12: a result no longer than its own stub is never evicted
# ---------------------------------------------------------------------------

def test_short_results_not_evicted():
    messages = [copy.deepcopy(SYSTEM_MSG), {"role": "user", "content": "hi"}]
    for i in range(30):
        call_id = "call_%d" % i
        messages.append({
            "role": "assistant",
            "content": "",
            "tool_calls": [{"id": call_id, "type": "function",
                            "function": {"name": "bash", "arguments": "{}"}}],
        })
        messages.append({"role": "tool", "tool_call_id": call_id, "content": "ok"})

    set_window(1000)
    args = make_args(max_tokens=100)
    try:
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            evicted = qwen_agent.evict_to_budget(messages, args, len(messages))

        check("C12 returns zero", evicted == 0)
        check("C12 no short result stubbed",
              not any(m.get("role") == "tool"
                      and (m.get("content") or "").startswith("[result evicted")
                      for m in messages))
        check("C12 no notice printed", "[context] evicted" not in stderr.getvalue())
    finally:
        qwen_agent.CONTEXT_WINDOW = qwen_agent.DEFAULT_CONTEXT_WINDOW


if __name__ == "__main__":
    test_import_is_side_effect_free()
    test_estimator()
    test_replay_eviction()
    test_cliff()
    test_truncated_with_tool_calls()
    test_truncated_without_tool_calls()
    test_repl_multi_turn_eviction()
    test_forced_summary_exhaustion()
    test_rollback_keeps_evictions()
    test_short_results_not_evicted()
    test_window_discovery()
    test_setup_window_resolution()
    test_source_guards()

    print("OK %d/%d" % (TOTAL - FAILED, TOTAL))
    sys.exit(0 if FAILED == 0 else 1)
