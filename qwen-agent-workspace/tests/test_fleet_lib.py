"""Unit tests for fleet_lib.py and bin/qwen-agentd-launch (fleet spec Section 11.3, D6).

Run from the workspace root: python3 -m pytest tests/test_fleet_lib.py -v
This file is also the self-update gate's selftest (spec F93): it stays fast, needs
no model server, and uses no network beyond in-process loopback servers. The code
under test is found relative to this file, so a release's selftest always tests
that release's own fleet_lib.py.
"""

import copy
import hashlib
import hmac
import http.server
import importlib.machinery
import importlib.util
import json
import os
import socket
import stat
import subprocess
import sys
import threading
import time

import pytest

WS = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
sys.path.insert(0, WS)
import fleet_lib  # noqa: E402

TEST_FLEET_ID = "0123456789abcdef"
TEST_TOKEN = "5e" * 32
OTHER_TOKEN = "a7" * 32


def _f18_registry(fleet_id=TEST_FLEET_ID):
    """The spec F18 production registry, with a test fleet_id."""
    return {
        "protocol": 1,
        "fleet_id": fleet_id,
        "hosts": {
            "orchestrator": {
                "role": "orchestrator",
                "address": "192.168.1.170",
                "model_server": {"type": "vllm", "url": "http://127.0.0.1:8000/v1"},
                "model": "PLACEHOLDER-70B",
                "skills": [],
            },
            "ollama-168": {
                "role": "agent",
                "address": "192.168.1.168",
                "model_server": {"type": "ollama", "url": "http://127.0.0.1:11434/v1"},
                "model": "qwen3.5:9b",
                "skills": ["researcher"],
            },
            "mac-local": {
                "role": "agent",
                "address": "192.168.1.199",
                "model_server": {"type": "vllm", "url": "http://127.0.0.1:8177/v1"},
                "model": "qwen38-6bit",
                "skills": ["investigator", "analyst", "planner"],
            },
        },
    }


def _write_json(path, obj):
    with open(str(path), "w", encoding="utf-8") as f:
        json.dump(obj, f)
    return str(path)


# --- T1-T4: registry and self-identity (F6-F9, F18) ---------------------------------

def test_t1_f18_registry_is_valid():
    reg = _f18_registry()
    assert fleet_lib.validate_registry(reg, TEST_FLEET_ID) == []
    for i, host in enumerate(reg["hosts"].values()):
        host["port"] = 8190 + i
    assert fleet_lib.validate_registry(reg, TEST_FLEET_ID) == []


def _mutated(mutate):
    reg = _f18_registry()
    mutate(reg)
    return reg


# (rule number, mutation, location prefix the error must start with)
_RULE_CASES = [
    (1, lambda r: r.update(extra=1), "registry: unexpected key 'extra'"),
    (1, lambda r: r.pop("hosts"), "registry: missing key 'hosts'"),
    (2, lambda r: r.update(protocol=True), "protocol: "),
    (2, lambda r: r.update(protocol=2), "protocol: "),
    (3, lambda r: r.update(fleet_id="0123456789ABCDEF"), "fleet_id: "),
    (3, lambda r: r.update(fleet_id="ffffffffffffffff"), "fleet_id: "),
    (4, lambda r: r.update(hosts={}), "hosts: "),
    (4, lambda r: r["hosts"].update({"Bad_Host": r["hosts"].pop("mac-local")}), "hosts.Bad_Host: "),
    (4, lambda r: r["hosts"].update({"mac-local\n": r["hosts"].pop("mac-local")}), "hosts.mac-local\n: "),
    (5, lambda r: r["hosts"].update({"mac-local": ["not", "a", "dict"]}), "hosts.mac-local: "),
    (5, lambda r: r["hosts"]["mac-local"].pop("model"), "hosts.mac-local: missing key 'model'"),
    (5, lambda r: r["hosts"]["mac-local"].update(gpu="m5"), "hosts.mac-local: unexpected key 'gpu'"),
    (6, lambda r: r["hosts"]["mac-local"].update(role="boss"), "hosts.mac-local.role: "),
    (7, lambda r: r["hosts"]["mac-local"].update(address="192.168.1.999"), "hosts.mac-local.address: "),
    (7, lambda r: r["hosts"]["mac-local"].update(address=3232235975), "hosts.mac-local.address: "),
    (8, lambda r: r["hosts"]["mac-local"].update(port=True), "hosts.mac-local.port: "),
    (8, lambda r: r["hosts"]["mac-local"].update(port=0), "hosts.mac-local.port: "),
    (8, lambda r: r["hosts"]["mac-local"].update(port=65536), "hosts.mac-local.port: "),
    (9, lambda r: r["hosts"]["mac-local"].update(model_server={"type": "vllm"}), "hosts.mac-local.model_server: "),
    (9, lambda r: r["hosts"]["mac-local"]["model_server"].update(type="lmstudio"), "hosts.mac-local.model_server.type: "),
    (9, lambda r: r["hosts"]["mac-local"]["model_server"].update(url="https://x/v1"), "hosts.mac-local.model_server.url: "),
    (9, lambda r: r["hosts"]["ollama-168"]["model_server"].update(url="http://127.0.0.1:11434"), "hosts.ollama-168.model_server.url: "),
    (10, lambda r: r["hosts"]["mac-local"].update(model=""), "hosts.mac-local.model: "),
    (11, lambda r: r["hosts"]["mac-local"].update(skills="analyst"), "hosts.mac-local.skills: "),
    (11, lambda r: r["hosts"]["mac-local"].update(skills=["coder"]), "hosts.mac-local.skills[0]: "),
    (11, lambda r: r["hosts"]["mac-local"].update(skills=["analyst", "analyst"]), "hosts.mac-local.skills[1]: "),
    (12, lambda r: r["hosts"]["orchestrator"].update(address="192.168.1.199"), "hosts.orchestrator: address 192.168.1.199:8190"),
]


