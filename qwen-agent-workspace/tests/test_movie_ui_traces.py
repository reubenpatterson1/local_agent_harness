"""movie-ui trace proxy tests (movie-ui spec MUT22, MU20, MU71-MU74, D9).
Run from the workspace root: python3 -m pytest tests/test_movie_ui_traces.py -v
Daemons are FakeDaemon instances on 127.0.0.1; no real daemon is contacted."""

import os

import pytest

import fleet_lib
import movie_ui_testutil as mt
import movie_ui_lib as lib

T1 = "11111111111111111111111111111111"
T2 = "22222222222222222222222222222222"
T3 = "33333333333333333333333333333333"


@pytest.fixture
def env(monkeypatch, tmp_path):
    state = mt.set_home(monkeypatch, tmp_path)
    running = mt.Running(state)
    daemons = []
    yield {"state": state, "srv": running, "home": os.environ["HOME"], "tmp": str(tmp_path), "daemons": daemons}
    running.close()
    for d in daemons:
        d.close()


def _summary(trace_id, start, delegated=(), status="ok"):
    return {"trace_id": trace_id, "start": start, "dur_ms": 1500, "status": status, "kind": "turn",
            "name": "planner", "spans": 3, "delegated": list(delegated)}


def _recent(agent, traces):
    return {"schema": fleet_lib.RECENT_SCHEMA, "agent": agent, "traces": traces}


def _result(trace_id, records, missing=(), truncated=()):
    return {"schema": fleet_lib.TRACE_SCHEMA, "trace_id": trace_id, "records": records,
            "missing": list(missing), "truncated": list(truncated)}


def _agents(env, ports):
    """Two agents on disk whose registries name the given ports (None: no registry file)."""
    spec = {}
    for agent, port in ports.items():
        spec[agent] = {"current": "v2026.10.01", "releases": {"v2026.10.01": {}}}
        if port is not None:
            spec[agent]["port"] = port
    mt.make_agents_home(env["home"], spec)


def test_mut22_agents_registry_default_and_disagreeing_ports(env):
    _agents(env, {"alpha": 9001, "beta": None})
    gamma = os.path.join(env["home"], "agents", "gamma")
    mt.make_agents_home(env["home"], {"gamma": {"current": "v2026.10.01", "releases": {"v2026.10.01": {}},
                                                "ports": [9100, 9200]}})
    status, _h, payload = mt.api(env["srv"], "GET", "/api/traces/agents")
    assert status == 200 and payload["default"] is None
    fleets = os.path.join(gamma, "current", "qwen-agent-workspace", "fleets")
    assert payload["agents"] == [
        {"id": "alpha", "port": 9001, "port_source": "registry", "url": "http://127.0.0.1:9001", "error": None},
        {"id": "beta", "port": fleet_lib.DEFAULT_PORT, "port_source": "default",
         "url": "http://127.0.0.1:%d" % fleet_lib.DEFAULT_PORT, "error": None},
        {"id": "gamma", "port": None, "port_source": None, "url": None,
         "error": "agent 'gamma' has different ports in f0.json, f1.json in %s" % fleets}]


def test_mut22_recent_merge_errors_and_wire_headers(env):
    a = mt.FakeDaemon("alpha", recent=_recent("alpha", [_summary(T1, 100.0, ["analyst@beta"]), _summary(T2, 300.0)]))
    b = mt.FakeDaemon("beta", recent=_recent("beta", [_summary(T1, 99.5), _summary(T3, 200.0)]))
    env["daemons"] += [a, b]
    dead = mt.free_port()
    _agents(env, {"alpha": a.port, "beta": b.port, "zeta": dead})
    status, _h, payload = mt.api(env["srv"], "GET", "/api/traces/recent?agent=all&n=10")
    assert status == 200
    assert [(t["trace_id"], t["start"], t["seen_on"], t["agents"]) for t in payload["traces"]] == [
        (T2, 300.0, ["alpha"], ["alpha"]), (T3, 200.0, ["beta"], ["beta"]), (T1, 99.5, ["alpha", "beta"], ["alpha", "beta"])]
    assert payload["errors"] == [{"agent": "zeta", "error": "daemon: not reachable at http://127.0.0.1:%d" % dead}]
    for daemon in (a, b):
        request = daemon.requests[-1]
        assert request["path"] == "/traces/recent?n=10"
        assert request["headers"]["Host"] == "127.0.0.1:%d" % daemon.port
        assert "Origin" not in request["headers"]
    assert len(mt.api(env["srv"], "GET", "/api/traces/recent?n=1")[2]["traces"]) == 1
    only = mt.api(env["srv"], "GET", "/api/traces/recent?agent=beta")[2]
    assert [t["trace_id"] for t in only["traces"]] == [T3, T1] and only["errors"] == []
    assert mt.api(env["srv"], "GET", "/api/traces/recent?agent=nobody")[:3:2] == (404, {"error": "unknown agent"})
    for bad in ("0", "101", "x", "1000"):
        assert mt.api(env["srv"], "GET", "/api/traces/recent?n=" + bad)[:3:2] == (400, {"error": "n must be 1 to 100"})


