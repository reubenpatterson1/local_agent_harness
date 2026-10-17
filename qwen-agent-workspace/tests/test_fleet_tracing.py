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


# --- POST /run and POST /delegate spans, propagation, the old-peer retry (TR23-TR25) ------------

def _signed_run(port, body, timeout=60):
    status, headers, raw, nonce = ftu.signed(ftu.TEST_KEY, "POST", port, "/run", body, timeout=timeout)
    assert ftu.response_ok(ftu.TEST_KEY, status, "POST", "/run", nonce, headers, raw), status
    return status, raw


def _of_kind(records, kind, trace_id=T):
    return [r for r in records if r["kind"] == kind and r["trace_id"] == trace_id]


def test_trt48_run_child_gets_the_agent_span_as_its_parent(tmp_path):
    hook = ftu.write_hook(os.path.join(str(tmp_path), "hook-envdump"), "envdump")
    fleet = ftu.Fleet(tmp_path, names=("alpha", "bravo"), extra_args={"bravo": ["--qwen-agent-bin", hook]}).start()
    ftu.wait_until(lambda: "bravo" in fleet.peer_ids("alpha"), 4.5)
    status, body = ftu.delegate(fleet.ports["alpha"], "researcher", "again", "bravo",
                                trace={"trace_id": T, "parent_span_id": P})
    assert status == 200 and body["outcome"] == "ok", body
    with open(hook + ".json", encoding="utf-8") as f:
        dumped = json.load(f)
    bravo = ftu.read_records(fleet.homes["bravo"], "bravo")
    alpha = ftu.read_records(fleet.homes["alpha"], "alpha")
    [delegate] = _of_kind(alpha, "delegate")
    [run] = _of_kind(bravo, "run")
    [agent] = _of_kind(bravo, "agent")
    assert dumped["env"]["QWEN_AGENT_TRACE_ID"] == T
    assert dumped["env"]["QWEN_AGENT_PARENT_SPAN"] == agent["span_id"]
    assert agent["parent_span_id"] == run["span_id"]
    assert run["parent_span_id"] == delegate["span_id"] and delegate["parent_span_id"] == P
    assert _of_kind(bravo, "turn") == []
    assert (delegate["status"], delegate["attrs"]) == ("ok", {"skill": "researcher", "target": "bravo",
                                                             "request_id": run["attrs"]["request_id"],
                                                             "http": 200, "images": 0})
    assert (run["status"], run["name"], run["attrs"]["http"]) == ("ok", "researcher", 200)
    assert (agent["status"], agent["attrs"]["envelope_status"]) == ("ok", "ok")
    bravo_url = "http://127.0.0.1:%d/v1" % fleet.server_ports["bravo"]
    assert dumped["argv"][1:] == ["--skill=researcher", "--user-prompt=again", "--base-url=%s" % bravo_url,
                                  "--model=bravo-model", "--model-server-type=ollama"]
    assert "run start skill=researcher request_id=%s task_chars=5 images=0 image_bytes=0" % (
        run["attrs"]["request_id"]) in fleet.daemons["bravo"].log()


class _OldPeer(object):
    """An in-process registered peer 'delta' from before tracing: its /run answers a body with
    a "trace" key with a signed 400 {"error": "bad request"} and any other body with the canned
    envelope; GET /trace/<id> is an unknown route (signed 404 {"error": "not found"})."""

    def __init__(self, port):
        self.run_bodies = []
        outer = self

        class Handler(http.server.BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.0"

            def log_message(self, *args):
                pass

            def _reply(self, status, raw):
                headers = fleet_lib.sign_response(ftu.TEST_KEY, status, self.command, self.path,
                                                  self.headers.get("X-Fleet-Nonce"), raw,
                                                  int(time.time()), os.urandom(16).hex())
                self.send_response(status)
                self.send_header("Content-Length", str(len(raw)))
                for name, value in headers.items():
                    self.send_header(name, value)
                self.end_headers()
                self.wfile.write(raw)

            def do_GET(self):
                if self.path == "/health":
                    self._reply(200, fleet_lib.canonical_json({"host_id": "delta", "role": "agent",
                                                               "version": "dev", "proto": 1,
                                                               "discovery": "beacon"}))
                elif self.path == "/skills":
                    self._reply(200, fleet_lib.canonical_json({"host_id": "delta", "skills": [
                        {"skill": "researcher", "model": "delta-model", "verified": True, "busy": False}]}))
                else:
                    self._reply(404, fleet_lib.canonical_json({"error": "not found"}))

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)))
                outer.run_bodies.append(body)
                if "trace" in body:
                    self._reply(400, fleet_lib.canonical_json({"error": "bad request"}))
                else:
                    self._reply(200, ftu.CANNED_LINE.encode("utf-8"))

        self.httpd = http.server.ThreadingHTTPServer(("127.0.0.1", port), Handler)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