def test_t2_every_rule_reports_a_located_error():
    rules_seen = set()
    for rule, mutate, prefix in _RULE_CASES:
        errors = fleet_lib.validate_registry(_mutated(mutate), TEST_FLEET_ID)
        assert errors, "rule %d case %r produced no error" % (rule, prefix)
        assert any(e.startswith(prefix) for e in errors), (rule, prefix, errors)
        for e in errors:
            assert ": " in e and not e.startswith(": "), e
        rules_seen.add(rule)
    assert rules_seen == set(range(1, 13))
    # Exactly one error per independent violation.
    def three(r):
        r["protocol"] = 2
        r["hosts"]["mac-local"]["role"] = "boss"
        r["hosts"]["ollama-168"]["skills"] = ["researcher", "coder"]
    assert len(fleet_lib.validate_registry(_mutated(three), TEST_FLEET_ID)) == 3
    assert fleet_lib.validate_registry([], TEST_FLEET_ID) == ["registry: must be a JSON object"]


def test_t3_load_registry(tmp_path):
    path = _write_json(tmp_path / "reg.json", _f18_registry())
    reg = fleet_lib.load_registry(path, TEST_FLEET_ID)
    assert all(h["port"] == 8190 for h in reg["hosts"].values())
    reg["hosts"]["mac-local"]["skills"].append("researcher")
    again = fleet_lib.load_registry(path, TEST_FLEET_ID)
    assert again["hosts"]["mac-local"]["skills"] == ["investigator", "analyst", "planner"]
    with open(path, encoding="utf-8") as f:
        assert "port" not in f.read()

    missing = str(tmp_path / "missing.json")
    with pytest.raises(fleet_lib.RegistryError) as e:
        fleet_lib.load_registry(missing, TEST_FLEET_ID)
    assert str(e.value).startswith("cannot read registry %s: FileNotFoundError: " % missing)

    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    with pytest.raises(fleet_lib.RegistryError) as e:
        fleet_lib.load_registry(str(bad), TEST_FLEET_ID)
    assert str(e.value).startswith("cannot read registry %s: JSONDecodeError: " % bad)

    invalid = _write_json(tmp_path / "invalid.json", _mutated(lambda r: r.update(protocol=2)))
    with pytest.raises(fleet_lib.RegistryError) as e:
        fleet_lib.load_registry(invalid, TEST_FLEET_ID)
    assert str(e.value) == "invalid registry %s:\n  protocol: must be the integer 1" % invalid

    empty = _write_json(tmp_path / "empty.json", {})
    with pytest.raises(fleet_lib.RegistryError) as e:
        fleet_lib.load_registry(empty, TEST_FLEET_ID)
    assert str(e.value).count("\n  registry: missing key") == 3


