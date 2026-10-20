"""movie-ui HTTP layer and endpoint tests (movie-ui spec MUT2, MUT9, MUT13, MUT14, MUT17-MUT21,
MUT23, MUT24). Run from the workspace root: python3 -m pytest tests/test_movie_ui_http.py -v
Every server binds 127.0.0.1 on a free port under a temporary HOME; requests use http.client."""

import hashlib
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import threading
import time

import pytest

import movie_ui_testutil as mt
import movie_ui_lib as lib
import movie_ui_server as srv


@pytest.fixture
def env(monkeypatch, tmp_path):
    state = mt.set_home(monkeypatch, tmp_path)
    ws = mt.make_stub_workspace(tmp_path)
    running = mt.Running(state)
    yield {"state": state, "ws": ws, "tmp": str(tmp_path), "srv": running, "home": os.environ["HOME"]}
    running.close()
    mt.kill_everything(state)


def test_mu13_query_parsing():
    assert srv.parse_query("a=1&b=x+y&c=%2Fp%20q&a=2&&d") == {"a": "2", "b": "x y", "c": "/p q", "d": ""}
    assert srv.parse_query("p=%C3%A9%e2%9c%93") == {"p": "é✓"}
    assert srv.parse_query("p=100%") == {"p": "100%"}
    with pytest.raises(ValueError):
        srv.parse_query("p=%ff")


def test_mut18_every_api_route_needs_the_token(env):
    s = env["srv"]
    assert len(srv.ROUTES) == 35
    for method, regex, name, sample in srv.ROUTES:
        assert re.fullmatch(regex, sample), sample
        body = {} if method in ("POST", "PUT") else None
        for token in (None, "wrong-token"):
            status, _h, payload = mt.api(s, method, sample, body=body, token=token)
            assert (status, payload) == (401, {"error": "missing or invalid token"}), (method, sample, token)
    assert mt.api(s, "GET", "/api/x", token=None)[0] == 401
    assert mt.api(s, "GET", "/api/x")[2] == {"error": "not found"}
    assert mt.api(s, "GET", "/api/x")[0] == 404
    assert mt.api(s, "GET", "/nothing")[0] == 404
    status, _h, payload = mt.api(s, "DELETE", "/api/host")
    assert (status, payload) == (405, {"error": "method not allowed"})
    assert mt.api(s, "PUT", "/api/jobs", body={})[0] == 405


def test_mut18_host_origin_and_body_checks(env):
    s = env["srv"]
    port = s.port
    status, headers, payload = mt.api(s, "GET", "/api/host", headers={"Host": "evil:%d" % port})
    assert (status, payload) == (403, {"error": "forbidden host"})
    assert mt.api(s, "GET", "/api/host", headers={"Host": "127.0.0.1"})[0] == 403
    assert mt.api(s, "GET", "/api/host", headers={"Host": "[::1]:%d" % port})[0] == 403
    assert mt.api(s, "GET", "/api/x", headers={"Host": "localhost:%d" % port})[0] == 404
    status, _h, payload = mt.api(s, "GET", "/api/x", headers={"Origin": "http://evil"})
    assert (status, payload) == (403, {"error": "forbidden origin"})
    assert mt.api(s, "GET", "/api/x", headers={"Origin": "http://localhost:%d" % port})[0] == 404
    assert mt.api(s, "GET", "/api/x", headers={"Origin": "http://127.0.0.1:%d" % port})[0] == 404
    status, headers, payload = mt.api(s, "POST", "/api/preview", raw=b"",
                                      headers={"Content-Type": "application/json", "Content-Length": None})
    assert (status, payload) == (411, {"error": "Content-Length required"})
    status, _h, payload = mt.api(s, "POST", "/api/preview", raw=b"",
                                 headers={"Content-Type": "application/json", "Content-Length": str(26214401)})
    assert (status, payload) == (413, {"error": "request body too large"})
    status, _h, payload = mt.api(s, "POST", "/api/preview", raw=b"{}", headers={"Content-Type": "text/plain"})
    assert (status, payload) == (415, {"error": "unsupported content type"})
    status, _h, payload = mt.api(s, "POST", "/api/preview", raw=b"{nope",
                                 headers={"Content-Type": "application/json; charset=utf-8"})
    assert (status, payload) == (400, {"error": "invalid JSON body"})
    status, _h, payload = mt.api(s, "POST", "/api/preview", raw=b"[1]", headers={"Content-Type": "application/json"})
    assert (status, payload) == (400, {"error": "body must be a JSON object"})
    status, headers, payload = mt.api(s, "GET", "/api/x?q=%ff")
    assert (status, payload) == (404, {"error": "not found"})
    assert headers["content-type"] == "application/json; charset=utf-8"
    assert headers["cache-control"] == "no-store" and headers["x-content-type-options"] == "nosniff"
    assert not any(k.startswith("access-control-") for k in headers)
    with pytest.raises(srv.ApiError) as e:
        srv.resolve_ws(None)
    assert (e.value.status, e.value.body) == (400, {"error": "missing ws"})
    for value, message in (("relative", "ws must be an absolute path"),
                           ("/nonexistent", "not a harness workspace (no bin/ltx-movie): /nonexistent")):
        with pytest.raises(srv.ApiError) as e:
            srv.resolve_ws(value)
        assert e.value.body == {"error": message}
    assert srv.resolve_ws(env["ws"] + "/bin/..") == env["ws"]