def test_mut22_one_trace_text_skew_save_list_load_delete(env):
    records = [mt.trace_record(T1, "a" * 16, None, "alpha", 100.0, dur_ms=5000),
               mt.trace_record(T1, "b" * 16, "a" * 16, "beta", 99.0, kind="run", dur_ms=2000),
               mt.trace_record(T1, "c" * 16, "f" * 16, "beta", 101.0)]
    result = _result(T1, records, missing=[{"agent": "gamma", "reason": "timeout"}])
    a = mt.FakeDaemon("alpha", traces={T1: result})
    env["daemons"].append(a)
    _agents(env, {"alpha": a.port})
    s = env["srv"]
    status, _h, payload = mt.api(s, "GET", "/api/traces/%s?agent=alpha&format=text" % T1)
    assert status == 200 and payload["agent"] == "alpha" and payload["result"] == result
    assert payload["skew"] == ["b" * 16]
    assert payload["text"] == "\n".join(fleet_lib.render_trace(result)) + "\n"
    assert a.requests[-1]["path"] == "/trace?id=" + T1 and "Origin" not in a.requests[-1]["headers"]
    assert "text" not in mt.api(s, "GET", "/api/traces/%s?agent=alpha" % T1)[2]
    assert mt.api(s, "GET", "/api/traces/%s" % T1)[2]["agent"] == "alpha"
    assert mt.api(s, "GET", "/api/traces/%s?agent=nobody" % T1)[:3:2] == (404, {"error": "unknown agent"})
    status, _h, payload = mt.api(s, "GET", "/api/traces/%s?agent=alpha" % T2)
    assert (status, payload) == (502, {"error": "the daemon at http://127.0.0.1:%d has no trace support (http 404)"
                                                % a.port})
    status, _h, payload = mt.api(s, "POST", "/api/traces/%s/save" % T1, body={"agent": "alpha"})
    path = os.path.join(env["state"], "traces", T1 + ".json")
    assert (status, payload) == (200, {"saved": T1, "path": path})
    saved = lib.read_json(path)
    assert saved["schema"] == "movie-ui.saved-trace.v1" and saved["result"] == result and saved["agent"] == "alpha"
    a.close()
    env["daemons"].remove(a)
    status, _h, payload = mt.api(s, "GET", "/api/traces/%s?agent=alpha" % T1)
    assert (status, payload) == (502, {"error": "daemon: not reachable at http://127.0.0.1:%d" % a.port})
    with open(os.path.join(env["state"], "traces", T2 + ".json"), "w") as f:
        f.write("{broken")
    listing = mt.api(s, "GET", "/api/traces/saved")[2]["saved"]
    assert listing == [
        {"trace_id": T1, "agent": "alpha", "saved_at": saved["saved_at"], "spans": 3, "start": 99.0, "invalid": False},
        {"trace_id": T2, "agent": None, "saved_at": None, "spans": 0, "start": None, "invalid": True}]
    view = mt.api(s, "GET", "/api/traces/saved/%s" % T1)[2]
    assert view["result"] == result and view["skew"] == ["b" * 16]
    assert view["text"] == "\n".join(fleet_lib.render_trace(result)) + "\n"
    assert mt.api(s, "GET", "/api/traces/saved/%s" % T2)[:3:2] == (422, {"error": "saved trace is invalid"})
    assert mt.api(s, "GET", "/api/traces/saved/%s" % T3)[0] == 404
    assert mt.api(s, "DELETE", "/api/traces/saved/%s" % T1)[:3:2] == (200, {"deleted": T1})
    assert mt.api(s, "DELETE", "/api/traces/saved/%s" % T1)[0] == 404