def test_t4_self_entry():
    reg = _f18_registry()
    assert fleet_lib.self_entry(reg, "mac-local")["model"] == "qwen38-6bit"
    with pytest.raises(fleet_lib.RegistryError) as e:
        fleet_lib.self_entry(reg, "laptop")
    assert str(e.value) == ("host_id 'laptop' is not in the fleet registry; "
                            "valid IDs: mac-local, ollama-168, orchestrator")


# --- T5, T6, T25, Review Focus 3: fleet.env and join strings (F19-F28) --------------

def _write_raw(path, text, mode=0o600):
    fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, mode)
    with os.fdopen(fd, "w", encoding="ascii", newline="") as f:
        f.write(text)
    os.chmod(str(path), mode)
    return str(path)


def test_t5_fleet_env_write_load_and_modes(tmp_path):
    path = str(tmp_path / "cfg" / "qwen-agent" / "fleet.env")
    fleet_lib.write_fleet_env(path, TEST_FLEET_ID, TEST_TOKEN)
    assert stat.S_IMODE(os.stat(os.path.dirname(path)).st_mode) == 0o700
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o600
    with open(path, encoding="ascii", newline="") as f:
        assert f.read() == ("QWEN_AGENT_FLEET_ID=%s\nQWEN_AGENT_FLEET_TOKEN=%s\n"
                            % (TEST_FLEET_ID, TEST_TOKEN))
    with pytest.raises(FileExistsError):
        fleet_lib.write_fleet_env(path, TEST_FLEET_ID, TEST_TOKEN)
    assert fleet_lib.load_fleet_env(path) == (TEST_FLEET_ID, TEST_TOKEN)

    os.chmod(path, 0o644)
    with pytest.raises(fleet_lib.FleetEnvError) as e:
        fleet_lib.load_fleet_env(path)
    assert str(e.value) == "%s must be mode 0600 (chmod 600 %s)" % (path, path)

    good = "QWEN_AGENT_FLEET_ID=%s\nQWEN_AGENT_FLEET_TOKEN=%s\n" % (TEST_FLEET_ID, TEST_TOKEN)
    variants = [
        good[:-1],                                     # no final newline
        good + "\n",                                   # extra empty line
        good + "EXTRA=1\n",                            # extra line
        good.replace("\n", "\r\n"),                    # CRLF
        "QWEN_AGENT_FLEET_TOKEN=%s\nQWEN_AGENT_FLEET_ID=%s\n" % (TEST_TOKEN, TEST_FLEET_ID),
        good.replace(TEST_FLEET_ID, TEST_FLEET_ID.upper()),
        good.replace(TEST_TOKEN, TEST_TOKEN[:-2]),
        good.replace("QWEN_AGENT_FLEET_ID=", "QWEN_AGENT_FLEET_ID = "),
        "",
    ]
    for i, text in enumerate(variants):
        bad = _write_raw(tmp_path / ("bad%d.env" % i), text)
        with pytest.raises(fleet_lib.FleetEnvError) as e:
            fleet_lib.load_fleet_env(bad)
        assert str(e.value) == "%s is malformed" % bad, i
    with pytest.raises(FileNotFoundError):
        fleet_lib.load_fleet_env(str(tmp_path / "absent.env"))


def test_t6_join_string_round_trip_and_tamper():
    s = fleet_lib.make_join_string(TEST_FLEET_ID, TEST_TOKEN)
    check = hashlib.sha256((TEST_FLEET_ID + ":" + TEST_TOKEN).encode("ascii")).hexdigest()[:8]
    assert s == "qaf1.%s.%s.%s" % (TEST_FLEET_ID, TEST_TOKEN, check)
    assert fleet_lib.parse_join_string(s) == (TEST_FLEET_ID, TEST_TOKEN)
    other_id = "1" + TEST_FLEET_ID[1:]
    other_token = "6" + TEST_TOKEN[1:]
    tampered = [
        s[:-1] + ("0" if s[-1] != "0" else "1"),                      # checksum
        "qaf2" + s[4:],                                                # prefix
        s + ".extra",                                                  # part count
        s.replace(".", "", 1),                                         # part count
        "qaf1.%s.%s.%s" % (other_id, TEST_TOKEN, check),               # fleet_id
        "qaf1.%s.%s.%s" % (TEST_FLEET_ID, other_token, check),         # token
        "qaf1.%s.%s.%s" % (TEST_FLEET_ID.upper(), TEST_TOKEN, check),  # case
        "",
    ]
    for bad in tampered:
        with pytest.raises(fleet_lib.FleetEnvError) as e:
            fleet_lib.parse_join_string(bad)
        message = str(e.value)
        assert message == "invalid join string"
        for i in range(len(bad) - 5):
            assert bad[i:i + 6] not in message