def test_trt43_old_peer_gets_one_untraced_retry_and_shows_as_no_trace_support(tmp_path):
    delta_port = ftu.free_port()
    fleet = ftu.Fleet(tmp_path, names=("alpha",), extra_hosts={"delta": {
        "port": delta_port, "model_server": {"type": "vllm", "url": "http://127.0.0.1:9/v1"},
        "model": "delta-model", "skills": ["researcher"]}})
    delta = _OldPeer(delta_port)
    try:
        fleet.start()
        alpha = fleet.ports["alpha"]
        ftu.send_beacon(ftu.TEST_KEY, delta_port, fleet.beacon_ports["alpha"])
        ftu.wait_until(lambda: "delta" in fleet.peer_ids("alpha"), 3.0)
        status, body = ftu.delegate(alpha, "researcher", "t", "delta", trace={"trace_id": T, "parent_span_id": P})
        assert status == 200 and body["outcome"] == "ok" and body["envelope"]["answer"] == "CANNED", body
        [delegate] = _of_kind(ftu.read_records(fleet.homes["alpha"], "alpha"), "delegate")
        assert [sorted(b) for b in delta.run_bodies] == [["request_id", "skill", "task", "trace"],
                                                         ["request_id", "skill", "task"]]
        assert delta.run_bodies[0]["trace"] == {"trace_id": T, "parent_span_id": delegate["span_id"]}
        assert delta.run_bodies[0]["request_id"] == delta.run_bodies[1]["request_id"]
        status, result = ftu.trace(alpha, T)
        assert status == 200 and result["records"] == [delegate]
        assert (delegate["status"], delegate["attrs"]["http"]) == ("ok", 200)
        assert result["missing"] == [{"agent": "delta", "reason": "no trace support (http 404)"}]
        proc = ftu.trace_cli(fleet.homes["alpha"], ["--port", str(alpha), T])
        assert proc.returncode == 0
        lines = proc.stdout.splitlines()
        assert lines[1] == "! delta: no trace support (http 404)"
        assert lines[2] == "… span %s on alpha (not retrieved)" % P
        assert lines[3].startswith("  delegate researcher -> delta  req=%s  http=200  " % (
            delegate["attrs"]["request_id"])) and lines[3].endswith("  ok  @alpha")
    finally:
        delta.close()


