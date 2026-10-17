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