def test_review_focus_3_pasted_join_string_whitespace():
    """Review Focus 3: a join string pasted with spaces, a tab, or a trailing newline
    still parses; one with whitespace inside it does not."""
    s = fleet_lib.make_join_string(TEST_FLEET_ID, TEST_TOKEN)
    for pasted in ("  " + s, s + "\n", "\t" + s + " \r\n"):
        assert fleet_lib.parse_join_string(pasted) == (TEST_FLEET_ID, TEST_TOKEN)
    with pytest.raises(fleet_lib.FleetEnvError):
        fleet_lib.parse_join_string(s[:20] + " " + s[20:])
    assert fleet_lib.token_key(TEST_TOKEN) == bytes.fromhex(TEST_TOKEN)
    assert len(fleet_lib.token_key(TEST_TOKEN)) == 32


def test_t25_token_not_in_git_tree():
    path = fleet_lib.fleet_env_path()
    if not os.path.exists(path):
        pytest.skip("no fleet.env on this host")
    inside = subprocess.run(["git", "-C", WS, "rev-parse", "--is-inside-work-tree"],
                            capture_output=True, text=True)
    if inside.returncode != 0 or inside.stdout.strip() != "true":
        pytest.skip("WS is not in a git worktree")
    _fleet_id, token = fleet_lib.load_fleet_env(path)
    needles = (token.encode("ascii"), fleet_lib.token_key(token))
    listing = subprocess.run(["git", "-C", WS, "ls-files", "-z"], capture_output=True)
    assert listing.returncode == 0
    leaked = []
    for rel in listing.stdout.decode("utf-8", "surrogateescape").split("\0"):
        full = os.path.join(WS, rel)
        if not rel or not os.path.isfile(full) or os.path.islink(full):
            continue
        with open(full, "rb") as f:
            data = f.read()
        if any(n in data for n in needles):
            leaked.append(rel)
    assert leaked == [], "fleet token or key bytes found in tracked files: %s" % leaked


# --- T10-T11, T13-T18: signing primitives (F29b-F29j) ---------------------------------

KEY = bytes.fromhex(TEST_TOKEN)
OTHER_KEY = bytes.fromhex(OTHER_TOKEN)
NOW = 1760000000
NONCE_A = "a" * 32
NONCE_B = "b" * 32
NONCE_C = "c" * 32


class _Clock(object):
    def __init__(self, t=1000.0):
        self.t = t

    def __call__(self):
        return self.t


def _beacon_dict(raw):
    return json.loads(raw)


def _resign(key, beacon):
    unsigned = dict((k, v) for k, v in beacon.items() if k != "sig")
    beacon = dict(unsigned)
    beacon["sig"] = hmac.new(key, fleet_lib.canonical_json(unsigned), hashlib.sha256).hexdigest()
    return fleet_lib.canonical_json(beacon)


def test_t10_request_sign_verify():
    body = b'{"skill":"researcher"}'
    headers = fleet_lib.sign_request(KEY, "POST", "/run", body, NOW, NONCE_A)
    assert set(headers) == {"X-Fleet-Ts", "X-Fleet-Nonce", "X-Fleet-Sig"}
    assert fleet_lib.verify_request(KEY, "POST", "/run", headers, body, NOW,
                                    fleet_lib.NonceCache()) == "ok"
    changed = [
        ("GET", "/run", headers, body),
        ("POST", "/runx", headers, body),
        ("POST", "/run", dict(headers, **{"X-Fleet-Ts": str(NOW + 1)}), body),
        ("POST", "/run", dict(headers, **{"X-Fleet-Nonce": NONCE_B}), body),
        ("POST", "/run", headers, body + b" "),
        ("POST", "/run", dict(headers, **{"X-Fleet-Sig": "0" * 64}), body),
    ]
    for method, path, hdrs, b in changed:
        assert fleet_lib.verify_request(KEY, method, path, hdrs, b, NOW,
                                        fleet_lib.NonceCache()) == "bad"
    for name in headers:
        missing = dict(headers)
        del missing[name]
        assert fleet_lib.verify_request(KEY, "POST", "/run", missing, body, NOW,
                                        fleet_lib.NonceCache()) == "bad"
    for name, value in (("X-Fleet-Sig", "z" * 64), ("X-Fleet-Nonce", "Z" * 32), ("X-Fleet-Ts", "12a")):
        assert fleet_lib.verify_request(KEY, "POST", "/run", dict(headers, **{name: value}), body,
                                        NOW, fleet_lib.NonceCache()) == "bad"
    assert fleet_lib.verify_request(OTHER_KEY, "POST", "/run", headers, body, NOW,
                                    fleet_lib.NonceCache()) == "bad"