def test_tracing_focus_5_a_crashed_child_still_leaves_run_and_agent_spans(tmp_path):
    """Review Focus 5: the peer's child crashes before printing an envelope (a model server
    that went away, a broken release). Expected: the run and agent spans are still recorded
    with http 502 and status error; a busy refusal is a run span "busy" with no agent span;
    a malformed trace field is a plain 400 with no span at all."""
    hook = ftu.write_hook(os.path.join(str(tmp_path), "hook-slow"), "slow")
    fleet = ftu.Fleet(tmp_path, names=("bravo",), extra_args={"bravo": ["--qwen-agent-bin", hook]}).start()
    port, home = fleet.ports["bravo"], fleet.homes["bravo"]

    def run_body(task, request_id, trace=None):
        req = {"skill": "researcher", "task": task, "request_id": request_id}
        if trace is not None:
            req["trace"] = trace
        return json.dumps(req).encode("utf-8")

    field = {"trace_id": T, "parent_span_id": P}
    assert _signed_run(port, run_body("garbage", "req-1", field)) == \
        (502, b'{"error":"skill produced no parseable output (exit code 1)"}')
    [run] = _of_kind(ftu.read_records(home, "bravo"), "run")
    [agent] = _of_kind(ftu.read_records(home, "bravo"), "agent")
    assert (run["parent_span_id"], run["status"], run["attrs"]["http"]) == (P, "error", 502)
    assert (agent["parent_span_id"], agent["status"]) == (run["span_id"], "error")
    assert agent["attrs"] == {"skill": "researcher", "request_id": "req-1", "http": 502, "envelope_status": None}
    result = {}
    first = threading.Thread(target=lambda: result.update(first=_signed_run(port, run_body("one", "req-2"))))
    first.start()
    ftu.wait_until(lambda: json.loads(ftu.signed(ftu.TEST_KEY, "GET", port, "/skills")[2])
                   ["skills"][0]["busy"] is True, 10)
    assert _signed_run(port, run_body("two", "req-3", field)) == (409, b'{"error":"busy"}')
    ftu.release_hook(hook, "one")
    first.join(30)
    assert result["first"] == (200, ftu.CANNED_LINE.encode("utf-8"))
    records = ftu.read_records(home, "bravo")
    busy = [r for r in records if r["kind"] == "run" and r["attrs"]["request_id"] == "req-3"]
    assert [(r["status"], r["attrs"]["http"], r["parent_span_id"]) for r in busy] == [("busy", 409, P)]
    assert [r for r in records if r["kind"] == "agent" and r["attrs"]["request_id"] == "req-3"] == []
    untraced = [r for r in records if r["kind"] == "run" and r["attrs"]["request_id"] == "req-2"]
    assert len(untraced) == 1 and untraced[0]["parent_span_id"] is None and untraced[0]["trace_id"] != T
    count = len(records)
    assert _signed_run(port, run_body("x", "req-4", {"trace_id": T})) == (400, b'{"error":"bad request"}')
    assert len(ftu.read_records(home, "bravo")) == count


# --- the chain: three daemons and the real harness end to end (TR17, TR22-TR27, TR42-TR45, TR50) ---

CHAIN_ANSWER = "ALPHA-ANSWER | BRAVO-ANSWER | CHARLIE-ANSWER"


def _chain(tmp_path, prompt="go", tasks=("stub task", "stub task"), before_start=None):
    """alpha's real harness delegates investigator to bravo, whose child delegates analyst to
    charlie (tracing spec 6.5) -> (fleet, harness CompletedProcess, the newest trace ID on
    alpha or None)."""
    fleet = ftu.Fleet(tmp_path, skills={"bravo": ["investigator"]},
                      stub_kwargs={"alpha": {"delegate_skill": "investigator", "delegate_task": tasks[0]},
                                   "bravo": {"delegate_skill": "analyst", "delegate_task": tasks[1]}})
    if before_start is not None:
        before_start(fleet)
    fleet.start()
    ftu.wait_until(fleet.all_see_each_other, 4.5)
    proc = _harness(fleet, tmp_path, prompt)
    return fleet, proc, _newest(fleet)


def _harness(fleet, tmp_path, prompt="go"):
    """The real bin/qwen-agent one-shot on alpha's stub, routed through alpha's daemon."""
    home = tmp_path / "caller"
    home.mkdir(exist_ok=True)
    env = ftu.clean_env(home, QWEN_AGENT_DAEMON_URL=fleet.daemons["alpha"].url)
    return subprocess.run([sys.executable, ftu.QWEN_AGENT, "--user-prompt=" + prompt,
                           "--base-url=%s" % fleet.stubs["alpha"].url, "--model=alpha-model"],
                          env=env, capture_output=True, text=True, timeout=180)


def _newest(fleet):
    status, listed = ftu.recent(fleet.ports["alpha"])
    if status != 200 or not listed["traces"]:
        return None
    return listed["traces"][0]["trace_id"]


def _depth(line):
    return (len(line) - len(line.lstrip(" "))) // 2


