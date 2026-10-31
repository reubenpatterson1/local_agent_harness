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

import batch_testutil as bt
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
    assert len(srv.ROUTES) == 46
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
    assert all(payload["supported"].values()) and len(payload["supported"]) == 30
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


def _compose(env, **overrides):
    return mt.fields(env["ws"], **overrides)


def test_mut2_preview_argv_is_the_job_argv(env):
    s = env["srv"]
    free = mt.fake_safetensors(os.path.join(env["tmp"], "free.safetensors"))
    sets = [_compose(env),
            _compose(env, action="regenerate", goal="Keep it tense."),
            _compose(env, panels=None, length=30, mode="shots", story_model="qwen38",
                     stills_loras=[{"id": None, "path": free, "strength": 0.7, "kind": None}])]
    for body in sets:
        status, _h, preview = mt.api(s, "POST", "/api/preview", body=body)
        assert status == 200 and preview["errors"] == []
        assert preview["command"] == shlex.join(preview["argv"])
        status, _h, created = mt.api(s, "POST", "/api/jobs", body=body)
        assert status == 201, created
        assert all(c["status"] != "fail" for c in created["checks"])
        job = lib.read_job(lib.job_dir(env["state"], created["job"]["id"]))
        assert job["argv"] == preview["argv"]
        assert job["fields"]["ws"] == env["ws"] and job["workspace"] == env["ws"]
        assert job["kind"] == "story" and job["story_id"] == "ronin-rescue" and job["character"] is None
        assert created["job"]["state"] == "queued" and created["job"]["progress"] is None
    status, _h, bad = mt.api(s, "POST", "/api/preview", body=_compose(env, panels=0))
    assert (status, bad["argv"], bad["command"]) == (200, None, None)
    assert bad["errors"] == ["panels must be an integer from 1 to 200"]
    status, _h, refused = mt.api(s, "POST", "/api/jobs", body=_compose(env, panels=0))
    assert status == 409 and refused["error"] == "validation failed" and refused["checks"][0]["status"] == "fail"
    status, _h, valid = mt.api(s, "POST", "/api/validate", body=_compose(env))
    assert status == 200 and valid["ok"] is True and valid["argv"] == mt.api(s, "POST", "/api/preview",
                                                                             body=_compose(env))[2]["argv"]
    jobs = mt.api(s, "GET", "/api/jobs")[2]
    assert jobs["running"] is None and jobs["history"] == []
    assert [j["queue_position"] for j in jobs["queued"]] == [1, 2, 3]
    assert set(jobs["queued"][0]) == {"id", "kind", "state", "workspace", "story_id", "character", "created",
                                      "started", "ended", "exit_code", "error", "queue_position", "command",
                                      "progress"}


def test_mut13_mut14_job_actions_over_http(env):
    s, state, ws = env["srv"], env["state"], env["ws"]
    a, b = mt.make_job(state, ["true"], ws), mt.make_job(state, ["true"], ws)
    assert mt.api(s, "POST", "/api/queue/move", body={"id": b, "direction": "up"})[:3:2] == (200, {"queued": [b, a]})
    assert mt.api(s, "POST", "/api/queue/move", body={"id": b, "direction": "sideways"})[0] == 400
    status, _h, payload = mt.api(s, "POST", "/api/jobs/%s/cancel" % a, body={})
    assert (status, payload) == (200, {"state": "cancelled"})
    assert mt.api(s, "POST", "/api/jobs/%s/cancel" % a, body={})[:3:2] == (
        409, {"error": "job %s is not queued or running" % a})
    assert mt.api(s, "POST", "/api/queue/move", body={"id": a, "direction": "up"})[:3:2] == (
        409, {"error": "job %s is not queued" % a})
    assert mt.api(s, "DELETE", "/api/jobs/%s" % b)[:3:2] == (409, {"error": "job %s is not finished" % b})
    assert mt.api(s, "DELETE", "/api/jobs/%s" % a)[:3:2] == (200, {"deleted": a})
    assert mt.api(s, "GET", "/api/jobs/%s" % a)[0] == 404
    assert mt.api(s, "GET", "/api/jobs/20261019-000000-0000")[0] == 404
    detail = mt.api(s, "GET", "/api/jobs/%s" % b)[2]
    assert detail["status"] == {"state": "queued"} and detail["progress"] is None and detail["orphan"] is None
    assert detail["window"] == {"start": None, "end": None} and detail["job"]["id"] == b
    running = mt.make_job(state, ["true"], ws, status={"state": "running", "dispatched": lib.utc_now(),
                                                         "runner_pid": 1, "pgid": None, "started": lib.utc_now()})
    assert mt.api(s, "POST", "/api/jobs/%s/cancel" % running, body={})[:3:2] == (202, {"state": "cancelling"})
    assert os.path.exists(os.path.join(lib.job_dir(state, running), "cancel"))
    orphan = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"], start_new_session=True)
    try:
        lost = mt.make_job(state, ["true"], ws, status={
            "state": "lost", "dispatched": lib.utc_now(), "runner_pid": 1, "pgid": orphan.pid,
            "started": lib.utc_now(), "exit_code": None, "ended": None, "detected": lib.utc_now()})
        assert mt.api(s, "GET", "/api/jobs/%s" % lost)[2]["orphan"] == {"pgid": orphan.pid, "alive": True}
        assert mt.api(s, "POST", "/api/jobs/%s/kill-orphan" % lost, body={})[:3:2] == (
            400, {"error": "confirm must be true"})
        assert mt.api(s, "POST", "/api/jobs/%s/kill-orphan" % lost, body={"confirm": "yes"})[0] == 400
        assert mt.api(s, "POST", "/api/jobs/%s/kill-orphan" % lost, body={"confirm": True})[:3:2] == (
            200, {"killed": orphan.pid})
        orphan.wait(5)
        assert mt.api(s, "POST", "/api/jobs/%s/kill-orphan" % lost, body={"confirm": True})[:3:2] == (
            409, {"error": "job %s has no live orphan process group" % lost})
    finally:
        if orphan.poll() is None:
            orphan.kill()
    jobs = mt.api(s, "GET", "/api/jobs")[2]
    assert jobs["running"]["id"] == running and jobs["running"]["progress"]["phase"] is None
    assert [j["id"] for j in jobs["queued"]] == [b]
    assert [j["id"] for j in jobs["history"]] == [lost]


def test_mut17_log_offsets_chain_on_character_boundaries(env):
    s, state = env["srv"], env["state"]
    job_id = mt.make_job(state, ["true"], env["ws"])
    data = b"a" * 262143 + "€".encode("utf-8") + b"b" * (300 * 1024 - 262146)
    with open(os.path.join(lib.job_dir(state, job_id), "log.txt"), "wb") as f:
        f.write(data)
    first = mt.api(s, "GET", "/api/jobs/%s/log" % job_id)[2]
    assert (first["offset"], first["next_offset"], first["size"], first["eof"]) == (0, 262143, len(data), False)
    assert first["text"] == "a" * 262143
    text, offset, rounds = first["text"], first["next_offset"], 1
    while True:
        chunk = mt.api(s, "GET", "/api/jobs/%s/log?offset=%d" % (job_id, offset))[2]
        text += chunk["text"]
        offset = chunk["next_offset"]
        rounds += 1
        if chunk["eof"]:
            break
    assert text == data.decode("utf-8") and offset == len(data) and rounds == 2
    tail = mt.api(s, "GET", "/api/jobs/%s/log?offset=%d" % (job_id, len(data) + 50))[2]
    assert (tail["text"], tail["next_offset"], tail["eof"]) == ("", len(data), True)
    assert mt.api(s, "GET", "/api/jobs/%s/log?offset=-1" % job_id)[:3:2] == (400, {"error": "invalid offset"})
    assert mt.api(s, "GET", "/api/jobs/%s/log?offset=1234567890123456" % job_id)[0] == 400
    assert srv.utf8_cut("a€".encode()[:-1]) == b"a" and srv.utf8_cut("a€".encode()) == "a€".encode()
    assert srv.utf8_cut("😀".encode()[:3]) == b"" and srv.utf8_cut("😀".encode()) == "😀".encode()