def test_t11_response_sign_verify():
    body = b'{"schema":"qwen-agent.oneshot.v1"}'
    headers = fleet_lib.sign_response(KEY, 200, "POST", "/run", NONCE_A, body, NOW, NONCE_B)
    assert fleet_lib.verify_response(KEY, 200, "POST", "/run", NONCE_A, headers, body, NOW,
                                     fleet_lib.NonceCache()) == "ok"
    for args in ((KEY, 200, "POST", "/run", NONCE_C, headers, body),
                 (KEY, 409, "POST", "/run", NONCE_A, headers, body),
                 (KEY, 200, "GET", "/run", NONCE_A, headers, body),
                 (KEY, 200, "POST", "/health", NONCE_A, headers, body),
                 (KEY, 200, "POST", "/run", NONCE_A, headers, body + b"x")):
        assert fleet_lib.verify_response(*(args + (NOW, fleet_lib.NonceCache()))) == "bad"


def test_t13_beacon_statuses():
    raw = fleet_lib.make_beacon(KEY, 8190, NOW, NONCE_A)
    status, beacon = fleet_lib.verify_beacon(KEY, raw, NOW, fleet_lib.NonceCache())
    assert status == "ok" and beacon["port"] == 8190 and beacon["nonce"] == NONCE_A
    good = _beacon_dict(raw)
    malformed = [
        b"not json",
        b"[1, 2]",
        fleet_lib.canonical_json(dict((k, v) for k, v in good.items() if k != "port")),
        fleet_lib.canonical_json(dict(good, extra=1)),
        fleet_lib.canonical_json(dict(good, port="8190")),
        fleet_lib.canonical_json(dict(good, ts=True)),
        fleet_lib.canonical_json(dict(good, nonce=5)),
        _resign(KEY, dict(good, proto=2)),
    ]
    for data in malformed:
        assert fleet_lib.verify_beacon(KEY, data, NOW, fleet_lib.NonceCache()) == ("malformed", None)
    for field, value in (("port", 8191), ("ts", NOW - 1), ("nonce", NONCE_B)):
        tampered = fleet_lib.canonical_json(dict(good, **{field: value}))
        assert fleet_lib.verify_beacon(KEY, tampered, NOW, fleet_lib.NonceCache()) == ("bad_sig", None)


def test_t14_replays_are_rejected():
    cache = fleet_lib.NonceCache()
    raw = fleet_lib.make_beacon(KEY, 8190, NOW, NONCE_A)
    assert fleet_lib.verify_beacon(KEY, raw, NOW, cache)[0] == "ok"
    assert fleet_lib.verify_beacon(KEY, raw, NOW, cache) == ("replay", None)

    cache = fleet_lib.NonceCache()
    headers = fleet_lib.sign_request(KEY, "GET", "/health", b"", NOW, NONCE_B)
    assert fleet_lib.verify_request(KEY, "GET", "/health", headers, b"", NOW, cache) == "ok"
    assert fleet_lib.verify_request(KEY, "GET", "/health", headers, b"", NOW, cache) == "replay"

    cache = fleet_lib.NonceCache()
    headers = fleet_lib.sign_response(KEY, 200, "GET", "/health", NONCE_B, b"{}", NOW, NONCE_C)
    args = (KEY, 200, "GET", "/health", NONCE_B, headers, b"{}", NOW, cache)
    assert fleet_lib.verify_response(*args) == "ok"
    assert fleet_lib.verify_response(*args) == "replay"