_CHAIN_SHAPE = [
    (0, r"turn oneshot  \S+  ok  rounds=2  tools=1  @alpha"),
    (1, r"model alpha-model  \S+  ok  1→1 tok  tool_calls  @alpha"),
    (1, r"tool delegate_to_skill  skill=investigator  \S+  ok  -> ok, \d+ characters  @alpha"),
    (2, r"delegate investigator -> bravo  req=(?P<r1>[0-9a-f]{16})  http=200  \S+  ok  @alpha"),
    (3, r"run investigator  req=(?P<r1b>[0-9a-f]{16})  http=200  \S+  ok  @bravo"),
    (4, r"agent investigator  req=[0-9a-f]{16}  http=200  \S+  ok  @bravo"),
    (5, r"model bravo-model  \S+  ok  1→1 tok  tool_calls  @bravo"),
    (5, r"tool delegate_to_skill  skill=analyst  \S+  ok  -> ok, \d+ characters  @bravo"),
    (6, r"delegate analyst -> charlie  req=(?P<r2>[0-9a-f]{16})  http=200  \S+  ok  @bravo"),
    (7, r"run analyst  req=(?P<r2b>[0-9a-f]{16})  http=200  \S+  ok  @charlie"),
    (8, r"agent analyst  req=[0-9a-f]{16}  http=200  \S+  ok  @charlie"),
    (9, r"model charlie-model  \S+  ok  1→1 tok  stop  @charlie"),
    (5, r"model bravo-model  \S+  ok  1→1 tok  stop  @bravo"),
    (1, r"model alpha-model  \S+  ok  1→1 tok  stop  @alpha"),
]


# The _CHAIN_SHAPE indices in printed order. A model call and the tool call it returned can
# start in the same millisecond (starts are rounded to 1 ms, TR4); TR17 then orders those two
# siblings by span_id, so the tool's subtree may print before the first model line, on alpha
# (index 1 after 12) or on bravo (index 6 after 11), or both.
_CHAIN_ORDERS = [[0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13],
                 [0, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 1, 13],
                 [0, 1, 2, 3, 4, 5, 7, 8, 9, 10, 11, 6, 12, 13],
                 [0, 2, 3, 4, 5, 7, 8, 9, 10, 11, 6, 12, 1, 13]]


def test_trt40_one_connected_tree_across_three_agents(tmp_path):
    fleet, proc, trace_id = _chain(tmp_path)
    assert proc.returncode == 0, proc.stderr
    assert json.loads(proc.stdout.strip().splitlines()[-1])["answer"] == CHAIN_ANSWER
    home, alpha = fleet.homes["alpha"], fleet.ports["alpha"]
    cli = ftu.trace_cli(home, ["--port", str(alpha), trace_id])
    assert cli.returncode == 0, cli.stderr
    lines = cli.stdout.splitlines()
    assert re.fullmatch(r"trace %s  \S+ \S+  \S+  agents: alpha, bravo, charlie  spans: 14" % trace_id[:12],
                        lines[0]), lines[0]
    assert len(lines) == 15 and not any(line.startswith(("!", "…", "(truncated")) for line in lines)
    ids, order = {}, []
    for line in lines[1:]:
        hits = [n for n, (depth, pattern) in enumerate(_CHAIN_SHAPE)
                if depth == _depth(line) and re.fullmatch(pattern, line.strip()) and n not in order]
        assert hits, line
        order.append(hits[0])
        ids.update(re.fullmatch(_CHAIN_SHAPE[hits[0]][1], line.strip()).groupdict())
    assert order in _CHAIN_ORDERS, order
    assert ids["r1"] == ids["r1b"] and ids["r2"] == ids["r2b"]
    assert [_depth(line) for line in lines[1:]].count(0) == 1
    assert "run start skill=investigator request_id=%s task_chars=9 " % ids["r1"] in fleet.daemons["bravo"].log()
    assert "delegate skill=investigator host=bravo request_id=%s outcome=ok" % ids["r1"] in \
        fleet.daemons["alpha"].log()
    cli = ftu.trace_cli(home, ["--port", str(alpha), "--json", trace_id])
    result = json.loads(cli.stdout)
    assert cli.returncode == 0 and len(result["records"]) == 14
    spans = set(r["span_id"] for r in result["records"])
    assert all(r["parent_span_id"] in spans for r in result["records"] if r["parent_span_id"] is not None)
    assert [r["kind"] for r in result["records"]].count("turn") == 1
    assert (result["missing"], result["truncated"]) == ([], [])


