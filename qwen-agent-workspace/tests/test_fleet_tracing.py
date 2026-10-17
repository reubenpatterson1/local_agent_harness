"""Fleet tracing tests for bin/qwen-agentd and the real harness (tracing spec Section 6.5).

Run from the workspace root: python3 -m pytest tests/test_fleet_tracing.py -v
Loopback only. Every daemon runs with --timing-scale 0.1, explicit beacon targets and
HOME=<tmp dir>; the autouse fixture SIGKILLs every process group a test started and
stops every stub server. Every harness run gets QWEN_AGENT_DAEMON_URL explicitly, so no
test contacts a qwen-agentd running on this machine or a real model server.
"""

import base64
import http.server
import json
import os
import re
import stat
import subprocess
import sys
import threading
import time

import pytest

WS = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
sys.path.insert(0, WS)
import fleet_lib  # noqa: E402
import fleet_testutil as ftu  # noqa: E402


@pytest.fixture(autouse=True)
def _reap_processes():
    yield
    ftu.kill_all()


T = "4bf92f3577b34da6a3ce929d0e0e4736"
P = "53995c3f42cd8ad8"


def _span(kind="tool", trace_id=T, parent=P, name="calculate", status="ok", attrs=None, start=None):
    """A valid /spans-form record (no "agent") with a fresh span ID."""
    attrs = attrs if attrs is not None else {
        "turn": {"rounds": 1, "tool_calls": 0},
        "model": {"call": 1, "tools": True, "prompt_tokens": 3, "completion_tokens": 4,
                  "finish_reason": "stop", "http": None},
        "tool": {"round": 1, "decision": "approved", "key": "2+2", "outcome": "OK: 4", "error": False},
    }[kind]
    start = round(time.time(), 3) if start is None else start
    return fleet_lib.make_record(trace_id, fleet_lib.new_span_id(), parent, None, kind, name, start,
                                 time.monotonic(), status, attrs)


def _post_span(port, record, headers=None):
    """(status, body bytes) of loopback POST /spans with a JSON body."""
    body = record if isinstance(record, bytes) else fleet_lib.canonical_json(record)
    status, _h, raw = ftu._request(port, "POST", "/spans", body,
                                   headers or {"Content-Type": "application/json"}, timeout=10)
    return status, raw


def _alpha(tmp_path, **kwargs):
    """One running daemon 'alpha' (no skills, no beacons) -> the Fleet."""
    return ftu.Fleet(tmp_path, names=("alpha",), **kwargs).start()


# --- POST /spans (TR9, TR21, TR22) -----------------------------------------------------

def test_trt46_post_spans_validation_cap_and_store(tmp_path):
    fleet = _alpha(tmp_path)
    port, home = fleet.ports["alpha"], fleet.homes["alpha"]
    assert ftu.raw_request(port, "POST", "/spans", {"Content-Type": "application/json",
                                                    "Content-Length": "8193"}) == (413, b"")
    assert _post_span(port, b"not json") == (400, b'{"error":"bad span: record"}')
    run = fleet_lib.make_record(T, fleet_lib.new_span_id(), P, None, "run", "researcher", 1760000000.0, 0.0,
                                "ok", {"skill": "researcher", "request_id": "r1", "http": 200, "images": 0,
                                       "image_bytes": 0}, now=1.0)
    assert _post_span(port, run) == (400, b'{"error":"bad span: kind"}')
    assert _post_span(port, dict(_span(), task="secret")) == (400, b'{"error":"bad span: keys"}')
    assert _post_span(port, dict(_span(), agent="alpha")) == (400, b'{"error":"bad span: keys"}')
    assert ftu.read_records(home, "alpha") == []
    good = _span()
    assert _post_span(port, good) == (200, b'{"ok":true}')
    assert ftu.read_records(home, "alpha") == [dict(good, agent="alpha")]
    path = os.path.join(ftu.daemon_log_dir(home, "alpha"), "trace.jsonl")
    assert ftu.trace_files(home, "alpha") == [path]
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o600
    assert "trace" not in fleet.daemons["alpha"].log()