def test_t15_skew_window_is_60_seconds():
    for ts, expected in ((NOW - 60, "ok"), (NOW + 60, "ok"), (NOW - 61, "skew"), (NOW + 61, "skew")):
        raw = fleet_lib.make_beacon(KEY, 8190, ts, NONCE_A)
        status, beacon = fleet_lib.verify_beacon(KEY, raw, NOW, fleet_lib.NonceCache())
        assert status == expected, ("beacon", ts)
        if expected == "skew":
            assert beacon["ts"] == ts
        headers = fleet_lib.sign_request(KEY, "GET", "/health", b"", ts, NONCE_A)
        assert fleet_lib.verify_request(KEY, "GET", "/health", headers, b"", NOW,
                                        fleet_lib.NonceCache()) == expected, ("request", ts)
        headers = fleet_lib.sign_response(KEY, 200, "GET", "/health", NONCE_B, b"", ts, NONCE_A)
        assert fleet_lib.verify_response(KEY, 200, "GET", "/health", NONCE_B, headers, b"", NOW,
                                         fleet_lib.NonceCache()) == expected, ("response", ts)


def test_t16_foreign_beacon_checked_before_signature():
    raw = fleet_lib.make_beacon(OTHER_KEY, 8190, NOW, NONCE_A)
    assert fleet_lib.verify_beacon(KEY, raw, NOW, fleet_lib.NonceCache()) == ("foreign", None)
    # A foreign tag with a garbage signature is still "foreign", not "bad_sig".
    garbage = fleet_lib.canonical_json(dict(_beacon_dict(raw), sig="x"))
    assert fleet_lib.verify_beacon(KEY, garbage, NOW, fleet_lib.NonceCache()) == ("foreign", None)
    assert fleet_lib.fleet_tag(KEY) != fleet_lib.fleet_tag(OTHER_KEY)
    assert len(fleet_lib.fleet_tag(KEY)) == 16


def test_t17_nonce_cache_retention():
    clock = _Clock(1000.0)
    cache = fleet_lib.NonceCache(retention=120, clock=clock)
    assert cache.check_and_add("n1") is True
    clock.t = 1119.9
    assert cache.check_and_add("n1") is False
    clock.t = 1120.1
    assert cache.check_and_add("n1") is True        # re-recorded at 1120.1
    assert cache.check_and_add("n2") is True
    clock.t = 1300.0
    cache.prune()
    assert len(cache) == 0


def test_t18_beacon_carries_no_secret():
    raw = fleet_lib.make_beacon(KEY, 8190, NOW, NONCE_A)
    assert TEST_TOKEN.encode("ascii") not in raw
    assert KEY not in raw
    assert KEY.hex().encode("ascii") not in raw
    assert len(raw) < 2048
    assert set(_beacon_dict(raw)) == {"proto", "fleet_tag", "port", "ts", "nonce", "sig"}


def test_signing_never_raises_on_hostile_input():
    """LAN noise or a hostile sender: non-ASCII text, deep nesting and odd header
    containers must come back as a plain status, never as an exception (an exception
    would reach the daemon's thread guard and write a log line, breaking F29a)."""
    good = _beacon_dict(fleet_lib.make_beacon(KEY, 8190, NOW, NONCE_A))
    cache = fleet_lib.NonceCache()
    assert fleet_lib.verify_beacon(KEY, fleet_lib.canonical_json(dict(good, fleet_tag="é" * 16)),
                                   NOW, cache) == ("foreign", None)
    assert fleet_lib.verify_beacon(KEY, fleet_lib.canonical_json(dict(good, sig="é" * 64)),
                                   NOW, cache) == ("bad_sig", None)
    assert fleet_lib.verify_beacon(KEY, b"[" * 3000, NOW, cache) == ("malformed", None)
    assert fleet_lib.verify_beacon(KEY, b"\xff\xfe\x00", NOW, cache) == ("malformed", None)
    headers = fleet_lib.sign_request(KEY, "GET", "/health", b"", NOW, NONCE_A)
    assert fleet_lib.verify_request(KEY, "GET", "/héalth", headers, b"", NOW, cache) == "bad"
    assert fleet_lib.verify_request(KEY, "GET", "/health", dict(headers, **{"X-Fleet-Nonce": "é" * 32}),
                                    b"", NOW, cache) == "bad"
    assert fleet_lib.verify_request(KEY, "GET", "/health", None, b"", NOW, cache) == "bad"


# --- T7-T9, T12: skill verification and the child environment (F13-F15, F54a) -------