def test_trt41b_recent_lists_the_chain_runs(tmp_path):
    fleet, proc, first = _chain(tmp_path)
    assert proc.returncode == 0, proc.stderr
    proc = _harness(fleet, tmp_path)
    assert proc.returncode == 0, proc.stderr
    second = _newest(fleet)
    assert second != first
    home, alpha = fleet.homes["alpha"], str(fleet.ports["alpha"])
    cli = ftu.trace_cli(home, ["--port", alpha, "--recent"])
    lines = cli.stdout.splitlines()
    assert cli.returncode == 0 and len(lines) == 3
    assert lines[0] == "time                 trace id                               dur  status        spans  delegated"
    assert [line.split()[2] for line in lines[1:]] == [second, first]
    for line in lines[1:]:
        assert line.split()[4:] == ["ok", "5", "investigator@bravo"], line
    cli = ftu.trace_cli(home, ["--port", alpha, "--recent", "1"])
    assert cli.returncode == 0 and cli.stdout.splitlines()[1:] == lines[1:2]
    cli = ftu.trace_cli(fleet.homes["bravo"], ["--port", str(fleet.ports["bravo"]), "--recent"])
    assert (cli.returncode, cli.stderr) == (1, "qwen-agentd: no traces recorded on bravo\n")


def _stopped_peer_lines(cli, d_span):
    assert cli.returncode == 0, cli.stderr
    lines = cli.stdout.splitlines()
    assert "! bravo: unreachable (connection refused)" in lines
    i = lines.index("… span %s on bravo (not retrieved)" % d_span)
    assert re.fullmatch(r"  run analyst  req=[0-9a-f]{16}  http=200  \S+  ok  @charlie", lines[i + 1])
    assert re.fullmatch(r"    agent analyst  req=[0-9a-f]{16}  http=200  \S+  ok  @charlie", lines[i + 2])
    assert re.fullmatch(r"      model charlie-model  \S+  ok  1→1 tok  stop  @charlie", lines[i + 3])
    [k] = [n for n, line in enumerate(lines) if line.startswith("    delegate investigator -> bravo")]
    assert _depth(lines[k + 1]) <= 2


def test_trt42_a_stopped_peer_leaves_a_partial_tree(tmp_path):
    fleet, proc, trace_id = _chain(tmp_path)
    assert proc.returncode == 0, proc.stderr
    home, alpha = fleet.homes["alpha"], str(fleet.ports["alpha"])
    result = json.loads(ftu.trace_cli(home, ["--port", alpha, "--json", trace_id]).stdout)
    [d_span] = [r["span_id"] for r in result["records"] if r["kind"] == "delegate" and r["agent"] == "bravo"]
    fleet.daemons["bravo"].kill()
    assert "bravo" in fleet.peer_ids("alpha")
    _stopped_peer_lines(ftu.trace_cli(home, ["--port", alpha, trace_id]), d_span)
    ftu.wait_until(lambda: "bravo" not in fleet.peer_ids("alpha"), 15)
    _stopped_peer_lines(ftu.trace_cli(home, ["--port", alpha, trace_id]), d_span)