def test_tracing_focus_1_non_ascii_tool_keys_round_trip(tmp_path):
    """Review Focus 1: a search query in Japanese with an emoji, and an error line made of
    emoji up to the 256-character limit. Expected: accepted (the escaped body stays under
    8192 bytes), stored exactly, and rendered unchanged in the tree."""
    fleet = _alpha(tmp_path)
    key = "東京 ラーメン \U0001f35c near Shibuya"
    outcome = "\U0001f35c" * 256
    rec = _span(attrs={"round": 1, "decision": "approved", "key": key, "outcome": outcome, "error": False},
                name="search")
    assert len(fleet_lib.canonical_json(rec)) < fleet_lib.TRACE_SPAN_MAX_BYTES
    assert _post_span(fleet.ports["alpha"], rec) == (200, b'{"ok":true}')
    stored = ftu.read_records(fleet.homes["alpha"], "alpha")
    assert [r["attrs"]["key"] for r in stored] == [key] and stored[0]["attrs"]["outcome"] == outcome
    result = {"schema": fleet_lib.TRACE_SCHEMA, "trace_id": T, "records": stored, "missing": [], "truncated": []}
    lines = fleet_lib.render_trace(result, localtime=time.gmtime)
    assert lines[1] == "… span %s on alpha (not retrieved)" % P
    assert lines[2].startswith("  tool search  %s  " % key) and lines[2].endswith("-> %s  @alpha" % outcome)


# --- signed GET /trace/<id> (TR26) ---------------------------------------------------------

def _signed_get(port, path, key=ftu.TEST_KEY, nonce=None):
    """(status, headers, body, request headers) of a GET signed with key."""
    nonce = nonce or os.urandom(16).hex()
    headers = fleet_lib.sign_request(key, "GET", path, b"", int(time.time()), nonce)
    status, resp_headers, raw = ftu._request(port, "GET", path, None, dict(headers), timeout=10)
    return status, resp_headers, raw, headers


def test_trt44_signed_peer_trace_endpoint(tmp_path):
    fleet = ftu.Fleet(tmp_path, names=("bravo",)).start()
    port = fleet.ports["bravo"]
    mine = [_span("model", name="bravo-model"), _span()]
    other = _span(trace_id="1" * 32)
    for rec in mine + [other]:
        assert _post_span(port, rec)[0] == 200
    before = fleet.daemons["bravo"].log()
    path = "/trace/" + T
    assert ftu._request(port, "GET", path)[0::2] == (401, b"")
    status, headers, raw, sent = _signed_get(port, path)
    assert status == 200 and ftu.response_ok(ftu.TEST_KEY, 200, "GET", path, sent["X-Fleet-Nonce"], headers, raw)
    assert json.loads(raw) == {"agent": "bravo", "trace_id": T, "records": [dict(r, agent="bravo") for r in mine],
                               "truncated": False}
    assert ftu._request(port, "GET", path, None, dict(sent))[0::2] == (401, b"")
    assert _signed_get(port, path, key=bytes.fromhex(ftu.OTHER_TOKEN))[0::2] == (401, b"")
    for bad in ("/trace/xyz", "/trace/" + T + "?x=1", "/trace/" + T.upper()):
        status, headers, raw, sent = _signed_get(port, bad)
        assert (status, raw) == (400, b'{"error":"bad trace id"}'), bad
        assert ftu.response_ok(ftu.TEST_KEY, 400, "GET", bad, sent["X-Fleet-Nonce"], headers, raw)
    status, _h, raw, _s = _signed_get(port, "/trace/" + "2" * 32)
    assert (status, json.loads(raw)) == (200, {"agent": "bravo", "trace_id": "2" * 32, "records": [],
                                               "truncated": False})
    assert fleet.daemons["bravo"].log() == before


# --- loopback GET /trace?id= (fan-out) and GET /traces/recent (TR27, TR28) --------------

def _append_lines(home, host_id, records):
    """Append stored-form records to an agent's trace.jsonl the way its daemon would."""
    path = os.path.join(ftu.daemon_log_dir(home, host_id), "trace.jsonl")
    with open(path, "ab") as f:
        for rec in records:
            f.write(fleet_lib.canonical_json(rec) + b"\n")