def test_t7_probe_url():
    assert fleet_lib.probe_url({"type": "vllm", "url": "http://127.0.0.1:8177/v1"}) == \
        "http://127.0.0.1:8177/v1/models"
    assert fleet_lib.probe_url({"type": "ollama", "url": "http://127.0.0.1:11434/v1"}) == \
        "http://127.0.0.1:11434/api/tags"
    assert fleet_lib.probe_url({"type": "vllm", "url": "http://127.0.0.1:8177/v1/"}) == \
        "http://127.0.0.1:8177/v1/models"


def test_t8_parse_loaded_models():
    ollama = b'{"models": [{"name": "qwen3.5:9b", "model": "qwen3.5:9b", "size": 1, "details": {}}]}'
    assert fleet_lib.parse_loaded_models("ollama", ollama) == {"qwen3.5:9b"}
    vllm = b'{"object": "list", "data": [{"id": "qwen38-6bit", "object": "model", "max_model_len": 16384}]}'
    assert fleet_lib.parse_loaded_models("vllm", vllm) == {"qwen38-6bit"}
    both = b'{"models": [{"name": "a:latest", "model": "a"}]}'
    assert fleet_lib.parse_loaded_models("ollama", both) == {"a:latest", "a"}
    for kind, body in (("vllm", b"not json"), ("ollama", b"<html>"),
                       ("vllm", b'{"data": "x"}'), ("vllm", b'{"data": [1]}'),
                       ("vllm", b'{"models": []}'), ("ollama", b'{"data": []}'),
                       ("ollama", b'{"models": [5]}'), ("vllm", b'{"data": [{"id": 5}]}'),
                       ("ollama", b'{"models": [{"name": 5, "model": null}]}'),
                       ("vllm", b"[]"), ("lmstudio", vllm)):
        assert fleet_lib.parse_loaded_models(kind, body) == set(), (kind, body)


def test_t9_verify_skills():
    entry = {"model": "qwen38-6bit", "skills": ["investigator", "analyst", "planner"]}
    assert fleet_lib.verify_skills(entry, {"qwen38-6bit", "other"}) == [
        {"skill": "investigator", "model": "qwen38-6bit", "verified": True},
        {"skill": "analyst", "model": "qwen38-6bit", "verified": True},
        {"skill": "planner", "model": "qwen38-6bit", "verified": True},
    ]
    assert [s["verified"] for s in fleet_lib.verify_skills(entry, {"qwen3.5:9b"})] == [False] * 3
    assert fleet_lib.verify_skills({"model": "m", "skills": []}, {"m"}) == []


def test_t12_build_child_env():
    environ = {
        "QWEN_AGENT_FLEET_ID": TEST_FLEET_ID,
        "QWEN_AGENT_FLEET_TOKEN": TEST_TOKEN,
        "QWEN_AGENT_FLEET_EXTRA": "x",
        "SKILL_ENDPOINT_RESEARCHER": "http://192.168.1.168:11434/v1",
        "SKILL_MODEL_RESEARCHER": "qwen3.5:9b",
        "PATH": "/usr/bin:/bin",
        "HOME": "/Users/test",
        "QWEN_AGENT_HOST_ID": "mac-local",
        "QWEN_AGENT_SEARXNG_URL": "http://10.0.0.5:8888",
        "QWEN_AGENT_DAEMON_URL": "http://127.0.0.1:1",
    }
    before = dict(environ)
    env = fleet_lib.build_child_env(environ, "http://127.0.0.1:8190")
    assert environ == before
    for gone in ("QWEN_AGENT_FLEET_ID", "QWEN_AGENT_FLEET_TOKEN", "QWEN_AGENT_FLEET_EXTRA",
                 "SKILL_ENDPOINT_RESEARCHER", "SKILL_MODEL_RESEARCHER"):
        assert gone not in env
    for kept in ("PATH", "HOME", "QWEN_AGENT_HOST_ID", "QWEN_AGENT_SEARXNG_URL"):
        assert env[kept] == environ[kept]
    assert env["QWEN_AGENT_DAEMON_URL"] == "http://127.0.0.1:8190"
    assert not any(TEST_TOKEN in v for v in env.values())


# --- T19, T20, Review Focus 2: the liveness table (F34, F35) ------------------------