def test_trt47_no_prompt_task_answer_image_or_secret_reaches_traces_or_logs(tmp_path):
    fleet, proc, trace_id = _chain(tmp_path / "chain", prompt="go TRSENTINEL-PROMPT",
                                   tasks=("TRSENTINEL-TASK-A", "TRSENTINEL-TASK-B"))
    assert proc.returncode == 0, proc.stderr
    home, alpha = fleet.homes["alpha"], str(fleet.ports["alpha"])
    blobs = [json.dumps(ftu.trace(fleet.ports["alpha"], trace_id)[1]).encode(),
             json.dumps(ftu.recent(fleet.ports["alpha"])[1]).encode()]
    for args in ([trace_id], ["--json", trace_id], ["--recent"]):
        cli = ftu.trace_cli(home, ["--port", alpha] + args)
        assert cli.returncode == 0
        blobs.append(cli.stdout.encode("utf-8"))
    stderr_blobs = []
    for name in fleet.names:
        log_dir = ftu.daemon_log_dir(fleet.homes[name], name)
        for entry in os.listdir(log_dir):
            with open(os.path.join(log_dir, entry), "rb") as f:
                (stderr_blobs if entry == "last-run.stderr" else blobs).append(f.read())
    assert len(ftu.trace_files(home, "alpha")) == 1 and stderr_blobs
    for blob in blobs:
        for needle in (b"TRSENTINEL", b"ALPHA-ANSWER", b"BRAVO-ANSWER", b"CHARLIE-ANSWER"):
            assert needle not in blob, needle
    secrets = (ftu.TEST_TOKEN.encode("ascii"), ftu.TEST_KEY,
               fleet_lib.make_join_string(ftu.TEST_FLEET_ID, ftu.TEST_TOKEN).encode("ascii"))
    for blob in blobs + stderr_blobs:
        for needle in secrets:
            assert needle not in blob

    vision = ftu.Fleet(tmp_path / "vision", names=("alpha", "bravo"), skills={"bravo": ["vision"]},
                       stub_kwargs={"alpha": {"delegate_skill": "vision",
                                              "delegate_images": ["a.png", "b.jpg"]}}).start()
    ftu.wait_until(lambda: fleet_lib.route_candidates("vision", vision.view("alpha")) == ["bravo"], 4.5)
    caller = tmp_path / "vision" / "caller"
    ws = caller / "ws"
    ws.mkdir(parents=True)
    (ws / "a.png").write_bytes(ftu.PNG_BYTES)
    (ws / "b.jpg").write_bytes(ftu.JPEG_BYTES)
    env = ftu.clean_env(caller, QWEN_AGENT_DAEMON_URL=vision.daemons["alpha"].url)
    proc = subprocess.run([sys.executable, ftu.QWEN_AGENT, "--user-prompt=go", "--workspace=%s" % ws,
                           "--base-url=%s" % vision.stubs["alpha"].url, "--model=alpha-model"],
                          env=env, capture_output=True, text=True, timeout=120)
    assert proc.returncode == 0, proc.stderr
    needles = [ftu.PNG_BYTES, ftu.JPEG_BYTES]
    for data in (ftu.PNG_BYTES, ftu.JPEG_BYTES):
        needles.append(base64.b64encode(data)[:40])
    for name in vision.names:
        paths = ftu.trace_files(vision.homes[name], name)
        assert paths, name
        for path in paths:
            with open(path, "rb") as f:
                blob = f.read()
            for needle in needles:
                assert needle not in blob, (path, needle[:12])
    keys = [r["attrs"]["key"] for r in ftu.read_records(vision.homes["alpha"], "alpha") if r["kind"] == "tool"]
    assert keys == ["skill=vision images=2"]


def test_trt49_an_unwritable_store_never_changes_a_run(tmp_path):
    def store_is_a_directory(fleet):
        os.makedirs(os.path.join(ftu.daemon_log_dir(fleet.homes["alpha"], "alpha"), "trace.jsonl"))

    fleet, proc, trace_id = _chain(tmp_path, before_start=store_is_a_directory)
    assert proc.returncode == 0, proc.stderr
    envelope = json.loads(proc.stdout.strip().splitlines()[-1])
    assert (envelope["status"], envelope["answer"]) == ("ok", CHAIN_ANSWER)
    assert trace_id is None
    assert _post_span(fleet.ports["alpha"], _span()) == (200, b'{"ok":true}')
    assert fleet.daemons["alpha"].log().count("trace: cannot write ") == 1
    assert [r["kind"] for r in ftu.read_records(fleet.homes["bravo"], "bravo")].count("run") == 1