def _delegate_record(agent, target, parent, start):
    return fleet_lib.make_record(T, fleet_lib.new_span_id(), parent, agent, "delegate", "researcher", start,
                                 0.0, "unreachable", {"skill": "researcher", "target": target, "request_id": "r1",
                                                      "http": None, "images": 0}, now=0.5)


def test_tr27_fanout_two_rounds_and_missing_reasons(tmp_path):
    fleet = ftu.Fleet(tmp_path, names=("alpha", "bravo"), extra_hosts={"charlie": {
        "port": ftu.free_port(), "model_server": {"type": "vllm", "url": "http://127.0.0.1:9/v1"},
        "model": "charlie-model", "skills": ["analyst"]}}).start()
    ftu.wait_until(lambda: fleet.peer_ids("alpha") == ["bravo"], 4.5)
    alpha, bravo = fleet.ports["alpha"], fleet.ports["bravo"]
    turn = _span("turn", parent=None, name="repl")
    tool = _span(parent=turn["span_id"], name="delegate_to_skill")
    for rec in (turn, tool):
        assert _post_span(alpha, rec)[0] == 200
    now = round(time.time(), 3)
    to_charlie = _delegate_record("alpha", "charlie", tool["span_id"], now)
    to_delta = _delegate_record("alpha", "delta", tool["span_id"], now + 0.001)
    _append_lines(fleet.homes["alpha"], "alpha", [to_charlie, to_delta])
    peer = _span("model", parent=to_charlie["span_id"], name="bravo-model")
    assert _post_span(bravo, peer)[0] == 200
    started = time.monotonic()
    status, result = ftu.trace(alpha, T)
    assert time.monotonic() - started < 3
    assert status == 200 and fleet_lib.valid_trace_result(result, T)
    expected = [dict(turn, agent="alpha"), dict(tool, agent="alpha"), to_charlie, to_delta, dict(peer, agent="bravo")]
    assert result["records"] == fleet_lib.merge_records(expected)
    assert result["missing"] == [{"agent": "charlie", "reason": "unreachable (connection refused)"},
                                 {"agent": "delta", "reason": "not in the registry"}]
    assert result["truncated"] == []
    assert ftu.trace(alpha, "1" * 32) == (200, {"schema": "qwen-agentd.trace.v1", "trace_id": "1" * 32,
                                                "records": [], "missing": [], "truncated": []})
    status, listed = ftu.recent(alpha)
    assert status == 200 and fleet_lib.valid_recent_result(listed)
    assert listed["agent"] == "alpha" and [t["trace_id"] for t in listed["traces"]] == [T]
    assert listed["traces"][0]["spans"] == 4
    assert listed["traces"][0]["delegated"] == ["researcher@charlie", "researcher@delta"]
    assert ftu._request(alpha, "GET", "/traces/recent")[0] == 200
    assert ftu.recent(bravo) == (200, {"schema": "qwen-agentd.recent.v1", "agent": "bravo", "traces": []})


def test_trt45_query_endpoints_refuse_browsers_and_bad_queries(tmp_path):
    fleet = _alpha(tmp_path)
    port = fleet.ports["alpha"]
    before = fleet.daemons["alpha"].log()
    body = fleet_lib.canonical_json(_span())
    requests = (("POST", "/spans", body), ("GET", "/trace?id=" + T, None), ("GET", "/traces/recent", None))
    for method, path, payload in requests:
        json_type = {"Content-Type": "application/json"} if method == "POST" else {}
        for headers in (dict(json_type, Host="evil.example:%d" % port),
                        dict(json_type, Origin="http://evil.example")):
            assert ftu._request(port, method, path, payload, headers)[0::2] == (403, b""), (path, headers)
    assert ftu._request(port, "POST", "/spans", body, {"Content-Type": "text/plain"})[0::2] == (403, b"")
    if sys.platform.startswith("linux"):
        for method, path, payload in requests:
            headers = {"Content-Length": str(len(payload or b"")), "Content-Type": "application/json"}
            assert ftu.raw_request(port, method, path, headers, payload or b"",
                                   source=("127.0.0.2", 0)) == (403, b"")
    assert ftu._request(port, "GET", "/trace?id=xyz")[0::2] == (400, b'{"error":"bad trace id"}')
    assert ftu._request(port, "GET", "/trace")[0::2] == (400, b'{"error":"bad trace id"}')
    for n in ("101", "0", "abc", "", "1000"):
        assert ftu._request(port, "GET", "/traces/recent?n=" + n)[0::2] == (400, b'{"error":"bad n"}'), n
    assert ftu.read_records(fleet.homes["alpha"], "alpha") == []
    assert fleet.daemons["alpha"].log() == before