def _health(version="v2026.10.17", proto=1, role="agent"):
    return {"host_id": "x", "role": role, "version": version, "proto": proto, "discovery": "beacon"}


_SKILLS = [{"skill": "researcher", "model": "qwen3.5:9b", "verified": True, "busy": False}]


def _table(clock):
    return fleet_lib.LivenessTable(_f18_registry(), "mac-local", 90, clock=clock)


def test_t19_live_window_and_transitions():
    clock = _Clock(1000.0)
    table = _table(clock)
    assert table.unheard_registered() == ["ollama-168", "orchestrator"]
    table.bind("ollama-168", "192.168.1.168", 8190, _health(), _SKILLS, "beacon")
    assert table.is_live("ollama-168")
    assert table.unheard_registered() == ["orchestrator"]
    assert table.transitions() == [("ollama-168", "live")]
    assert table.transitions() == []
    clock.t = 1090.0
    assert table.is_live("ollama-168")
    clock.t = 1090.001
    assert not table.is_live("ollama-168")
    assert table.live_peers() == []
    assert table.unheard_registered() == ["ollama-168", "orchestrator"]
    assert table.transitions() == [("ollama-168", "down")]
    assert table.transitions() == []
    assert not table.is_live("orchestrator")
    assert "mac-local" not in table.unheard_registered()


def test_t20_order_fields_rebind_refresh():
    clock = _Clock(1000.0)
    table = _table(clock)
    table.bind("orchestrator", "192.168.1.170", 8190, _health(role="orchestrator"), [], "poll")
    table.bind("ollama-168", "192.168.1.168", 8190, _health(), _SKILLS, "beacon")
    assert [p["host_id"] for p in table.live_peers()] == ["ollama-168", "orchestrator"]
    clock.t = 1001.0
    assert table.heard("192.168.1.170", 8190, "beacon") == "orchestrator"
    assert [p["host_id"] for p in table.live_peers()] == ["orchestrator", "ollama-168"]
    clock.t = 1002.0
    assert table.heard("192.168.1.168", 8190, "beacon") == "ollama-168"
    assert table.heard("192.168.1.170", 8190, "beacon") == "orchestrator"
    peers = table.live_peers()
    assert [p["host_id"] for p in peers] == ["ollama-168", "orchestrator"]  # tie -> host_id
    for p in peers:
        assert set(p) == set(fleet_lib.PEER_FIELDS) and len(p) == 10
    assert peers[0]["age"] == 0.0 and peers[0]["compatible"] is True
    assert table.heard("192.168.1.99", 8190, "beacon") is None
    assert table.heard("192.168.1.168", 8191, "beacon") is None

    # A bind attempt from a new address moves the record (F34).
    table.bind("ollama-168", "192.168.1.201", 8190, _health(), _SKILLS, "beacon")
    assert table.record("ollama-168")["address"] == "192.168.1.201"
    assert table.heard("192.168.1.168", 8190, "beacon") is None

    # due_for_refresh and heard_beacon_within.
    clock.t = 1062.5
    assert table.due_for_refresh(60) == ["ollama-168", "orchestrator"]
    table.refresh("orchestrator", _health(version="v2", proto=2, role="orchestrator"), [], "poll")
    assert table.due_for_refresh(60) == ["ollama-168"]
    rec = table.record("orchestrator")
    assert rec["version"] == "v2" and rec["compatible"] is False and rec["heard_via"] == "poll"
    assert table.heard_beacon_within(90) is True
    assert table.heard_beacon_within(10) is False
    clock.t = 1300.0
    assert table.heard_beacon_within(90) is False


def test_review_focus_2_restarted_peer_is_rebound_not_revived():
    """Review Focus 2: a peer that aged out (rebooted, or restarted on a new release)
    and beacons again from the same address must not be revived by heard(); the
    daemon re-binds it through signed /health, which picks up the new version."""
    clock = _Clock(1000.0)
    table = _table(clock)
    table.bind("ollama-168", "192.168.1.168", 8190, _health(version="v2026.10.17"), _SKILLS, "beacon")
    clock.t = 1200.0
    assert table.heard("192.168.1.168", 8190, "beacon") is None
    assert not table.is_live("ollama-168")
    table.bind("ollama-168", "192.168.1.168", 8190, _health(version="v2026.10.18"), _SKILLS, "beacon")
    assert table.live_peers()[0]["version"] == "v2026.10.18"