def test_mu7_no_request_log_below_500_and_a_500_line(env, capfd):
    s = env["srv"]
    mt.api(s, "GET", "/api/x?t=secret")
    mt.api(s, "GET", "/api/x", token=None)

    def boom(self, groups, query, body):
        raise RuntimeError("kaput")
    srv.MovieUIHandler.h_boom = boom
    srv.ROUTES.append(("GET", r"/api/boom", "h_boom", "/api/boom"))
    try:
        status, _h, payload = mt.api(s, "GET", "/api/boom?t=secret")
    finally:
        srv.ROUTES.pop()
        del srv.MovieUIHandler.h_boom
    assert (status, payload) == (500, {"error": "internal error"})
    err = capfd.readouterr().err
    assert err == "movie-ui: GET /api/boom -> 500 (RuntimeError: kaput)\n"


def _raw(port, data):
    import socket as _socket
    sock = _socket.create_connection(("127.0.0.1", port), timeout=30)
    try:
        sock.sendall(data)
        chunks = []
        while True:
            c = sock.recv(65536)
            if not c:
                break
            chunks.append(c)
        return b"".join(chunks)
    finally:
        sock.close()


def test_fix_result_send_failures_are_500_and_json_constants_rejected(env, capfd):
    s = env["srv"]

    def odd(self, groups, query, body):
        return 200, {"x": object()}
    srv.MovieUIHandler.h_odd = odd
    srv.ROUTES.append(("GET", r"/api/odd", "h_odd", "/api/odd"))
    try:
        status, _h, payload = mt.api(s, "GET", "/api/odd")
    finally:
        srv.ROUTES.pop()
        del srv.MovieUIHandler.h_odd
    assert (status, payload) == (500, {"error": "internal error"})
    capfd.readouterr()
    hdr = {"Content-Type": "application/json"}
    status, _h, payload = mt.api(s, "POST", "/api/preview", raw=b'{"n": "\\ud800"}', headers=hdr)
    assert (status, payload) == (400, {"error": "invalid JSON body"})
    for raw in (b"NaN", b'{"n": Infinity}', b'{"n": -Infinity}',
                b'{"n": 1e999}', b'{"n": -1e999}'):
        assert mt.api(s, "POST", "/api/preview", raw=raw, headers=hdr)[0] == 400


def test_fix_token_host_methods_and_content_length(env):
    s = env["srv"]
    port = s.port
    tok = mt.TOKEN
    assert mt.api(s, "GET", "/api/host?t=" + tok, token=None)[0] == 401
    assert mt.api(s, "GET", "/api/host", headers={"Host": None})[0] == 403
    status, headers, _p = mt.api(s, "OPTIONS", "/api/host", token=None)
    assert status == 401
    assert not any(k.startswith("access-control-") for k in headers)
    out = _raw(port, b"HEAD /api/host HTTP/1.1\r\nHost: 127.0.0.1:%d\r\n\r\n" % port)
    assert out.split(b"\r\n")[0].split(b" ")[1] == b"401"
    assert b"access-control-" not in out.lower()
    assert mt.api(s, "PATCH", "/api/host")[0] == 405
    assert mt.api(s, "FOO", "/api/host", token=None)[0] == 401
    hdr = {"Content-Type": "application/json"}
    for bad in ("-1", "abc"):
        status, _h, payload = mt.api(s, "POST", "/api/preview", raw=b"{}",
                                     headers=dict(hdr, **{"Content-Length": bad}))
        assert status == 400, bad
    status, _h, payload = mt.api(s, "POST", "/api/preview", raw=b"",
                                 headers={"Content-Type": "application/json", "Content-Length": None,
                                          "Transfer-Encoding": "chunked"})
    assert (status, payload) == (411, {"error": "Content-Length required"})