def test_tr26_to_tr28_unreadable_store_answers_500(tmp_path):
    fleet = ftu.Fleet(tmp_path, names=("alpha",))
    os.makedirs(os.path.join(ftu.daemon_log_dir(fleet.homes["alpha"], "alpha"), "trace.jsonl"))
    fleet.start()
    port = fleet.ports["alpha"]
    status, _h, raw, _s = _signed_get(port, "/trace/" + T)
    assert (status, raw) == (500, b'{"error":"trace store unreadable: IsADirectoryError"}')
    assert ftu.trace(port, T) == (500, {"error": "trace store unreadable: IsADirectoryError"})
    assert ftu.recent(port) == (500, {"error": "trace store unreadable: IsADirectoryError"})
    assert _post_span(port, _span()) == (200, b'{"ok":true}')
    assert _post_span(port, _span()) == (200, b'{"ok":true}')
    log = fleet.daemons["alpha"].log()
    assert log.count("trace: cannot write ") == 1
    assert " WARNING " in log and "trace: cannot write %s: IsADirectoryError\n" % os.path.join(
        ftu.daemon_log_dir(fleet.homes["alpha"], "alpha"), "trace.jsonl") in log


def test_tracing_focus_4_traces_survive_a_daemon_restart(tmp_path):
    """Review Focus 4: every self-update restarts the daemon. Expected: a trace recorded
    before the restart is still listed by --recent and returned by GET /trace?id= after it."""
    fleet = _alpha(tmp_path)
    turn = _span("turn", parent=None, name="repl")
    assert _post_span(fleet.ports["alpha"], turn)[0] == 200
    fleet.daemons["alpha"].kill()
    ftu.start_daemon(fleet.homes["alpha"], "alpha", fleet.registry, fleet.beacon_ports["alpha"], "none")
    status, result = ftu.trace(fleet.ports["alpha"], T)
    assert status == 200 and result["records"] == [dict(turn, agent="alpha")]
    status, listed = ftu.recent(fleet.ports["alpha"], 1)
    assert status == 200 and [t["trace_id"] for t in listed["traces"]] == [T]


# --- qwen-agentd trace (TR29) ---------------------------------------------------------------

class _OldDaemon(object):
    """A loopback server that answers every request 401 with an empty body, as a daemon
    without tracing answers an unsigned GET to an unknown route (F44)."""

    def __init__(self):
        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                self.send_response(401)
                self.send_header("Content-Length", "0")
                self.end_headers()

        self.httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.port = self.httpd.server_address[1]
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