def test_review_focus_4_two_tabs_submit_at_once(env):
    """Review Focus 4: two browser tabs (or a double click) submit jobs at the same moment."""
    s = env["srv"]
    results = []

    def submit(i):
        results.append(mt.api(s, "POST", "/api/jobs", body=_compose(env, story_id="story-%d" % i)))
    threads = [threading.Thread(target=submit, args=(i,)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(60)
    assert sorted(r[0] for r in results) == [201] * 8
    ids = [r[2]["job"]["id"] for r in results]
    assert len(set(ids)) == 8
    assert sorted(lib.read_queue(env["state"])) == sorted(ids)
    assert sorted(lib.list_job_ids(env["state"])) == sorted(ids)


def test_review_focus_5_undecodable_bytes_in_a_running_log(env):
    """Review Focus 5: ffmpeg or a model prints bytes that are not UTF-8 while the page polls."""
    s, state = env["srv"], env["state"]
    job_id = mt.make_job(state, ["true"], env["ws"], status={"state": "running", "dispatched": lib.utc_now(),
                                                               "runner_pid": 1, "pgid": None, "started": lib.utc_now()})
    log = os.path.join(lib.job_dir(state, job_id), "log.txt")
    with open(log, "wb") as f:
        f.write(b"\xff\xfe\x00junk\n=== Phase 4: render ===\n=== panel 1/2 (a) ===\npanel 1 ok: caf\xc3")
    progress = mt.api(s, "GET", "/api/jobs/%s" % job_id)[2]["progress"]
    assert progress["phase"] == "4" and progress["panels"] == {"1": {"state": "running"}}
    assert progress["last_line"] == "panel 1 ok: caf"
    with open(log, "ab") as f:
        f.write(b"\xa9.mp4 (1.0s)\n")
    progress = mt.api(s, "GET", "/api/jobs")[2]["running"]["progress"]
    assert progress["panels"] == {"1": {"state": "ok", "reused": False}}
    assert progress["last_line"] == "panel 1 ok: café.mp4 (1.0s)"
    chunk = mt.api(s, "GET", "/api/jobs/%s/log" % job_id)[2]
    assert chunk["text"].startswith("��\x00junk\n") and chunk["eof"] is True


def test_jobs_blocked_by_live_orphan(env):
    s, state, ws = env["srv"], env["state"], env["ws"]
    assert mt.api(s, "GET", "/api/jobs")[2]["blocked_by"] is None
    orphan = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"], start_new_session=True)
    try:
        lost = mt.make_job(state, ["true"], ws, status={
            "state": "lost", "dispatched": lib.utc_now(), "runner_pid": 1, "pgid": orphan.pid,
            "started": lib.utc_now(), "exit_code": None, "ended": None, "detected": lib.utc_now()})
        assert mt.api(s, "GET", "/api/jobs")[2]["blocked_by"] == {"job": lost, "pgid": orphan.pid}
    finally:
        orphan.kill()
        orphan.wait(5)


def test_job_delete_failure_is_500_and_job_stays(env, monkeypatch):
    s, state, ws = env["srv"], env["state"], env["ws"]
    done = mt.make_job(state, ["true"], ws, status={"state": "done", "exit_code": 0, "ended": lib.utc_now()})

    def boom(path, *a, **k):
        raise OSError(13, "Permission denied")
    monkeypatch.setattr(lib.shutil, "rmtree", boom)
    status, _h, payload = mt.api(s, "DELETE", "/api/jobs/%s" % done)
    assert status == 500
    assert payload == {"error": "cannot delete job %s: Permission denied" % done}
    jobs = mt.api(s, "GET", "/api/jobs")[2]
    assert [j["id"] for j in jobs["history"]] == [done]


def _live_orphan_job(env):
    orphan = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"], start_new_session=True)
    lost = mt.make_job(env["state"], ["true"], env["ws"], status={
        "state": "lost", "dispatched": lib.utc_now(), "runner_pid": 1, "pgid": orphan.pid,
        "started": lib.utc_now(), "exit_code": None, "ended": None, "detected": lib.utc_now()})
    return orphan, lost


def test_kill_orphan_permission_error_is_409(env, monkeypatch):
    s = env["srv"]
    orphan, lost = _live_orphan_job(env)
    try:
        real = os.killpg

        def deny(group, sig):
            if sig == 0:
                return real(group, sig)
            raise PermissionError(1, "Operation not permitted")
        monkeypatch.setattr(lib.os, "killpg", deny)
        status, _h, payload = mt.api(s, "POST", "/api/jobs/%s/kill-orphan" % lost, body={"confirm": True})
        assert status == 409
        assert payload == {"error": "cannot kill process group %d: Operation not permitted" % orphan.pid}
    finally:
        orphan.kill()
        orphan.wait(5)


def test_delete_lost_job_with_live_orphan_needs_confirm(env):
    s = env["srv"]
    orphan, lost = _live_orphan_job(env)
    try:
        status, _h, payload = mt.api(s, "DELETE", "/api/jobs/%s" % lost)
        assert status == 409
        assert payload["error"] == ("job %s still has a live process group %d; kill it first, or delete "
                                    "with confirm to unblock the queue anyway" % (lost, orphan.pid))
        assert mt.api(s, "GET", "/api/jobs/%s" % lost)[0] == 200
        for bad in ({"confirm": "yes"}, {"confirm": 1}, {"confirm": 1.0}, {"confirm": True, "x": 1}):
            assert mt.api(s, "DELETE", "/api/jobs/%s" % lost, body=bad)[0] == 409
            assert mt.api(s, "GET", "/api/jobs/%s" % lost)[0] == 200
        assert mt.api(s, "DELETE", "/api/jobs/%s" % lost, body={"confirm": True})[:3:2] == (200, {"deleted": lost})
        assert mt.api(s, "GET", "/api/jobs/%s" % lost)[0] == 404
    finally:
        orphan.kill()
        orphan.wait(5)


def test_log_of_a_finished_job_returns_the_final_partial_bytes(env):
    s, state = env["srv"], env["state"]
    job_id = mt.make_job(state, ["true"], env["ws"], status={"state": "done", "exit_code": 0,
                                                              "ended": lib.utc_now()})
    with open(os.path.join(lib.job_dir(state, job_id), "log.txt"), "wb") as f:
        f.write(b"caf\xc3")
    chunk = mt.api(s, "GET", "/api/jobs/%s/log" % job_id)[2]
    assert chunk["text"] == "caf�" and chunk["eof"] is True and chunk["next_offset"] == chunk["size"] == 4


def test_job_actions_on_bad_input_and_unknown_ids(env):
    s, state, ws = env["srv"], env["state"], env["ws"]
    job_id = mt.make_job(state, ["true"], ws)
    assert mt.api(s, "GET", "/api/jobs/%s/log?offset=abc" % job_id)[0] == 400
    ghost = "20261019-000000-0000"
    assert mt.api(s, "POST", "/api/jobs/%s/cancel" % ghost, body={})[0] == 404
    assert mt.api(s, "DELETE", "/api/jobs/%s" % ghost)[0] == 404
    assert mt.api(s, "POST", "/api/jobs/%s/kill-orphan" % ghost, body={"confirm": True})[0] == 404
    assert mt.api(s, "POST", "/api/jobs/%s/kill-orphan" % job_id, body={"confirm": True})[:3:2] == (
        409, {"error": "job %s has no live orphan process group" % job_id})
    assert mt.api(s, "GET", "/api/jobs/%s" % job_id)[0] == 200
    shutil.rmtree(lib.job_dir(state, job_id))
    assert mt.api(s, "GET", "/api/jobs/%s" % job_id)[0] == 404


def test_delete_with_content_length_zero_is_an_absent_body(env):
    s, state = env["srv"], env["state"]
    done = mt.make_job(state, ["true"], env["ws"], status={"state": "done", "exit_code": 0,
                                                            "ended": lib.utc_now()})
    status, _h, payload = mt.api(s, "DELETE", "/api/jobs/%s" % done, headers={"Content-Length": "0"})
    assert (status, payload) == (200, {"deleted": done})


def _upload(s, data, media):
    return mt.api(s, "POST", "/api/uploads", raw=data, headers={"Content-Type": media})


def test_mut21_uploads(env):
    s, state = env["srv"], env["state"]
    for data, media, ext in ((mt.PNG, "image/png", "png"), (mt.JPEG, "image/jpeg", "jpg"), (mt.WEBP, "image/webp", "webp")):
        status, _h, payload = _upload(s, data, media)
        upload_id = "%s.%s" % (hashlib.sha256(data).hexdigest(), ext)
        assert (status, payload) == (201, {"upload_id": upload_id, "path": os.path.join(state, "uploads", upload_id),
                                           "bytes": len(data)})
        with open(payload["path"], "rb") as f:
            assert f.read() == data
        assert _upload(s, data, media)[2]["upload_id"] == upload_id
    assert _upload(s, mt.JPEG, "image/png")[:3:2] == (400, {"error": "file content is not image/png"})
    assert _upload(s, mt.PNG, "image/webp")[:3:2] == (400, {"error": "file content is not image/webp"})
    assert _upload(s, mt.PNG, "image/gif")[:3:2] == (415, {"error": "unsupported content type"})
    status, _h, payload = mt.api(s, "POST", "/api/uploads", raw=b"",
                                 headers={"Content-Type": "image/png", "Content-Length": str(20971521)})
    assert (status, payload) == (413, {"error": "upload larger than 20 MiB"})
    assert sorted(os.listdir(os.path.join(state, "uploads"))) == sorted(
        "%s.%s" % (hashlib.sha256(d).hexdigest(), e) for d, e in ((mt.PNG, "png"), (mt.JPEG, "jpg"), (mt.WEBP, "webp")))


def test_mu61_mu62_lora_endpoints(env):
    s, ws = env["srv"], env["ws"]
    entry = {"id": "pan", "kind": "motion", "target": "video", "path": "/l/pan.safetensors"}
    mt.stub_config(ws, {
        "lora-catalog list --json --model M": {"stdout": json.dumps({"catalog": "/c", "entries": [entry],
                                                                     "characters": []})},
        "lora-catalog add": {"exit": 2, "stderr": "Error: catalog entry pan already exists\n"},
        "lora-catalog verify": {"exit": 1, "stdout": "OK ink\nFAIL pan: sha256 changed\nFAIL pan: missing file\n"
                                                    "verified 2 entries: 2 problem(s)\n"}})
    status, _h, payload = mt.api(s, "GET", "/api/loras?ws=%s&model=M" % ws)
    assert (status, payload["entries"], payload["model"]) == (200, [entry], "M")
    status, _h, payload = mt.api(s, "GET", "/api/loras?ws=%s" % ws)
    assert status == 200 and payload["entries"] == [] and payload["model"] is None
    mt.stub_config(ws, {"lora-catalog list": {"exit": 2, "stderr": "Error: invalid catalog\n"}})
    status, _h, payload = mt.api(s, "GET", "/api/loras?ws=%s" % ws)
    assert status == 502 and payload["error"] == "lora-catalog exited 2"
    assert payload["run"]["stderr"] == "Error: invalid catalog\n"
    mt.stub_config(ws, {"lora-catalog add": {"exit": 2, "stderr": "Error: catalog entry pan already exists\n"},
                        "lora-catalog verify": {"exit": 1, "stdout": "OK ink\nFAIL pan: sha256 changed\n"
                                                                    "FAIL pan: missing file\n"}})
    add = {"ws": ws, "path": "/l/pan.safetensors", "id": "pan", "kind": "motion", "target": "video",
           "base_models": ["M1", "M2"], "triggers": ["panshot"], "description": "a pan", "use_when": "pans",
           "avoid_when": "", "default_strength": 0.8, "strength_range": [0.5, 1], "rank": 16, "alpha": None}
    status, _h, payload = mt.api(s, "POST", "/api/loras", body=add)
    assert status == 200 and payload["run"]["exit_code"] == 2
    assert mt.stub_calls(ws)[-1]["argv"] == [
        "add", "/l/pan.safetensors", "--id", "pan", "--kind", "motion", "--target", "video", "--base-model", "M1",
        "--base-model", "M2", "--trigger", "panshot", "--description", "a pan", "--use-when", "pans",
        "--default-strength", "0.8", "--strength-range", "0.5,1.0", "--rank", "16"]
    assert mt.api(s, "POST", "/api/loras", body=dict(add, triggers="panshot"))[:3:2] == (
        400, {"error": "triggers must be a list of strings"})
    assert mt.api(s, "POST", "/api/loras", body=dict(add, rank=1.5))[:3:2] == (
        400, {"error": "rank must be an integer or null"})
    status, _h, payload = mt.api(s, "POST", "/api/loras/remove", body={"ws": ws, "id": "pan"})
    assert status == 200 and mt.stub_calls(ws)[-1]["argv"] == ["remove", "pan"]
    status, _h, payload = mt.api(s, "POST", "/api/loras/verify", body={"ws": ws, "ids": []})
    assert status == 200 and mt.stub_calls(ws)[-1]["argv"] == ["verify"]
    assert payload["results"] == [{"id": "ink", "ok": True, "problems": []},
                                  {"id": "pan", "ok": False, "problems": ["sha256 changed", "missing file"]}]


def test_mu63_models_endpoint(env, monkeypatch):
    for var, sub in (("LTX2_MLX_HF_HOME", "l"), ("Z_IMAGE_HF_HOME", "z"), ("HF_HOME", "h")):
        monkeypatch.setenv(var, os.path.join(env["tmp"], sub))
    mt.make_hf_cache(os.path.join(env["tmp"], "l"), "org/m", {"a.safetensors": b"\x01"})
    status, _h, payload = mt.api(env["srv"], "GET", "/api/models?ws=" + env["ws"])
    assert status == 200 and [m["repo"] for m in payload["models"]] == ["org/m"]
    assert mt.api(env["srv"], "GET", "/api/models")[:3:2] == (400, {"error": "missing ws"})


def test_mu64_mu65_character_endpoints(env):
    s, ws, state = env["srv"], env["ws"], env["state"]
    sheet = os.path.join(env["tmp"], "lib", "kyra", "dataset", "contact_sheet.jpg")
    os.makedirs(os.path.join(os.path.dirname(sheet), "stills"))
    for name in ("char_02.png", "char_01.png", "other.png"):
        open(os.path.join(os.path.dirname(sheet), "stills", name), "wb").close()
    show = json.dumps({"name": "kyra", "status": "untrained", "dataset": {"contact_sheet": sheet},
                       "loras": {"video": None, "stills": None}}, indent=2)
    mt.stub_config(ws, {
        "character list": {"stdout": "NAME             TRIGGER          STATUS    VIDEO STILLS PHRASE\n"
                                     "kyra             kyrax            trained   yes   no     the young woman\n"
                                     "broken           (invalid: bad json)\n"},
        "character show kyra": {"stdout": show + "\nfiles:\n  ok       %s\n  MISSING  /lib/kyra/seed.png\n" % sheet}})
    assert mt.api(s, "GET", "/api/characters?ws=" + ws)[2] == {"characters": [
        {"name": "kyra", "trigger": "kyrax", "status": "trained", "video": True, "stills": False,
         "phrase": "the young woman", "invalid": None},
        {"name": "broken", "invalid": "bad json"}]}
    detail = mt.api(s, "GET", "/api/characters/kyra?ws=" + ws)[2]
    assert detail["character"]["status"] == "untrained"
    assert detail["files"] == [{"status": "ok", "path": sheet}, {"status": "MISSING", "path": "/lib/kyra/seed.png"}]
    stills = os.path.join(os.path.dirname(sheet), "stills")
    assert detail["dataset"] == {"contact_sheet": sheet, "stills": [os.path.join(stills, "char_01.png"),
                                                                    os.path.join(stills, "char_02.png")]}
    assert detail["face_problem"] is False and detail["last_create_fields"] is None
    seed = _upload(s, mt.PNG, "image/png")[2]["upload_id"]
    create = {"ws": ws, "name": "kyra", "phrase": "the young woman", "class_noun": None, "descriptor": None,
              "trigger": None, "seed": None, "seed_upload": seed, "force": False}
    for bad in (-1, 2 ** 31):
        status, _h, payload = mt.api(s, "POST", "/api/characters", body=dict(create, seed=bad))
        assert status == 400 and payload["errors"] == ["seed must be an integer from 0 to 2147483647"], bad
    status, _h, payload = mt.api(s, "POST", "/api/characters", body=create)
    assert status == 201 and payload["job"]["kind"] == "character-create" and payload["job"]["character"] == "kyra"
    job = lib.read_job(lib.job_dir(state, payload["job"]["id"]))
    assert job["argv"][2:] == ["create", "kyra", "--phrase", "the young woman", "--seed-image",
                               os.path.join(state, "uploads", seed), "--no-review"]
    with open(os.path.join(lib.job_dir(state, job["id"]), "log.txt"), "wb") as f:
        f.write(b"Error: the vision model found no face in the seed image; pass --force to proceed anyway.\n")
    detail = mt.api(s, "GET", "/api/characters/kyra?ws=" + ws)[2]
    assert detail["face_problem"] is True and detail["last_create_fields"]["seed_upload"] == seed
    status, _h, payload = mt.api(s, "POST", "/api/characters", body=dict(create, name="K", phrase="", seed_upload=None))
    assert (status, payload["error"]) == (400, "invalid fields")
    assert payload["errors"] == ["character name must match [a-z][a-z0-9-]{1,23}", "phrase is required",
                                 "give exactly one of a seed image or a descriptor"]
    assert mt.api(s, "POST", "/api/characters", body=dict(create, seed_upload=None, descriptor="tall"))[2]["errors"] == [
        "a descriptor needs a class noun"]
    status, _h, payload = mt.api(s, "POST", "/api/characters/kyra/train", body={"ws": ws})
    assert (status, payload) == (400, {"error": "invalid fields", "errors": ["choose video, stills or both"]})
    status, _h, payload = mt.api(s, "POST", "/api/characters/kyra/train", body={"ws": ws, "video": True,
                                                                               "force": True})
    train_argv = lib.read_job(lib.job_dir(state, payload["job"]["id"]))["argv"]
    assert status == 201 and os.path.basename(train_argv[0]) == "character-train-vlm"
    assert train_argv[2:] == ["kyra", "--video", "--force"]
    status, _h, payload = mt.api(s, "POST", "/api/characters/kyra/regenerate", body={"ws": ws})
    assert status == 201 and lib.read_job(lib.job_dir(state, payload["job"]["id"]))["argv"][2:] == [
        "create", "kyra", "--regenerate", "--no-review"]
    assert payload["job"]["kind"] == "character-regenerate" and payload["job"]["queue_position"] == 3
    status, _h, payload = mt.api(s, "POST", "/api/characters/kyra/regenerate", body={"ws": ws, "seed": 9})
    assert status == 201 and lib.read_job(lib.job_dir(state, payload["job"]["id"]))["argv"][2:] == [
        "create", "kyra", "--regenerate", "--no-review", "--seed", "9"]
    for bad in ("x", -1, True, 2 ** 31):
        status, _h, payload = mt.api(s, "POST", "/api/characters/kyra/regenerate", body={"ws": ws, "seed": bad})
        assert (status, payload) == (400, {"error": "invalid fields",
                                           "errors": ["seed must be an integer from 0 to 2147483647"]}), bad
    mt.stub_config(ws, {"character show kyra": {"exit": 2, "stderr": "Error: no character kyra\n"}})
    assert mt.api(s, "GET", "/api/characters/kyra?ws=" + ws)[:3:2][0] == 502


def test_mu61_lora_add_rejects_flaglike_and_unsafe_values(env):
    s, ws = env["srv"], env["ws"]
    add = {"ws": ws, "path": "/l/pan.safetensors", "id": "pan", "kind": "motion", "target": "video",
           "base_models": ["M1"], "triggers": ["panshot"], "description": "a pan", "use_when": "pans",
           "avoid_when": "", "default_strength": 0.8, "strength_range": [0.5, 1], "rank": None, "alpha": None}
    for change, error in ((dict(path="rel/x"), "path must be an absolute path"),
                          (dict(description="--force"), "description must not start with '-'"),
                          (dict(triggers=["ok", "-x"]), "triggers must not start with '-'"),
                          (dict(description="a\x00b"), "description contains invalid characters")):
        assert mt.api(s, "POST", "/api/loras", body=dict(add, **change))[:3:2] == (400, {"error": error})


def test_mu65_character_create_errors_flaglike_and_unsafe(env):
    base = {"name": "kyra", "phrase": "the woman", "class_noun": "woman", "descriptor": "tall", "trigger": None,
            "seed": None, "seed_upload": None, "force": False}
    state = env["state"]
    assert srv.character_create_errors(base, state) == []
    for change, error in ((dict(phrase="--x"), "phrase must not start with '-'"),
                          (dict(phrase=" -x"), "phrase must not start with '-'"),
                          (dict(phrase="a\x00b"), "phrase contains invalid characters"),
                          (dict(phrase="a\ud800b"), "phrase contains invalid characters"),
                          (dict(descriptor="-tall"), "descriptor must not start with '-'"),
                          (dict(descriptor="a\x00b"), "descriptor contains invalid characters")):
        assert srv.character_create_errors(dict(base, **change), state) == [error]


def test_fix13_lora_values_nul_and_flag_like(env):
    s, ws = env["srv"], env["ws"]
    got = lambda *a, **k: mt.api(s, *a, **k)[:3:2]
    assert got("POST", "/api/loras/remove", body={"ws": ws, "id": "a\x00b"}) == (
        400, {"error": "id contains invalid characters"})
    assert got("POST", "/api/loras/remove", body={"ws": ws, "id": "-x"}) == (400, {"error": "id must not start with '-'"})
    assert got("POST", "/api/loras/verify", body={"ws": ws, "ids": ["ok", "a\x00b"]}) == (
        400, {"error": "ids contains invalid characters"})
    assert got("POST", "/api/loras/verify", body={"ws": ws, "ids": ["-x"]}) == (
        400, {"error": "ids must not start with '-'"})
    assert got("POST", "/api/loras/verify", body={"ws": ws, "ids": ""}) == (
        400, {"error": "ids must be a list of strings"})
    assert got("GET", "/api/loras?ws=%s&model=a%%00b" % ws) == (400, {"error": "model contains invalid characters"})
    assert got("GET", "/api/loras?ws=%s&model=-x" % ws) == (400, {"error": "model must not start with '-'"})


def test_fix13_upload_wave_riff_refused_and_reupload_keeps_file(env):
    s, state = env["srv"], env["state"]
    wave = b"RIFF\x00\x00\x00\x00WAVEfmt " + b"\x00" * 24
    assert _upload(s, wave, "image/webp")[:3:2] == (400, {"error": "file content is not image/webp"})
    status, _h, payload = _upload(s, mt.PNG, "image/png")
    assert status == 201
    os.utime(payload["path"], (1000000, 1000000))
    status, _h, again = _upload(s, mt.PNG, "image/png")
    assert (status, again) == (201, payload)
    assert os.stat(payload["path"]).st_mtime == 1000000


def test_fix13_lora_action_timeout_is_504(env, monkeypatch):
    def fake(argv, cwd, env=None, timeout=None):
        return {"argv": argv, "exit_code": None, "stdout": "", "stderr": "", "timed_out": True}
    monkeypatch.setattr(lib, "run_light", fake)
    status, _h, payload = mt.api(env["srv"], "POST", "/api/loras/remove", body={"ws": env["ws"], "id": "pan"})
    assert status == 504 and payload["error"].startswith("lora-catalog timed out")


def test_fix13_character_empty_seed_upload_is_none(env):
    base = {"name": "kyra", "phrase": "the woman", "class_noun": "woman", "descriptor": "tall", "trigger": None,
            "seed": None, "seed_upload": "", "force": False}
    assert srv.character_create_errors(base, env["state"]) == []


def _make_story(ws, story_id, text=None, files=()):
    sdir = os.path.join(ws, "generated", "stories", story_id)
    os.makedirs(sdir, exist_ok=True)
    if text is not None:
        with open(os.path.join(sdir, "story.md"), "wb") as f:
            f.write(text.encode("utf-8"))
    for rel, data in files:
        path = os.path.join(sdir, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            f.write(data)
    return sdir


def test_mu69_story_list_and_detail(env):
    s, ws = env["srv"], env["ws"]
    old = _make_story(ws, "old-one", "## Panel 1\n")
    os.utime(old, (1000, 1000))
    checks = {"source": "robust", "hard": [{"id": "N1"}], "advisory": [], "verdict": "ok", "panels": 3}
    sdir = _make_story(ws, "ronin-rescue", "## Panel 1\n", files=[
        ("story_checks.json", json.dumps(checks).encode()), ("plan.json", json.dumps({"mode": "shots", "loras": {
            "global": []}}).encode()), ("images/panel_01.png", b"p"), ("images/panel_02.png", b"p"),
        ("images/seed.png", b"p"), ("clips/panel_01.mp4", b"m"), ("movie.mp4", b"m"),
        ("runs/20261019-a/story_summary.json", b'{"run": "a"}'), ("runs/20261019-b/story_summary.json", b'{"run": "b"}')])
    _make_story(ws, "movie-ui-smoke", "x")
    _make_story(ws, "a..b", "x")
    payload = mt.api(s, "GET", "/api/stories?ws=" + ws)[2]
    assert payload["stories_dir"] == os.path.join(ws, "generated", "stories")
    assert [st["id"] for st in payload["stories"]] == ["ronin-rescue", "old-one"]
    first = payload["stories"][0]
    assert first == {"id": "ronin-rescue", "story_md": True,
                     "checks": {"source": "robust", "hard": 1, "advisory": 0, "verdict": "ok"},
                     "stills": 2, "clips": 1, "movie": True, "mtime": first["mtime"]}
    assert payload["stories"][1]["mtime"] == "1970-01-01T00:16:40Z" and payload["stories"][1]["checks"] is None
    detail = mt.api(s, "GET", "/api/stories/ronin-rescue?ws=" + ws)[2]
    assert detail["dir"] == sdir and detail["story_md"] == {"text": "## Panel 1\n",
                                                            "sha256": hashlib.sha256(b"## Panel 1\n").hexdigest()}
    assert detail["files"] == ["clips", "images", "movie.mp4", "plan.json", "runs", "story.md", "story_checks.json"]
    assert detail["checks"] == checks and detail["plan_mode"] == "shots" and detail["plan_loras"] == {"global": []}
    assert detail["stills"] == [os.path.join(sdir, "images", "panel_01.png"), os.path.join(sdir, "images", "panel_02.png")]
    assert detail["clips"] == [os.path.join(sdir, "clips", "panel_01.mp4")]
    assert detail["movie"] == os.path.join(sdir, "movie.mp4") and detail["summary"] == {"run": "b"}
    assert detail["catalog_loras"] is None and detail["last_fields"] is None
    created = mt.api(s, "POST", "/api/jobs", body=_compose(env, goal="Keep it tense."))[2]
    job = lib.read_job(lib.job_dir(env["state"], created["job"]["id"]))
    assert mt.api(s, "GET", "/api/stories/ronin-rescue?ws=" + ws)[2]["last_fields"] == job["fields"]
    assert job["fields"]["goal"] == "Keep it tense."
    assert mt.api(s, "GET", "/api/stories/nope?ws=" + ws)[0] == 404
    assert mt.api(s, "GET", "/api/stories/a..b?ws=" + ws)[:3:2] == (404, {"error": "not found"})


def test_mut20_story_md_save_backup_and_conflicts(env, monkeypatch):
    s, ws, state = env["srv"], env["ws"], env["state"]
    sdir = _make_story(ws, "ronin-rescue", "v1\n")
    sha1 = hashlib.sha256(b"v1\n").hexdigest()
    put = "/api/stories/ronin-rescue/story.md"
    status, _h, payload = mt.api(s, "PUT", put, body={"ws": ws, "text": "v2\r\n", "base_sha256": sha1})
    assert status == 200 and payload["sha256"] == hashlib.sha256(b"v2\r\n").hexdigest()
    backup = payload["backup"]
    assert re.fullmatch(re.escape(os.path.join(sdir, "story.md.bak-")) + r"[0-9]{8}T[0-9]{6}Z", backup)
    with open(backup, "rb") as f:
        assert f.read() == b"v1\n"
    with open(os.path.join(sdir, "story.md"), "rb") as f:
        assert f.read() == b"v2\r\n"
    status, _h, payload = mt.api(s, "PUT", put, body={"ws": ws, "text": "v3", "base_sha256": sha1})
    assert (status, payload) == (409, {"error": "story.md changed since it was loaded; reload it",
                                       "sha256": hashlib.sha256(b"v2\r\n").hexdigest()})
    sha2 = hashlib.sha256(b"v2\r\n").hexdigest()
    stamp = backup[len(os.path.join(sdir, "story.md.bak-")):]
    original = time.strftime

    def frozen(fmt, *args):
        return stamp if fmt == "%Y%m%dT%H%M%SZ" else original(fmt, *args)
    monkeypatch.setattr(srv.time, "strftime", frozen)
    payload = mt.api(s, "PUT", put, body={"ws": ws, "text": "v3", "base_sha256": sha2})[2]
    assert payload["backup"] == backup + "-2"
    payload = mt.api(s, "PUT", put, body={"ws": ws, "text": "v4", "base_sha256": hashlib.sha256(b"v3").hexdigest()})[2]
    assert payload["backup"] == backup + "-3"
    monkeypatch.setattr(srv.time, "strftime", original)
    fresh = _make_story(ws, "fresh")
    assert mt.api(s, "PUT", "/api/stories/fresh/story.md", body={"ws": ws, "text": "x", "base_sha256": sha1})[0] == 409
    payload = mt.api(s, "PUT", "/api/stories/fresh/story.md", body={"ws": ws, "text": "x", "base_sha256": None})[2]
    assert payload["backup"] is None and os.path.isfile(os.path.join(fresh, "story.md"))
    assert mt.api(s, "PUT", "/api/stories/missing/story.md", body={"ws": ws, "text": "x", "base_sha256": None})[0] == 404
    busy = mt.make_job(state, ["true"], ws, story_id="ronin-rescue", status={
        "state": "running", "dispatched": lib.utc_now(), "runner_pid": 1, "pgid": None, "started": lib.utc_now()})
    status, _h, payload = mt.api(s, "PUT", put, body={"ws": ws, "text": "v5",
                                                      "base_sha256": hashlib.sha256(b"v4").hexdigest()})
    assert (status, payload) == (409, {"error": "story ronin-rescue is in use by job %s" % busy})


def test_mut19_files_roots_ranges_and_token(env):
    s, ws, state = env["srv"], env["ws"], env["state"]
    data = bytes(range(100))
    sdir = _make_story(ws, "ronin-rescue", files=[("clips/panel_01.mp4", data)])
    clip = os.path.join(sdir, "clips", "panel_01.mp4")
    outside = os.path.join(env["tmp"], "secret.txt")
    with open(outside, "w") as f:
        f.write("secret")
    os.symlink(outside, os.path.join(sdir, "link.txt"))

    def get(path, token=mt.TOKEN, headers=None, t=None):
        url = "/files?ws=%s&path=%s" % (ws, path) + ("&t=%s" % t if t else "")
        return mt.api(s, "GET", url, token=token, headers=headers)
    status, headers, body = get(clip)
    assert (status, body) == (200, data)
    assert headers["content-type"] == "video/mp4" and headers["accept-ranges"] == "bytes"
    assert headers["x-content-type-options"] == "nosniff" and headers["cache-control"] == "no-store"
    assert get(clip, token=None)[0] == 401
    assert get(clip, token=None, t="wrong")[0] == 401
    assert get(clip, token=None, t=mt.TOKEN)[:3:2] == (200, data)
    assert get(os.path.join(sdir, "..", "..", "..", "..", "secret.txt"))[:3:2] == (403, {"error": "path not allowed"})
    assert get(os.path.join(sdir, "link.txt"))[:3:2] == (403, {"error": "path not allowed"})
    assert get(os.path.join(ws, "generated"))[0] == 403
    assert get(os.path.join(sdir, "nope.mp4"))[0] == 404
    for rng, start, end in (("bytes=0-9", 0, 9), ("bytes=10-", 10, 99), ("bytes=-5", 95, 99), ("bytes=90-500", 90, 99)):
        status, headers, body = get(clip, headers={"Range": rng})
        assert (status, body) == (206, data[start:end + 1]), rng
        assert headers["content-range"] == "bytes %d-%d/100" % (start, end)
        assert headers["content-length"] == str(end - start + 1)
    for rng in ("bytes=100-", "bytes=9-3", "bytes=-0"):
        status, headers, body = get(clip, headers={"Range": rng})
        assert (status, headers["content-range"], body) == (416, "bytes */100", b""), rng
    for rng in ("items=0-1", "bytes=0-1,5-6", "bytes=-"):
        assert get(clip, headers={"Range": rng})[:3:2] == (200, data), rng
    upload = _upload(s, mt.PNG, "image/png")[2]["path"]
    status, headers, body = get(upload)
    assert (status, headers["content-type"], body) == (200, "image/png", mt.PNG)


def test_review_focus_1_non_ascii_story_round_trip(env):
    """Review Focus 1: a narrative and a story.md edit with accents, CJK and emoji."""
    s, ws = env["srv"], env["ws"]
    narrative = "Ein Rōnin rettet ein Kind — 子供を救う 🔥"
    preview = mt.api(s, "POST", "/api/preview", body=_compose(env, narrative=narrative))[2]
    assert preview["argv"][2] == narrative
    sdir = _make_story(ws, "ronin-rescue", "## Panel 1 — Café\n")
    detail = mt.api(s, "GET", "/api/stories/ronin-rescue?ws=" + ws)[2]
    assert detail["story_md"]["text"] == "## Panel 1 — Café\n"
    text = detail["story_md"]["text"] + "Image: 夜の市場、提灯 🏮\n"
    payload = mt.api(s, "PUT", "/api/stories/ronin-rescue/story.md",
                     body={"ws": ws, "text": text, "base_sha256": detail["story_md"]["sha256"]})[2]
    with open(os.path.join(sdir, "story.md"), "rb") as f:
        assert f.read() == text.encode("utf-8")
    again = mt.api(s, "GET", "/api/stories/ronin-rescue?ws=" + ws)[2]["story_md"]
    assert again == {"text": text, "sha256": payload["sha256"]}


def test_review_focus_2_files_with_spaces_and_non_ascii_names(env):
    """Review Focus 2: the page percent-encodes paths such as ".../My Movies/café still.png"."""
    s = env["srv"]
    ws = os.path.join(env["tmp"], "My Movies", "ws é")
    shutil.copytree(env["ws"], ws, symlinks=True)
    ws = os.path.realpath(ws)
    sdir = _make_story(ws, "ronin-rescue", files=[("images/café still+1.png", mt.PNG)])

    def enc(text):
        return "".join(c if (c.isascii() and c.isalnum()) or c in "/-_." else "".join("%%%02X" % b for b in c.encode("utf-8"))
                       for c in text)
    path = os.path.join(sdir, "images", "café still+1.png")
    status, headers, body = mt.api(s, "GET", "/files?ws=%s&path=%s" % (enc(ws), enc(path)))
    assert (status, headers["content-type"], body) == (200, "image/png", mt.PNG)
    assert mt.api(s, "GET", "/api/stories?ws=" + enc(ws))[2]["stories"][0]["id"] == "ronin-rescue"


def test_t14_fix_files_unreadable_gives_clean_403(env):
    if os.geteuid() == 0:
        pytest.skip("root ignores file modes")
    s, ws = env["srv"], env["ws"]
    sdir = _make_story(ws, "ronin-rescue", files=[("clips/locked.mp4", b"data")])
    locked = os.path.join(sdir, "clips", "locked.mp4")
    os.chmod(locked, 0)
    try:
        status, _h, payload = mt.api(s, "GET", "/files?ws=%s&path=%s" % (ws, locked))
    finally:
        os.chmod(locked, 0o644)
    assert (status, payload) == (403, {"error": "path not allowed"})


def test_t14_fix_files_prefix_sibling_and_nul(env):
    s, ws = env["srv"], env["ws"]
    evil = os.path.join(ws, "generated-evil")
    os.makedirs(evil)
    with open(os.path.join(evil, "x.png"), "wb") as f:
        f.write(mt.PNG)
    assert mt.api(s, "GET", "/files?ws=%s&path=%s" % (ws, os.path.join(evil, "x.png")))[0] == 403
    assert mt.api(s, "GET", "/files?ws=%s&path=%s/generated/a%%00b.png" % (ws, ws))[0] == 404


def test_t14_fix_huge_range_numbers(env):
    s, ws = env["srv"], env["ws"]
    sdir = _make_story(ws, "ronin-rescue", files=[("clips/panel_01.mp4", bytes(range(100)))])
    url = "/files?ws=%s&path=%s" % (ws, os.path.join(sdir, "clips", "panel_01.mp4"))
    status, headers, _b = mt.api(s, "GET", url, headers={"Range": "bytes=" + "9" * 5000 + "-"})
    assert (status, headers["content-range"]) == (416, "bytes */100")
    status, headers, body = mt.api(s, "GET", url, headers={"Range": "bytes=0-" + "9" * 5000})
    assert (status, len(body)) == (206, 100)
    assert mt.api(s, "GET", url, headers={"Range": "bytes=0005-0007"})[2] == bytes(range(5, 8))


def test_t14_fix_story_json_never_500(env):
    s, ws = env["srv"], env["ws"]
    _make_story(ws, "ronin-rescue", "x", files=[
        ("runs/r1/story_summary.json", b'{"score": NaN}'), ("plan.json", b"\xff\xfe"),
        ("story_checks.json", b'{"hard": [], "advisory": [], "verdict": NaN}')])
    detail = mt.api(s, "GET", "/api/stories/ronin-rescue?ws=" + ws)
    assert detail[0] == 200 and detail[2]["summary"] is None and detail[2]["checks"] is None
    assert detail[2]["plan_mode"] is None
    listing = mt.api(s, "GET", "/api/stories?ws=" + ws)
    assert listing[0] == 200 and listing[2]["stories"][0]["checks"] is None


def test_t14_fix_story_symlink_escapes(env):
    s, ws = env["srv"], env["ws"]
    outside = os.path.join(env["tmp"], "outside-story")
    os.makedirs(outside)
    with open(os.path.join(outside, "story.md"), "wb") as f:
        f.write(b"outside")
    stories = os.path.join(ws, "generated", "stories")
    os.makedirs(stories, exist_ok=True)
    os.symlink(outside, os.path.join(stories, "evil"))
    assert mt.api(s, "GET", "/api/stories/evil?ws=" + ws)[0] == 404
    status = mt.api(s, "PUT", "/api/stories/evil/story.md", body={
        "ws": ws, "text": "pwn", "base_sha256": hashlib.sha256(b"outside").hexdigest()})[0]
    assert status == 404
    assert [st["id"] for st in mt.api(s, "GET", "/api/stories?ws=" + ws)[2]["stories"]] == []
    with open(os.path.join(outside, "story.md"), "rb") as f:
        assert f.read() == b"outside"
    # story.md itself a symlink out of its story dir
    sdir = _make_story(ws, "ronin-rescue")
    target = os.path.join(env["tmp"], "outside-file.md")
    with open(target, "wb") as f:
        f.write(b"secret")
    os.symlink(target, os.path.join(sdir, "story.md"))
    detail = mt.api(s, "GET", "/api/stories/ronin-rescue?ws=" + ws)[2]
    assert detail["story_md"] is None
    assert mt.api(s, "GET", "/api/stories?ws=" + ws)[2]["stories"][0]["story_md"] is False
    for base in (None, hashlib.sha256(b"secret").hexdigest()):
        assert mt.api(s, "PUT", "/api/stories/ronin-rescue/story.md",
                      body={"ws": ws, "text": "pwn", "base_sha256": base})[0] == 404
    with open(target, "rb") as f:
        assert f.read() == b"secret"


PAGE_HEADERS = {
    "content-security-policy": ("default-src 'self'; img-src 'self' blob:; media-src 'self'; object-src 'none'; "
                                "base-uri 'none'; frame-ancestors 'none'; form-action 'self'"),
    "x-frame-options": "DENY", "x-content-type-options": "nosniff", "referrer-policy": "no-referrer",
    "cache-control": "no-store"}


def test_mut24_page_headers_and_asset_rules(env):
    s = env["srv"]
    static = os.path.join(mt.WS, "static", "movie-ui")
    for path, name, ctype in (("/", "index.html", "text/html; charset=utf-8"),
                              ("/static/app.js", "app.js", "text/javascript; charset=utf-8"),
                              ("/static/app.css", "app.css", "text/css; charset=utf-8")):
        status, headers, body = mt.api(s, "GET", path, token=None)
        assert status == 200 and headers["content-type"] == ctype
        for key, value in PAGE_HEADERS.items():
            assert headers[key] == value, (path, key)
        with open(os.path.join(static, name), "rb") as f:
            assert body == f.read()
        text = body.decode("utf-8")
        for pattern in (r"https?://", r"\son[a-z]+=", r"style=", r"\balert\(", r"\bconfirm\(", r"\bprompt\(",
                        r"\beval\(", r"new Function"):
            assert not re.search(pattern, text), (name, pattern)
    html = mt.api(s, "GET", "/", token=None)[2].decode("utf-8")
    assert re.findall(r"<script[^>]*>", html) == ['<script src="/static/app.js" defer>']
    assert "<script src=\"/static/app.js\" defer></script>" in html
    assert html.count('<link rel="stylesheet" href="/static/app.css">') == 1
    for element in ("banner", "ws-select", "ws-typed", "ws-typed-use", "badge-render", "badge-stills", "badge-story",
                    "badge-reasons", "badge-refresh", "badge-apikey", "header-job", "header-queue", "confirm",
                    "confirm-text", "confirm-yes", "confirm-no", "c-command", "c-errors", "c-checks", "s-editor",
                    "j-log", "t-waterfall"):
        assert 'id="%s"' % element in html, element
    for tab in ("compose", "stories", "characters", "loras", "jobs", "traces"):
        assert 'id="tab-%s"' % tab in html and 'id="panel-%s"' % tab in html
    css = mt.api(s, "GET", "/static/app.css", token=None)[2].decode("utf-8")
    assert "@media (prefers-color-scheme: dark)" in css
    assert mt.api(s, "POST", "/", body={}, token=None)[0] == 404


def test_mut14_smoke_job_runs_the_stub_render_and_deletes_its_directory(env, monkeypatch, tmp_path):
    mt.smoke_host(monkeypatch, tmp_path)
    s, state = env["srv"], env["state"]
    status, _h, payload = mt.api(s, "POST", "/api/jobs", body=_compose(env, action="smoke"))
    assert status == 201, payload
    job = payload["job"]
    assert (job["kind"], job["story_id"], job["character"]) == ("smoke", None, None)
    sdir = os.path.join(state, "smoke", job["id"])
    assert os.path.isfile(os.path.join(sdir, "manifest.json"))
    preview = mt.api(s, "POST", "/api/preview", body=_compose(env, action="smoke"))[2]
    assert preview == {"argv": None, "command": None, "errors": []}
    assert lib.dispatch_tick(state, mt.WS) == job["id"]
    mt.wait_until(lambda: mt.status_of(state, job["id"]).get("state") == "done", 20)
    detail = mt.api(s, "GET", "/api/jobs/%s" % job["id"])[2]
    clip = os.path.join(sdir, "clips", "panel_01.mp4")
    assert detail["progress"]["kind"] == "smoke"
    assert detail["progress"]["smoke"] == {"clip": clip, "clip_ok": True}
    call = [c for c in mt.stub_calls(env["ws"]) if c["tool"] == "ltx-mlx-render"][-1]
    assert call["argv"][:2] == [os.path.join(sdir, "manifest.json"), os.path.join(sdir, "smoke.mp4")]
    assert mt.api(s, "DELETE", "/api/jobs/%s" % job["id"])[:3:2] == (200, {"deleted": job["id"]})
    assert not os.path.exists(sdir) and not os.path.exists(lib.job_dir(state, job["id"]))


def test_final1_story_save_unreadable_story_is_409(env):
    if os.geteuid() == 0:
        pytest.skip("root can read mode-000 files")
    s, ws = env["srv"], env["ws"]
    sdir = _make_story(ws, "ronin-rescue", "ORIGINAL")
    path = os.path.join(sdir, "story.md")
    os.chmod(path, 0)
    try:
        status, _h, payload = mt.api(s, "PUT", "/api/stories/ronin-rescue/story.md",
                                     body={"ws": ws, "text": "NEW", "base_sha256": None})
    finally:
        os.chmod(path, 0o644)
    assert status == 409
    assert payload == {"error": "story.md exists but cannot be read; fix its permissions and reload", "sha256": None}
    with open(path, "rb") as f:
        assert f.read() == b"ORIGINAL"
    assert not [n for n in os.listdir(sdir) if n.startswith("story.md.bak-")]


def test_final3_unencodable_api_error_message_is_replaced(env, monkeypatch):
    def boom(self, groups, query, body):
        raise srv.ApiError(502, "bad \udcff", run={"argv": ["\udcff"]})
    monkeypatch.setattr(srv.MovieUIHandler, "h_models", boom)
    status, _h, payload = mt.api(env["srv"], "GET", "/api/models?ws=" + env["ws"])
    assert (status, payload) == (502, {"error": "bad ?"})


def test_final4_lora_action_timeouts(env, monkeypatch):
    seen = []

    def fake(argv, cwd, env=None, timeout=None):
        seen.append(timeout)
        return {"argv": argv, "exit_code": None, "stdout": "", "stderr": "", "timed_out": True}
    monkeypatch.setattr(lib, "run_light", fake)
    s, ws = env["srv"], env["ws"]
    status, _h, payload = mt.api(s, "POST", "/api/loras/verify", body={"ws": ws, "ids": ["pan"]})
    assert status == 504 and payload["error"] == "lora-catalog timed out after 300 s"
    status = mt.api(s, "POST", "/api/loras/remove", body={"ws": ws, "id": "pan"})[0]
    assert status == 504
    body = {"ws": ws, "path": "/x.safetensors", "id": "pan", "kind": "style", "target": "video",
            "base_models": ["m"], "triggers": [], "description": "d", "use_when": "u",
            "default_strength": 0.8, "strength_range": [0.2, 1.0]}
    assert mt.api(s, "POST", "/api/loras", body=body)[0] == 504
    assert seen == [lib.VERIFY_TIMEOUT, lib.LIGHT_TIMEOUT, lib.VERIFY_TIMEOUT]


def test_choose_token_env_override():
    # unset -> fresh random, no note
    tok, note = srv.choose_token({})
    assert note is None and re.fullmatch(r"[A-Za-z0-9_-]{16,}", tok)
    # valid MOVIE_UI_TOKEN -> reused verbatim (stable URL across restarts)
    tok, note = srv.choose_token({"MOVIE_UI_TOKEN": "my-stable-range-token-123"})
    assert tok == "my-stable-range-token-123" and note is None
    # set-but-invalid -> ignored (random) with a note
    tok, note = srv.choose_token({"MOVIE_UI_TOKEN": "short"})
    assert tok != "short" and note and "MOVIE_UI_TOKEN" in note
    # whitespace/empty -> treated as unset
    tok, note = srv.choose_token({"MOVIE_UI_TOKEN": "   "})
    assert note is None and re.fullmatch(r"[A-Za-z0-9_-]{16,}", tok)
    # two random tokens differ
    assert srv.choose_token({})[0] != srv.choose_token({})[0]


def test_regenerate_seed_field_is_wired_in_the_static_ui():
    static = os.path.join(mt.WS, "static", "movie-ui")
    with open(os.path.join(static, "index.html"), encoding="utf-8") as f:
        html = f.read()
    with open(os.path.join(static, "app.js"), encoding="utf-8") as f:
        js = f.read()
    assert 'id="ch-regen-seed"' in html and 'max="2147483647"' in html
    assert html.index('id="ch-regen-seed"') < html.index('id="ch-regenerate"')
    assert "seed:" in js and "#ch-regen-seed" in js and "% 2147483648" in js


# --- batch forks (docs/superpowers/specs/2026-10-30-batch-forks-design.md, Section 7) ----------

def test_bt15_batch_story_eligibility(env):
    s, state, ws = env["srv"], env["state"], env["ws"]
    os.makedirs(lib.story_dir(ws, "cli-story"))
    with open(os.path.join(lib.story_dir(ws, "cli-story"), "story.md"), "w", encoding="utf-8") as f:
        f.write(bt.STORY_MD)
    _sdir, queued = bt.original(state, ws, "queued-story", job_state="queued")
    _sdir, running = bt.original(state, ws, "running-story", job_state="running")
    bt.original(state, ws, "ui-story")
    status, _h, payload = mt.api(s, "GET", "/api/batches/stories?ws=" + ws)
    assert status == 200
    rows = dict((r["id"], r) for r in payload["stories"])
    assert sorted(rows) == ["cli-story", "queued-story", "running-story", "ui-story"]
    assert rows["cli-story"] == {"id": "cli-story", "eligible": False,
                                 "reason": "Started from the command line: no saved Compose settings to fork",
                                 "busy_job": None, "fields_source": None, "fields_batch": None}
    for story_id, job_id in (("queued-story", queued), ("running-story", running)):
        assert rows[story_id] == {"id": story_id, "eligible": False,
                                  "reason": "Job %s is queued or running for this story" % job_id,
                                  "busy_job": job_id, "fields_source": "job", "fields_batch": None}
    assert rows["ui-story"] == {"id": "ui-story", "eligible": True, "reason": None, "busy_job": None,
                                "fields_source": "job", "fields_batch": None}
    assert mt.api(s, "GET", "/api/batches/stories")[:3:2] == (400, {"error": "missing ws"})


def test_batch_review_focus_2_saved_settings_that_no_longer_pass_v1(env):
    """Review Focus 2: the original's saved seed image is gone from STATE/uploads."""
    s, state, ws = env["srv"], env["state"], env["ws"]
    gone = "0" * 64 + ".png"
    bt.original(state, ws, "seeded", seed_upload=gone)
    status, _h, payload = mt.api(s, "POST", "/api/batches/preview",
                                 body=bt.body(ws, ["seeded"], [bt.variant("v1", bt.RENDER)]))
    assert status == 200
    assert payload["cells"] == [{"story_id": "seeded", "variant": 1, "fork_id": "seeded-b1-v1",
                                 "status": "invalid", "reason": "seed image upload %s not found" % gone,
                                 "level": None, "diff": [], "warnings": []}]
    assert payload["totals"] == {"jobs": 0, "replan": 0, "stills": 0, "render": 0, "refused": 1,
                                 "text": "0 jobs: 0 re-plan, 0 new stills, 0 render-only; 1 refused"}
    assert payload["number"] == 1 and payload["rows"][0]["fields"]["seed_upload"] == gone
    assert (payload["rows"][0]["fields_source"], payload["rows"][0]["movie"]) == ("job", None)
    assert os.listdir(os.path.join(state, "batches")) == []
    assert not os.path.lexists(lib.story_dir(ws, "seeded-b1-v1"))
    status, _h, payload = mt.api(s, "POST", "/api/batches/preview", body={"ws": ws, "stories": [], "variants": []})
    assert (status, payload) == (400, {"error": "invalid batch", "errors": [
        "stories must be a list of 1 to 24 distinct story IDs", "variants must be a list of 1 to 6 variants"]})
    assert mt.api(s, "POST", "/api/batches/preview", body={"stories": ["seeded"]})[:3:2] == (
        400, {"error": "missing ws"})


RICH_FILES = {"story.md": bt.STORY_MD.encode("utf-8"), "plan.json": b'{"schema": "ltx-movie.plan.v1"}',
              "story_checks.json": b'{"hard": [], "advisory": []}', "manifest.json": b'{"panels": []}',
              "images/panel_01.png": mt.PNG, "images/images.json": b"{}",
              "clips/panel_01.mp4": b"\x00\x00\x00\x18ftypmp42",
              "clips/panel_01.mp4.provenance.json": b'{"output_sha256": "x"}', "movie.mp4": b"movie"}


def test_bt16_preview_equals_submit(env, monkeypatch):
    s, state, ws = env["srv"], env["state"], env["ws"]
    bt.passing_checks(monkeypatch)
    bt.original(state, ws, "ronin-rescue")
    bt.original(state, ws, "harbour-chase")
    variants = [bt.variant("v1", bt.RENDER), bt.variant("v2", {"goal": "Keep it tense."}, replace=[("dusk", "dawn")]),
                bt.variant("v3", {})]
    req = bt.body(ws, ["ronin-rescue", "harbour-chase"], variants)
    preview = mt.api(s, "POST", "/api/batches/preview", body=req)[2]
    batch_id = bt.submit(s, ws, req["stories"], variants)
    bt.wait_status(s, batch_id)
    rec = bt.record(state, batch_id)
    keys = ("fork_id", "level", "diff", "warnings")
    assert [[c[k] for k in keys] for c in rec["cells"]] == [[c[k] for k in keys] for c in preview["cells"]]
    assert [c["status"] for c in rec["cells"]] == ["queued", "queued", "refused"] * 2
    assert preview["cells"][1]["warnings"] == ['find text not in this prompt: "dusk"']
    assert preview["totals"]["text"] == "4 jobs: 2 re-plan, 0 new stills, 2 render-only; 2 refused"
    assert rec["number"] == preview["number"] == 1 and rec["workspace"] == ws and rec["cancel_requested"] is False
    assert rec["schema"] == "movie-ui.batch.v1" and rec["stories"] == req["stories"]


def test_bt17_queue_order_after_the_existing_queue(env, monkeypatch):
    s, state, ws = env["srv"], env["state"], env["ws"]
    bt.passing_checks(monkeypatch)
    bt.original(state, ws, "s1")
    bt.original(state, ws, "s2")
    other = mt.make_job(state, ["true"], ws, story_id="unrelated")
    variants = [bt.variant("v1", bt.RENDER), bt.variant("v2", {"goal": "Keep it tense."}),
                bt.variant("v3", {"width": 768, "height": 512})]
    batch_id = bt.submit(s, ws, ["s1", "s2"], variants)
    bt.wait_status(s, batch_id)
    rec = bt.record(state, batch_id)
    assert [c["level"] for c in rec["cells"]] == ["render", "replan", "stills"] * 2
    assert rec["order"] == [1, 4, 2, 5, 0, 3]
    assert lib.read_queue(state) == [other] + [rec["cells"][i]["job_id"] for i in (1, 4, 2, 5, 0, 3)]


def test_bt18_a_cell_that_fails_v6_leaves_no_folder(env, monkeypatch):
    s, state, ws = env["srv"], env["state"], env["ws"]
    bt.passing_checks(monkeypatch, fail={"ronin-rescue-b1-v1": "Error: the dry run failed"})
    bt.original(state, ws, "ronin-rescue")
    batch_id = bt.submit(s, ws, ["ronin-rescue"], [bt.variant("v1", bt.RENDER),
                                                   bt.variant("v2", {"gemma": bt.OTHER_GEMMA})])
    bt.wait_status(s, batch_id)
    cells = bt.record(state, batch_id)["cells"]
    assert (cells[0]["status"], cells[0]["reason"]) == ("refused", "V6 dry run: Error: the dry run failed")
    assert not os.path.lexists(lib.story_dir(ws, "ronin-rescue-b1-v1"))
    assert cells[1]["status"] == "queued" and os.path.isdir(lib.story_dir(ws, "ronin-rescue-b1-v2"))
    assert lib.read_queue(state) == [cells[1]["job_id"]]


def test_bt19_a_job_queued_between_preview_and_submit(env, monkeypatch):
    s, state, ws = env["srv"], env["state"], env["ws"]
    bt.passing_checks(monkeypatch)
    bt.original(state, ws, "ronin-rescue")
    bt.original(state, ws, "harbour-chase")
    req = bt.body(ws, ["ronin-rescue", "harbour-chase"], [bt.variant("v1", bt.RENDER)])
    assert [c["status"] for c in mt.api(s, "POST", "/api/batches/preview", body=req)[2]["cells"]] == ["ok", "ok"]
    late = mt.make_job(state, ["true"], ws, story_id="ronin-rescue",
                       fields=mt.fields(ws, action="movie", story_id="ronin-rescue"))
    batch_id = bt.submit(s, ws, req["stories"], req["variants"])
    bt.wait_status(s, batch_id)
    cells = bt.record(state, batch_id)["cells"]
    assert (cells[0]["status"], cells[0]["reason"]) == (
        "refused", "story ronin-rescue has a job queued or running (job %s)" % late)
    assert cells[1]["status"] == "queued" and not os.path.lexists(lib.story_dir(ws, "ronin-rescue-b1-v1"))


def test_bt22_every_cell_identical_is_409_and_writes_nothing(env):
    s, state, ws = env["srv"], env["state"], env["ws"]
    bt.original(state, ws, "ronin-rescue")
    status, _h, payload = mt.api(s, "POST", "/api/batches", body=bt.body(
        ws, ["ronin-rescue"], [bt.variant("v1", {}), bt.variant("v2", {}, append="   ")]))
    assert status == 409 and payload["error"] == "every cell was refused"
    assert [c["reason"] for c in payload["cells"]] == [
        "same settings and prompt as the original; nothing to compare"] * 2
    assert os.listdir(os.path.join(state, "batches")) == []


def test_bt23_not_enough_free_space(env, monkeypatch):
    s, state, ws = env["srv"], env["state"], env["ws"]
    bt.passing_checks(monkeypatch)
    bt.original(state, ws, "ronin-rescue")

    class Usage(object):
        total, used, free = 100 * 1024 ** 3, 80 * 1024 ** 3, 20 * 1024 ** 3
    monkeypatch.setattr(srv.shutil, "disk_usage", lambda path: Usage())
    batch_id = bt.submit(s, ws, ["ronin-rescue"], [bt.variant("v1", bt.RENDER)])
    bt.wait_status(s, batch_id)
    cell = bt.record(state, batch_id)["cells"][0]
    assert (cell["status"], cell["reason"]) == ("refused", "not enough free space: 20.0 GiB free, this fork "
                                                           "copies 0.0 GiB and at least 20 GiB must stay free")
    assert cell["copy_bytes"] == len(bt.STORY_MD) and not os.path.lexists(lib.story_dir(ws, cell["fork_id"]))


def test_bt24_a_render_fork_runs_on_the_copied_story(env, monkeypatch):
    s, state, ws = env["srv"], env["state"], env["ws"]
    bt.passing_checks(monkeypatch)
    mt.stub_config(ws, {"ltx-movie run": {"stdout": "=== Phase 1: story ===\n"}})
    sdir, _job = bt.original(state, ws, "ronin-rescue", files=RICH_FILES)
    batch_id = bt.submit(s, ws, ["ronin-rescue"], [bt.variant("v1", bt.RENDER)])
    cell = bt.wait_status(s, batch_id)["batch"]["cells"][0]
    fork = lib.story_dir(ws, cell["fork_id"])
    bt.run_job(state, cell["job_id"])
    copied = bt.tree_digests(fork)
    fork_json = lib.read_json(os.path.join(fork, "fork.json"))
    assert copied.pop("fork.json")
    original = bt.tree_digests(sdir)
    assert copied == dict((rel, original[rel]) for rel in original if rel != "movie.mp4")
    assert fork_json == {"schema": "movie-ui.fork.v1", "fork_id": cell["fork_id"], "source_story": "ronin-rescue",
                         "batch": batch_id, "variant": 1, "label": "v1", "level": "render",
                         "diff": [{"key": "model", "from": lib.DEFAULT_MODEL, "to": bt.OTHER_MODEL}],
                         "created": fork_json["created"]}
    runs = [c["argv"] for c in mt.stub_calls(ws) if c["tool"] == "ltx-movie" and c["sub"] == "run"]
    expected = lib.build_argv(mt.fields(ws, action="movie", story_id="ronin-rescue"), ws, state)[2:]
    expected[expected.index("--story-id") + 1] = cell["fork_id"]
    expected[expected.index("--model") + 1] = bt.OTHER_MODEL
    assert runs == [expected]


def test_bt25_the_original_is_byte_identical_after_its_forks_ran(env, monkeypatch):
    s, state, ws = env["srv"], env["state"], env["ws"]
    bt.passing_checks(monkeypatch)
    sdir, _job = bt.original(state, ws, "ronin-rescue", files=RICH_FILES)
    before = bt.tree_digests(sdir)
    batch_id = bt.submit(s, ws, ["ronin-rescue"], [bt.variant("v1", bt.RENDER),
                                                   bt.variant("v2", {"width": 768, "height": 512})])
    for cell in bt.wait_status(s, batch_id)["batch"]["cells"]:
        bt.run_job(state, cell["job_id"])
        assert os.path.isfile(os.path.join(lib.story_dir(ws, cell["fork_id"]), "movie.mp4"))
    assert bt.tree_digests(sdir) == before


def test_bt26_checks_run_with_no_lock_held(env, monkeypatch):
    s, state, ws = env["srv"], env["state"], env["ws"]
    seen = []

    def grab(lock, out):
        got = lock.acquire(timeout=1)
        out.append(got)
        if got:
            lock.release()

    def wrapped(fields, ws_real, state_dir, py=None):
        observed = {}
        for key, lock in (("store_acquired", srv.STORE_LOCK), ("batch_acquired", srv.BATCH_LOCK)):
            got = []
            other = threading.Thread(target=grab, args=(lock, got))
            other.start()
            other.join(5)
            observed[key] = got == [True]
        seen.append(observed)
        return [lib.check("V1", "fields", "pass")]
    monkeypatch.setattr(lib, "run_checks", wrapped)
    bt.original(state, ws, "ronin-rescue")
    batch_id = bt.submit(s, ws, ["ronin-rescue"], [bt.variant("v1", bt.RENDER)])
    bt.wait_status(s, batch_id)
    assert seen == [{"store_acquired": True, "batch_acquired": True}]
    assert bt.record(state, batch_id)["cells"][0]["status"] == "queued"


def _fallback_fork(env, monkeypatch, delete_job=True):
    """BT32's state: a 1 x 1 Render batch whose fork job ran to done and (delete_job) was deleted.
    Returns (batch ID, fork ID, the fork's job ID)."""
    s, state, ws = env["srv"], env["state"], env["ws"]
    bt.passing_checks(monkeypatch)
    bt.original(state, ws, "ronin-rescue")
    batch_id = bt.submit(s, ws, ["ronin-rescue"], [bt.variant("v1", bt.RENDER)])
    cell = bt.wait_status(s, batch_id)["batch"]["cells"][0]
    bt.run_job(state, cell["job_id"])
    if delete_job:
        assert mt.api(s, "DELETE", "/api/jobs/" + cell["job_id"])[:3:2] == (200, {"deleted": cell["job_id"]})
    return batch_id, cell["fork_id"], cell["job_id"]


def _stories(env):
    return dict((r["id"], r) for r in mt.api(env["srv"], "GET", "/api/batches/stories?ws=" + env["ws"])[2]["stories"])


def test_bt32_a_fork_whose_job_was_deleted_uses_its_batch_cell(env, monkeypatch):
    s, state, ws = env["srv"], env["state"], env["ws"]
    batch_id, fork, _job = _fallback_fork(env, monkeypatch)
    assert _stories(env)[fork] == {"id": fork, "eligible": True, "reason": None, "busy_job": None,
                                   "fields_source": "batch", "fields_batch": {"id": batch_id, "number": 1}}
    gemma = [bt.variant("v1", {"gemma": bt.OTHER_GEMMA})]
    preview = mt.api(s, "POST", "/api/batches/preview", body=bt.body(ws, [fork], gemma))[2]
    row = preview["rows"][0]
    assert (row["fields_source"], row["fields_batch"]) == ("batch", {"id": batch_id, "number": 1})
    assert row["fields"]["model"] == bt.OTHER_MODEL and row["movie"] == os.path.join(lib.story_dir(ws, fork), "movie.mp4")
    view = mt.api(s, "GET", "/api/batches/" + batch_id)[2]["view"]
    assert view["cells"] == [{"state": "job deleted", "job": None, "dir": True,
                              "movie": os.path.join(lib.story_dir(ws, fork), "movie.mp4")}]
    second = bt.submit(s, ws, [fork], gemma)
    cell = bt.wait_status(s, second)["batch"]["cells"][0]
    assert (cell["status"], cell["fork_id"]) == ("queued", fork + "-b2-v1")
    fields = lib.read_job(lib.job_dir(state, cell["job_id"]))["fields"]
    assert (fields["model"], fields["gemma"], fields["story_id"]) == (bt.OTHER_MODEL, bt.OTHER_GEMMA, fork + "-b2-v1")


def test_bt33_last_fields_win_over_the_batch_cell(env, monkeypatch):
    s, state, ws = env["srv"], env["state"], env["ws"]
    batch_id, fork, _job = _fallback_fork(env, monkeypatch, delete_job=False)
    rec = bt.record(state, batch_id)
    rec["cells"][0]["fields"]["model"] = "/models/rewritten"
    lib.write_json_atomic(os.path.join(state, "batches", batch_id, "batch.json"), rec)
    assert _stories(env)[fork] == {"id": fork, "eligible": True, "reason": None, "busy_job": None,
                                   "fields_source": "job", "fields_batch": None}
    preview = mt.api(s, "POST", "/api/batches/preview",
                     body=bt.body(ws, [fork], [bt.variant("v1", {"gemma": bt.OTHER_GEMMA})]))[2]
    assert preview["rows"][0]["fields"]["model"] == bt.OTHER_MODEL
    assert (preview["rows"][0]["fields_source"], preview["rows"][0]["fields_batch"]) == ("job", None)


MISMATCH_REASON = ("Its job was deleted and batch %s has no matching record of this fork: no saved Compose "
                   "settings to fork")


@pytest.mark.parametrize("case", ["no-fork-json", "cell-cancelled", "other-workspace", "variant-2"])
def test_bt34_a_missing_or_mismatched_record_leaves_the_fork_ineligible(env, monkeypatch, case):
    s, state, ws = env["srv"], env["state"], env["ws"]
    batch_id, fork, _job = _fallback_fork(env, monkeypatch)
    fork_json = os.path.join(lib.story_dir(ws, fork), "fork.json")
    if case == "no-fork-json":
        os.unlink(fork_json)
        reason = "Started from the command line: no saved Compose settings to fork"
        refusal = "story %s has no saved Compose settings (it was started from the command line)" % fork
    else:
        path = fork_json if case == "variant-2" else os.path.join(state, "batches", batch_id, "batch.json")
        data = lib.read_json(path)
        if case == "cell-cancelled":
            data["cells"][0]["status"] = "cancelled"
        elif case == "other-workspace":
            data["workspace"] = "/elsewhere/qwen-agent-workspace"
        else:
            data["variant"] = 2
        lib.write_json_atomic(path, data)
        reason = MISMATCH_REASON % batch_id
        refusal = ("story %s has no saved Compose settings (its job was deleted and batch %s has no matching "
                   "record of it)" % (fork, batch_id))
    assert _stories(env)[fork] == {"id": fork, "eligible": False, "reason": reason, "busy_job": None,
                                   "fields_source": None, "fields_batch": None}
    preview = mt.api(s, "POST", "/api/batches/preview",
                     body=bt.body(ws, [fork], [bt.variant("v1", {"gemma": bt.OTHER_GEMMA})]))[2]
    assert preview["rows"][0]["fields"] is None and preview["rows"][0]["fields_source"] is None
    assert (preview["cells"][0]["status"], preview["cells"][0]["reason"]) == ("refused", refusal)


def test_batch_review_focus_1_non_ascii_labels_and_prompt_edits(env, monkeypatch):
    """Review Focus 1: a label, find/replace text and an appended paragraph with accents and symbols."""
    s, state, ws = env["srv"], env["state"], env["ws"]
    bt.passing_checks(monkeypatch)
    narrative = "A ronin rescues a child at dusk — before the café burns."
    bt.original(state, ws, "ronin-rescue", narrative=narrative)
    label = "café ☕"
    batch_id = bt.submit(s, ws, ["ronin-rescue"], [bt.variant(label, {}, append="Snow falls on the café.",
                                                              replace=[("dusk", "l’aube")])])
    cell = bt.wait_status(s, batch_id)["batch"]["cells"][0]
    edited = "A ronin rescues a child at l’aube — before the café burns.\n\nSnow falls on the café."
    job = lib.read_job(lib.job_dir(state, cell["job_id"]))
    assert job["fields"]["narrative"] == edited and job["argv"][2] == edited
    assert cell["diff"] == [{"key": "narrative", "from": narrative, "to": edited}] and cell["level"] == "replan"
    assert bt.record(state, batch_id)["variants"][0]["label"] == label
    assert lib.read_json(os.path.join(lib.story_dir(ws, cell["fork_id"]), "fork.json"))["label"] == label


def test_batch_review_focus_3_two_batches_submitted_at_once(env, monkeypatch):
    """Review Focus 3: a double click, or two tabs, submit a batch of the same story at once."""
    s, state, ws = env["srv"], env["state"], env["ws"]
    bt.passing_checks(monkeypatch)
    bt.original(state, ws, "ronin-rescue")
    results = []

    def post():
        results.append(mt.api(s, "POST", "/api/batches",
                              body=bt.body(ws, ["ronin-rescue"], [bt.variant("v1", bt.RENDER)])))
    threads = [threading.Thread(target=post) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(60)
    assert sorted(r[0] for r in results) == [201, 201]
    assert sorted(r[2]["batch"]["number"] for r in results) == [1, 2]
    forks = []
    for batch_id in set(r[2]["batch"]["id"] for r in results):
        cell = bt.wait_status(s, batch_id)["batch"]["cells"][0]
        assert cell["status"] == "queued"
        forks.append(cell["fork_id"])
    assert sorted(forks) == ["ronin-rescue-b1-v1", "ronin-rescue-b2-v1"] and len(lib.read_queue(state)) == 2


def test_batch_review_focus_4_batches_are_per_workspace(env, monkeypatch, tmp_path):
    """Review Focus 4: the Workspace selector names another workspace (another release)."""
    s, state, ws = env["srv"], env["state"], env["ws"]
    bt.passing_checks(monkeypatch)
    other = mt.make_stub_workspace(tmp_path / "second")
    bt.original(state, ws, "ronin-rescue")
    bt.original(state, other, "ronin-rescue")
    first = bt.submit(s, ws, ["ronin-rescue"], [bt.variant("v1", bt.RENDER)])
    created = bt.wait_status(s, first)["batch"]["created"]
    assert mt.api(s, "GET", "/api/batches?ws=" + other)[:3:2] == (200, {"batches": []})
    second = bt.submit(s, other, ["ronin-rescue"], [bt.variant("v1", bt.RENDER)])
    payload = bt.wait_status(s, second)
    assert payload["batch"]["number"] == 1 and payload["batch"]["cells"][0]["fork_id"] == "ronin-rescue-b1-v1"
    assert mt.api(s, "GET", "/api/batches?ws=" + ws)[2] == {"batches": [
        {"id": first, "number": 1, "created": created, "status": "submitted", "cells": 1, "done": 0}]}
    assert mt.api(s, "GET", "/api/batches")[:3:2] == (400, {"error": "missing ws"})


BATCH_ROUTES = [("GET", "/api/batches"), ("POST", "/api/batches"), ("POST", "/api/batches/preview"),
                ("GET", "/api/batches/stories"), ("GET", "/api/batches/" + srv._SAMPLE_ID),
                ("DELETE", "/api/batches/" + srv._SAMPLE_ID), ("POST", "/api/batches/%s/cancel" % srv._SAMPLE_ID),
                ("POST", "/api/batches/%s/resume" % srv._SAMPLE_ID)]


def test_bt14_every_batch_route_needs_the_token(env):
    s = env["srv"]
    assert [(m, sample) for m, _r, _n, sample in srv.ROUTES if sample.startswith("/api/batches")] == BATCH_ROUTES
    for method, regex, name, sample in srv.ROUTES:
        if (method, sample) not in BATCH_ROUTES:
            continue
        assert re.fullmatch(regex, sample) and hasattr(srv.MovieUIHandler, name), name
        for token in (None, "wrong-token"):
            status, _h, payload = mt.api(s, method, sample, body={} if method == "POST" else None, token=token)
            assert (status, payload) == (401, {"error": "missing or invalid token"}), (method, sample, token)
    for method, sample in BATCH_ROUTES[4:]:
        assert mt.api(s, method, sample, body={} if method == "POST" else None)[:3:2] == (
            404, {"error": "unknown batch %s" % srv._SAMPLE_ID}), (method, sample)
    assert mt.api(s, "PUT", "/api/batches", body={})[:3:2] == (405, {"error": "method not allowed"})


def test_bt20_cancel_batch(env, monkeypatch):
    import fcntl
    s, state, ws = env["srv"], env["state"], env["ws"]
    gate = threading.Event()
    calls = bt.passing_checks(monkeypatch, gate={"ronin-rescue-b1-v3": gate})
    bt.original(state, ws, "ronin-rescue")
    batch_id = bt.submit(s, ws, ["ronin-rescue"], [bt.variant("v%d" % m, {"model": "/models/m%d" % m})
                                                   for m in range(1, 5)])
    mt.wait_until(lambda: "ronin-rescue-b1-v3" in calls, 30)
    cells = bt.record(state, batch_id)["cells"]
    assert [c["status"] for c in cells] == ["queued", "queued", "forking", "pending"]
    forks = [lib.story_dir(ws, c["fork_id"]) for c in cells]
    running, queued = cells[0]["job_id"], cells[1]["job_id"]
    jdir = lib.job_dir(state, running)
    lib.write_queue(state, [queued])
    lib.write_status(jdir, {"state": "running", "dispatched": lib.utc_now(), "runner_pid": os.getpid(),
                            "pgid": None, "started": lib.utc_now()})
    holder = os.open(os.path.join(jdir, "lock"), os.O_RDWR | os.O_CREAT, 0o600)
    fcntl.flock(holder, fcntl.LOCK_EX)
    try:
        status, _h, payload = mt.api(s, "POST", "/api/batches/%s/cancel" % batch_id, body={})
        assert (status, payload) == (200, {"status": "cancelled", "cancelled": [queued], "cancelling": [running]})
        gate.set()
        mt.wait_until(lambda: s.server.batch_thread is None, 30)
    finally:
        os.close(holder)
    rec = bt.record(state, batch_id)
    assert [(c["status"], c["reason"]) for c in rec["cells"]] == [
        ("queued", None), ("cancelled", "cancelled before it started"), ("cancelled", "batch cancelled"),
        ("cancelled", "batch cancelled")]
    assert (rec["status"], rec["cancel_requested"]) == ("cancelled", True)
    assert os.path.isdir(forks[0]) and not any(os.path.lexists(f) for f in forks[1:])
    assert os.path.exists(os.path.join(jdir, "cancel")) and calls == [c["fork_id"] for c in cells[:3]]
    lib.write_status(jdir, {"state": "cancelled", "dispatched": lib.utc_now(), "runner_pid": os.getpid(),
                            "pgid": None, "started": lib.utc_now(), "exit_code": -15, "ended": lib.utc_now()})
    assert mt.api(s, "POST", "/api/batches/%s/cancel" % batch_id, body={})[:3:2] == (
        409, {"error": "batch %s has nothing to cancel" % batch_id})
    assert mt.api(s, "GET", "/api/batches/" + batch_id)[2]["view"]["cells"][0]["state"] == "cancelled"
    assert os.path.isdir(forks[0])


def test_bt21_delete_batch(env, monkeypatch):
    s, state, ws = env["srv"], env["state"], env["ws"]
    gate = threading.Event()
    calls = bt.passing_checks(monkeypatch, gate={"ronin-rescue-b1-v1": gate})
    bt.original(state, ws, "ronin-rescue")
    batch_id = bt.submit(s, ws, ["ronin-rescue"], [bt.variant("v1", bt.RENDER),
                                                   bt.variant("v2", {"gemma": bt.OTHER_GEMMA})])
    mt.wait_until(lambda: "ronin-rescue-b1-v1" in calls, 30)
    try:
        assert mt.api(s, "DELETE", "/api/batches/" + batch_id)[:3:2] == (
            409, {"error": "batch %s is still submitting; cancel it first" % batch_id})
    finally:
        gate.set()
    cells = bt.wait_status(s, batch_id)["batch"]["cells"]
    assert mt.api(s, "DELETE", "/api/batches/" + batch_id)[:3:2] == (200, {"deleted": batch_id})
    assert not os.path.exists(os.path.join(state, "batches", batch_id))
    assert mt.api(s, "GET", "/api/batches/" + batch_id)[:3:2] == (404, {"error": "unknown batch %s" % batch_id})
    for cell in cells:
        assert os.path.isfile(os.path.join(lib.story_dir(ws, cell["fork_id"]), "fork.json"))
        assert os.path.isfile(os.path.join(lib.job_dir(state, cell["job_id"]), "job.json"))


def test_bt27_cancelling_a_fork_job_removes_its_folder(env, monkeypatch):
    s, state, ws = env["srv"], env["state"], env["ws"]
    bt.passing_checks(monkeypatch)
    bt.original(state, ws, "ronin-rescue")
    batch_id = bt.submit(s, ws, ["ronin-rescue"], [bt.variant("v1", bt.RENDER),
                                                   bt.variant("v2", {"gemma": bt.OTHER_GEMMA})])
    cells = bt.wait_status(s, batch_id)["batch"]["cells"]
    forks = [lib.story_dir(ws, c["fork_id"]) for c in cells]
    queued, starting = cells[0]["job_id"], cells[1]["job_id"]
    assert mt.api(s, "POST", "/api/jobs/%s/cancel" % queued, body={})[:3:2] == (200, {"state": "cancelled"})
    cell = bt.record(state, batch_id)["cells"][0]
    assert (cell["status"], cell["reason"]) == ("cancelled", "cancelled before it started")
    assert not os.path.lexists(forks[0])
    jdir = lib.job_dir(state, starting)
    lib.write_queue(state, [])
    lib.write_status(jdir, {"state": "starting", "dispatched": lib.utc_now()})
    assert mt.api(s, "POST", "/api/jobs/%s/cancel" % starting, body={})[:3:2] == (202, {"state": "cancelling"})
    proc = subprocess.run([sys.executable, os.path.join(mt.WS, "bin", "movie-ui-job"), jdir],
                          capture_output=True, text=True, timeout=30)
    assert (proc.returncode, proc.stdout) == (0, "[movie-ui] cancelled before start\n")
    assert os.path.isdir(forks[1])
    payload = mt.api(s, "GET", "/api/batches/" + batch_id)[2]
    assert (payload["batch"]["cells"][1]["status"], payload["batch"]["cells"][1]["reason"]) == (
        "cancelled", "cancelled before it started")
    assert payload["view"]["cells"][1] == {"state": "cancelled", "job": None, "movie": None, "dir": False}
    assert not os.path.lexists(forks[1])


def test_bt29_resume_submits_the_interrupted_cells(env, monkeypatch):
    s, state, ws = env["srv"], env["state"], env["ws"]
    bt.passing_checks(monkeypatch)
    bt.original(state, ws, "ronin-rescue")
    clean = {"ws": ws, "stories": ["ronin-rescue"],
             "variants": [bt.variant("v1", bt.RENDER), bt.variant("v2", {"gemma": bt.OTHER_GEMMA})]}
    batch_id = srv.new_batch_id(state)
    rec = srv.make_batch_record(clean, batch_id, 1, srv.plan_batch(s.server, clean, 1)[0])
    rec["status"] = "submitting"
    rec["cells"][0]["status"] = "forking"
    fork = lib.story_dir(ws, rec["cells"][0]["fork_id"])
    os.makedirs(fork)
    lib.write_json_atomic(os.path.join(fork, "fork.json"), {"schema": "movie-ui.fork.v1",
                                                            "fork_id": rec["cells"][0]["fork_id"],
                                                            "batch": batch_id})
    lib.make_dir(os.path.join(state, "batches", batch_id))
    srv.write_batch(state, rec)
    srv.batch_recovery(state)
    assert bt.record(state, batch_id)["status"] == "interrupted" and not os.path.lexists(fork)
    assert mt.api(s, "POST", "/api/batches/%s/resume" % batch_id, body={})[:3:2] == (
        200, {"status": "waiting", "pending": 2})
    cells = bt.wait_status(s, batch_id)["batch"]["cells"]
    assert [c["status"] for c in cells] == ["queued", "queued"]
    assert lib.read_json(os.path.join(fork, "fork.json"))["label"] == "v1"
    assert mt.api(s, "POST", "/api/batches/%s/resume" % batch_id, body={})[:3:2] == (
        409, {"error": "batch %s was not interrupted" % batch_id})


def test_bt35_a_deleted_batch_leaves_its_job_less_forks_ineligible(env, monkeypatch):
    s, state, ws = env["srv"], env["state"], env["ws"]
    batch_id, fork, _job = _fallback_fork(env, monkeypatch)
    assert mt.api(s, "DELETE", "/api/batches/" + batch_id)[:3:2] == (200, {"deleted": batch_id})
    assert _stories(env)[fork] == {
        "id": fork, "eligible": False, "busy_job": None, "fields_source": None, "fields_batch": None,
        "reason": "Its job and its batch %s were deleted: no saved Compose settings to fork" % batch_id}
    req = bt.body(ws, [fork], [bt.variant("v1", {"gemma": bt.OTHER_GEMMA})])
    cell = mt.api(s, "POST", "/api/batches/preview", body=req)[2]["cells"][0]
    assert (cell["status"], cell["reason"]) == ("refused", "story %s has no saved Compose settings (its job and "
                                                           "its batch %s were deleted)" % (fork, batch_id))
    status, _h, payload = mt.api(s, "POST", "/api/batches", body=req)
    assert status == 409 and payload["error"] == "every cell was refused"


def test_batch_fix_reconcile_keeps_a_fork_a_later_job_uses(env, monkeypatch):
    s, state, ws = env["srv"], env["state"], env["ws"]
    bt.passing_checks(monkeypatch)
    bt.original(state, ws, "ronin-rescue")
    batch_id = bt.submit(s, ws, ["ronin-rescue"], [bt.variant("v1", bt.RENDER)])
    cell = bt.wait_status(s, batch_id)["batch"]["cells"][0]
    fork = lib.story_dir(ws, cell["fork_id"])
    lib.write_queue(state, [i for i in lib.read_queue(state) if i != cell["job_id"]])
    lib.write_status(lib.job_dir(state, cell["job_id"]), {"state": "cancelled", "exit_code": None,
                                                          "ended": lib.utc_now()})
    later = mt.make_job(state, ["true"], ws, story_id=cell["fork_id"],
                        status={"state": "running", "started": lib.utc_now()})
    mt.api(s, "GET", "/api/batches?ws=" + ws)
    assert os.path.isdir(fork)
    assert bt.record(state, batch_id)["cells"][0]["status"] == "cancelled"
    assert srv.fork_in_use(state, ws, cell["fork_id"], cell["job_id"]) == later


def test_batch_fix_remove_fork_refuses_a_foreign_fork_json(tmp_path, capsys):
    fdir = tmp_path / "ronin-rescue-b1-v1"
    fdir.mkdir()
    for rec in ({"batch": "20261030-120000-0b0b", "fork_id": "ronin-rescue-b1-v1"},
                {"batch": "20261030-120000-0a0a", "fork_id": "other-b1-v1"}, None):
        if rec is None:
            (fdir / "fork.json").unlink()
        else:
            (fdir / "fork.json").write_text(json.dumps(rec), encoding="utf-8")
        assert srv.remove_fork(str(fdir), "20261030-120000-0a0a") is False
        assert fdir.is_dir()
    assert "not removing" in capsys.readouterr().err


def test_batch_fix_copy_failure_midway_leaves_no_fork(env, monkeypatch):
    s, state, ws = env["srv"], env["state"], env["ws"]
    bt.passing_checks(monkeypatch)
    sdir, _ = bt.original(state, ws, "ronin-rescue", files=RICH_FILES)
    real, calls = srv.shutil.copy2, []

    def flaky(src, dst, *args, **kwargs):
        calls.append(src)
        if len(calls) == 3:
            raise OSError(28, "No space left on device", dst)
        return real(src, dst, *args, **kwargs)
    monkeypatch.setattr(srv.shutil, "copy2", flaky)
    before = bt.tree_digests(sdir)
    batch_id = bt.submit(s, ws, ["ronin-rescue"], [bt.variant("v1", bt.RENDER)])
    cell = bt.wait_status(s, batch_id)["batch"]["cells"][0]
    assert cell["status"] == "refused" and cell["reason"].startswith("copy failed: No space left on device: ")
    assert not os.path.lexists(lib.story_dir(ws, cell["fork_id"]))
    assert bt.tree_digests(sdir) == before


def test_batch_fix_fork_json_write_failure_leaves_no_fork(env, monkeypatch):
    s, state, ws = env["srv"], env["state"], env["ws"]
    bt.passing_checks(monkeypatch)
    bt.original(state, ws, "ronin-rescue")
    real = lib.write_json_atomic

    def failing(path, obj, *args, **kwargs):
        if path.endswith("fork.json"):
            raise OSError(28, "No space left on device", path)
        return real(path, obj, *args, **kwargs)
    monkeypatch.setattr(lib, "write_json_atomic", failing)
    batch_id = bt.submit(s, ws, ["ronin-rescue"], [bt.variant("v1", bt.RENDER)])
    cell = bt.wait_status(s, batch_id)["batch"]["cells"][0]
    assert cell["status"] == "refused" and cell["reason"].startswith("copy failed: No space left on device: ")
    assert not os.path.lexists(lib.story_dir(ws, cell["fork_id"]))


def test_batch_fix_mkdir_error_is_a_copy_failure(env, monkeypatch):
    s, state, ws = env["srv"], env["state"], env["ws"]
    bt.passing_checks(monkeypatch)
    bt.original(state, ws, "ronin-rescue")
    real = srv.os.mkdir

    def denied(path, *args, **kwargs):
        if str(path).endswith("-b1-v1"):
            raise PermissionError(13, "Permission denied", path)
        return real(path, *args, **kwargs)
    monkeypatch.setattr(srv.os, "mkdir", denied)
    batch_id = bt.submit(s, ws, ["ronin-rescue"], [bt.variant("v1", bt.RENDER)])
    cell = bt.wait_status(s, batch_id)["batch"]["cells"][0]
    assert (cell["status"], cell["reason"].split(": ")[0]) == ("refused", "copy failed")
    assert "Permission denied" in cell["reason"]


def test_batch_fix_numbers_are_never_reused_after_cancel_and_delete(env, monkeypatch):
    s, state, ws = env["srv"], env["state"], env["ws"]
    bt.passing_checks(monkeypatch, fail={})
    bt.original(state, ws, "ronin-rescue")
    variants = [bt.variant("v1", bt.RENDER), bt.variant("v2", {"gemma": bt.OTHER_GEMMA})]
    b1 = bt.submit(s, ws, ["ronin-rescue"], variants)
    bt.wait_status(s, b1)
    assert mt.api(s, "POST", "/api/batches/%s/cancel" % b1, body={})[0] == 200
    assert mt.api(s, "DELETE", "/api/batches/" + b1)[0] == 200
    bt.passing_checks(monkeypatch, fail={"ronin-rescue-b2-v1": "Error: dry run failed"})
    b2 = bt.submit(s, ws, ["ronin-rescue"], variants)
    bt.wait_status(s, b2)
    rec = bt.record(state, b2)
    assert rec["number"] == 2
    assert [c["fork_id"] for c in rec["cells"]] == ["ronin-rescue-b2-v1", "ronin-rescue-b2-v2"]
    assert rec["cells"][0]["status"] == "refused"
    assert not os.path.lexists(lib.story_dir(ws, "ronin-rescue-b2-v1"))
    assert mt.api(s, "POST", "/api/batches/%s/cancel" % b2, body={})[0] == 200
    mt.api(s, "GET", "/api/batches?ws=" + ws)
    assert not os.path.lexists(lib.story_dir(ws, "ronin-rescue-b2-v2"))


def test_batch_fix_a_malformed_record_does_not_hide_the_list(env, monkeypatch):
    s, state, ws = env["srv"], env["state"], env["ws"]
    bt.passing_checks(monkeypatch)
    bt.original(state, ws, "ronin-rescue")
    good = bt.submit(s, ws, ["ronin-rescue"], [bt.variant("v1", bt.RENDER)])
    bt.wait_status(s, good)
    bad = "20201030-120000-0c0c"
    lib.make_dir(os.path.join(state, "batches", bad))
    lib.write_json_atomic(os.path.join(state, "batches", bad, "batch.json"), {"id": bad, "workspace": ws})
    status, _h, payload = mt.api(s, "GET", "/api/batches?ws=" + ws)
    assert status == 200 and [b["id"] for b in payload["batches"]] == [good]