def test_fix_resolve_ws_nul_byte():
    with pytest.raises(srv.ApiError) as e:
        srv.resolve_ws("/tmp/a\x00b")
    assert e.value.status == 400


def test_fix_http2_request_gets_json_and_no_traceback(env, capfd):
    port = env["srv"].port
    out = _raw(port, b"GET / HTTP/2.0\r\nHost: 127.0.0.1:%d\r\n\r\n" % port)
    head, _sep, body = out.partition(b"\r\n\r\n")
    assert b" 505 " in head.split(b"\r\n")[0]
    assert "error" in json.loads(body.decode("utf-8"))
    assert "Traceback" not in capfd.readouterr().err


def test_fix_logged_line_escapes_control_characters(env, capfd):
    port = env["srv"].port

    def boom(self, groups, query, body):
        raise RuntimeError("kaput")
    srv.MovieUIHandler.h_boom = boom
    srv.ROUTES.append(("GET", r"/api/boom.*", "h_boom", "/api/boom"))
    try:
        _raw(port, b"GET /api/boom\x1b[31m HTTP/1.1\r\nHost: 127.0.0.1:%d\r\n%s: %s\r\n\r\n"
             % (port, srv.TOKEN_HEADER.encode(), mt.TOKEN.encode()))
    finally:
        srv.ROUTES.pop()
        del srv.MovieUIHandler.h_boom
    err = capfd.readouterr().err
    assert "\x1b" not in err
    assert err == "movie-ui: GET /api/boom\\x1b[31m -> 500 (RuntimeError: kaput)\n"


def test_mu14_ws_parameter_errors_and_options(env):
    s = env["srv"]
    assert mt.api(s, "GET", "/api/options")[2] == {"error": "missing ws"}
    assert mt.api(s, "GET", "/api/options?ws=relative")[2] == {"error": "ws must be an absolute path"}
    assert mt.api(s, "GET", "/api/options?ws=%ff")[:3:2] == (400, {"error": "invalid query string"})
    status, _h, payload = mt.api(s, "GET", "/api/options?ws=" + env["ws"])
    assert status == 200
    assert payload["workspace"] == env["ws"] and payload["help_ok"] is True and payload["help_error"] is None
    assert payload["flags"] == sorted(payload["flags"]) and "--judge" in payload["flags"]
    assert all(payload["supported"].values()) and len(payload["supported"]) == 26
    assert payload["defaults"] == {"panels": 15, "fps": 24, "frames": 145, "model": lib.DEFAULT_MODEL,
                                   "gemma": lib.DEFAULT_GEMMA, "panel_timeout": 7200}
    with open(os.path.join(mt.FIXTURES, "ltx-movie-help-old.txt"), encoding="utf-8") as f:
        mt.stub_config(env["ws"], {"ltx-movie --help": {"stdout": f.read()}})
    os.utime(os.path.join(env["ws"], "bin", "ltx-movie"), ns=(10 ** 9, 10 ** 9))
    payload = mt.api(s, "GET", "/api/options?ws=" + env["ws"])[2]
    assert payload["supported"]["judge"] is False and payload["supported"]["goal"] is False
    assert payload["supported"]["panels"] is True