def test_trt41a_trace_cli_on_one_agent(tmp_path):
    fleet = _alpha(tmp_path)
    port, home = fleet.ports["alpha"], fleet.homes["alpha"]
    older = _span("turn", trace_id="2" * 32, parent=None, name="oneshot", start=round(time.time(), 3) - 60)
    turn = _span("turn", parent=None, name="repl")
    model = _span("model", parent=turn["span_id"], name="alpha-model")
    for rec in (older, turn, model):
        assert _post_span(port, rec)[0] == 200
    proc = ftu.trace_cli(home, ["--port", str(port), T])
    assert (proc.returncode, proc.stderr) == (0, "")
    expected = fleet_lib.render_trace(ftu.trace(port, T)[1])
    assert proc.stdout == "\n".join(expected) + "\n"
    assert proc.stdout.startswith("trace 4bf92f3577b3  ") and "  agents: alpha  spans: 2\n" in proc.stdout
    assert proc.stdout.splitlines()[2] == "  model alpha-model  %s  ok  3→4 tok  stop  @alpha" % (
        fleet_lib.fmt_ms(model["dur_ms"]))
    proc = ftu.trace_cli(home, ["--port", str(port), "--json", T])
    assert proc.returncode == 0 and json.loads(proc.stdout) == ftu.trace(port, T)[1]
    assert proc.stdout == json.dumps(json.loads(proc.stdout), indent=2, sort_keys=True) + "\n"
    proc = ftu.trace_cli(home, ["--port", str(port), "--recent"])
    lines = proc.stdout.splitlines()
    assert proc.returncode == 0 and len(lines) == 3
    assert lines[0] == "time                 trace id                               dur  status        spans  delegated"
    assert lines[1].split()[2] == T and lines[2].split()[2] == "2" * 32
    assert lines[1].endswith("  2  -") and lines[2].endswith("  1  -")
    proc = ftu.trace_cli(home, ["--port", str(port), "--recent", "1"])
    assert proc.returncode == 0 and proc.stdout.splitlines()[1:] == lines[1:2]
    for args, message in (
            (["--recent", "0"], "qwen-agentd: invalid --recent '0' (1 to 100)"),
            (["--recent", "x"], "qwen-agentd: invalid --recent 'x' (1 to 100)"),
            (["--recent", "101"], "qwen-agentd: invalid --recent '101' (1 to 100)"),
            (["--recent", "--json"], "qwen-agentd: --json applies to trace TRACE_ID only"),
            ([T, "--recent"], "qwen-agentd: trace takes a TRACE_ID or --recent, not both"),
            ([], "qwen-agentd: trace needs a TRACE_ID or --recent [N]"),
            (["--port", "70000", T], "qwen-agentd: invalid --port 70000"),
            (["badid"], "qwen-agentd: invalid trace id 'badid' (32 lowercase hex characters)"),
            ([T.upper()], "qwen-agentd: invalid trace id '%s' (32 lowercase hex characters)" % T.upper())):
        proc = ftu.trace_cli(home, args)
        assert (proc.returncode, proc.stdout, proc.stderr) == (2, "", message + "\n"), args
    closed = ftu.free_port()
    proc = ftu.trace_cli(home, ["--port", str(closed), T])
    assert (proc.returncode, proc.stderr) == (1, "qwen-agentd: daemon not reachable at http://127.0.0.1:%d\n" % closed)
    proc = ftu.trace_cli(home, ["--port", str(port), "1" * 32])
    assert proc.returncode == 1
    assert proc.stdout == "trace 111111111111  -  -  agents: none  spans: 0\n"
    assert proc.stderr == "qwen-agentd: no records for trace %s\n" % ("1" * 32)
    old = _OldDaemon()
    try:
        for args in ([T], ["--recent"]):
            proc = ftu.trace_cli(home, ["--port", str(old.port)] + args)
            assert (proc.returncode, proc.stderr) == (
                1, "qwen-agentd: the daemon at http://127.0.0.1:%d has no trace support (http 401)\n" % old.port)
    finally:
        old.close()


def test_tracing_focus_2_fresh_agent_with_no_trace_file(tmp_path):
    """Review Focus 2: the first `trace --recent` on a newly installed agent, before any
    turn was traced. Expected: exit 1 with "no traces recorded on <agent>" (not an error
    about a missing file), `trace <id>` says "no records", and no query creates the file."""
    fleet = _alpha(tmp_path)
    port, home = fleet.ports["alpha"], fleet.homes["alpha"]
    proc = ftu.trace_cli(home, ["--port", str(port), "--recent"])
    assert (proc.returncode, proc.stdout, proc.stderr) == (1, "", "qwen-agentd: no traces recorded on alpha\n")
    proc = ftu.trace_cli(home, ["--port", str(port), T])
    assert proc.returncode == 1 and proc.stderr == "qwen-agentd: no records for trace %s\n" % T
    assert ftu.trace_files(home, "alpha") == []
    assert "trace" not in fleet.daemons["alpha"].log()