def test_mut9_host_and_refresh(env, monkeypatch):
    s = env["srv"]
    server = s.server
    server.probe_ws = env["ws"]
    good_py = os.path.join(env["tmp"], "good-python")
    with open(good_py, "w") as f:
        f.write("#!/bin/sh\nexit 0\n")
    os.chmod(good_py, 0o755)
    server.stills_py = good_py
    monkeypatch.setenv("LTX2_MLX_BIN", os.path.join(env["tmp"], "missing-ltx"))
    payload = mt.api(s, "GET", "/api/host")[2]
    assert payload["capabilities"]["render"] == {"ok": None, "reason": "probing", "checked": None}
    assert payload["port"] == s.port and payload["state_dir"] == env["state"]
    assert payload["ui_workspace"] == mt.WS and payload["default_workspace"] == mt.WS
    assert payload["default_agent"] is None and payload["api_key_present"] is False
    assert payload["running_job"] is None and payload["queue_length"] == 0
    assert set(payload) == {"host", "platform", "python", "port", "state_dir", "ui_workspace", "default_workspace",
                            "default_agent", "api_key_present", "capabilities", "running_job", "queue_length"}
    payload = mt.api(s, "GET", "/api/host?refresh=1")[2]
    caps = payload["capabilities"]
    assert caps["render"]["ok"] is False and caps["render"]["reason"].startswith("ltx-2-mlx binary not found")
    assert caps["stills"] == {"ok": True, "reason": None, "checked": caps["stills"]["checked"]}
    assert caps["story_server"]["ok"] is True and caps["story_server"]["reason"] == "story server: SERVING vision"
    mt.stub_config(env["ws"], {"story-server status": {"stdout": "  state:          STOPPED\n"}})
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-not-a-key")
    payload = mt.api(s, "GET", "/api/host?refresh=1")[2]
    assert payload["capabilities"]["story_server"]["ok"] is False and payload["api_key_present"] is True


def test_mut23_workspaces_labels_default_and_prune(env, monkeypatch):
    home = env["home"]
    state = {"from": "v2026.10.02", "to": "v2026.10.05", "status": "ok", "attempts": 0, "bad_tags": []}
    mt.make_agents_home(home, {
        "mac-local": {"current": "v2026.10.05", "default": True, "port": 8190, "state": state,
                      "releases": {"v2026.10.01": {"data": True, "bytes": 1234}, "v2026.10.02": {},
                                   "v2026.09.30": {}, "v2026.10.03": {}, "v2026.10.04": {}, "v2026.10.05": {},
                                   "notes": {}}},
        "spare": {"releases": {"v2026.10.01": {}}, "fleet_env": True},
        "ghost": {"releases": {"v2026.10.01": {}}}})
    s = env["srv"]
    payload = mt.api(s, "GET", "/api/workspaces")[2]
    a = os.path.join(home, "agents", "mac-local")
    entries = payload["workspaces"]
    assert [e["label"] for e in entries] == [
        "mac-local current (v2026.10.05)", "mac-local v2026.10.04", "mac-local v2026.10.03", "mac-local v2026.10.02",
        "mac-local v2026.10.01", "mac-local v2026.09.30", "spare v2026.10.01",
        "this checkout (%s)" % entries[-1]["commit"] if entries[-1]["commit"] else "this checkout (unknown commit)"]
    by_tag = dict((e["label"], e) for e in entries)
    cur = by_tag["mac-local current (v2026.10.05)"]
    assert cur["path"] == os.path.join(a, "current", "qwen-agent-workspace") and cur["is_current"] is True
    assert cur["prune"] is None and cur["data_bytes"] is None and cur["agent"] == "mac-local"
    assert by_tag["mac-local v2026.10.04"]["prune"] == "kept"
    assert by_tag["mac-local v2026.10.02"]["prune"] == "kept"
    assert by_tag["mac-local v2026.10.01"]["prune"] == "kept_for_data"
    assert by_tag["mac-local v2026.10.01"]["data_bytes"] == 1234
    assert by_tag["mac-local v2026.10.01"]["stories"] == 1
    assert by_tag["mac-local v2026.09.30"]["prune"] == "would_prune"
    assert by_tag["mac-local v2026.09.30"]["data_bytes"] == 0 and by_tag["mac-local v2026.09.30"]["is_current"] is False
    assert entries[-1]["is_ui"] is True and entries[-1]["agent"] is None and entries[-1]["prune"] is None
    assert set(cur) == {"path", "realpath", "label", "agent", "tag", "commit", "is_current", "is_ui", "stories",
                        "prune", "data_bytes"}
    assert payload["default"] == mt.WS
    assert srv.default_agent() == "mac-local"
    ui_copy = os.path.join(a, "releases", "v2026.10.03", "qwen-agent-workspace")
    assert srv.default_workspace(ui_copy) == os.path.join(a, "current", "qwen-agent-workspace")
    assert srv.default_workspace("/somewhere/else") == "/somewhere/else"
    os.unlink(os.path.join(home, ".local", "bin", "qwen-agent"))
    assert srv.default_agent() is None
    typed = mt.api(s, "GET", "/api/options?ws=" + os.path.join(env["tmp"]))
    assert typed[:3:2] == (400, {"error": "not a harness workspace (no bin/ltx-movie): %s" % env["tmp"]})
