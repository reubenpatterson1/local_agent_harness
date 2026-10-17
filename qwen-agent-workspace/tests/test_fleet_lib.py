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
    paths = [fleet_lib.fleet_env_path(i) for i in fleet_lib.agent_ids_on_disk()]
    paths = [p for p in paths if os.path.exists(p)]
    if not paths:
        pytest.skip("no fleet.env on this host")
    inside = subprocess.run(["git", "-C", WS, "rev-parse", "--is-inside-work-tree"],
                            capture_output=True, text=True)
    if inside.returncode != 0 or inside.stdout.strip() != "true":
        pytest.skip("WS is not in a git worktree")
    needles = []
    for path in paths:
        _fleet_id, token = fleet_lib.load_fleet_env(path)
        needles.extend((token.encode("ascii"), fleet_lib.token_key(token)))
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


def test_beacon_alone_cannot_keep_a_record_live():
    # bind at t=1000, then heard() every 30 s with no refresh; live through t=1360, not at t=1361+
    clock = _Clock(1000.0)
    table = _table(clock)
    table.bind("ollama-168", "192.168.1.168", 8190, _health(), _SKILLS, "beacon")
    for t in (1030.0 + 30.0 * i for i in range(12)):
        clock.t = t
        assert table.heard("192.168.1.168", 8190, "beacon") == "ollama-168"
    assert [p["host_id"] for p in table.live_peers()] == ["ollama-168"]
    clock.t = 1390.0
    assert table.heard("192.168.1.168", 8190, "beacon") is None
    assert table.live_peers() == []


# --- T21-T24, Review Focus 3 and 4: routing and the harness clients (F42, F57-F68) ----

def _skill(name, verified=True, busy=False, model="m"):
    return {"skill": name, "model": model, "verified": verified, "busy": busy}


def _peer(host_id, skills, compatible=True, age=1.0):
    return {"host_id": host_id, "address": "192.168.1.5", "port": 8190, "role": "agent",
            "version": "v2026.10.17", "proto": 1, "compatible": compatible,
            "skills": skills, "heard_via": "beacon", "age": age}


def _view(self_skills, peers):
    return {"schema": fleet_lib.PEERS_SCHEMA,
            "self": {"host_id": "mac-local", "role": "agent", "version": "dev", "proto": 1,
                     "discovery": "beacon", "skills": self_skills},
            "peers": peers}


def test_t21_route_candidates():
    peers = [_peer("p1", [_skill("researcher")]), _peer("p2", [_skill("researcher")])]
    view = _view([_skill("researcher")], peers)
    snapshot = copy.deepcopy(view)
    assert fleet_lib.route_candidates("researcher", view) == [fleet_lib.LOCAL]
    assert view == snapshot
    view = _view([_skill("researcher", verified=False)], peers)
    assert fleet_lib.route_candidates("researcher", view) == ["p1", "p2"]
    view = _view([], [_peer("p1", [_skill("researcher", verified=False)]),
                      _peer("p2", [_skill("researcher")], compatible=False),
                      _peer("p3", [_skill("analyst")]),
                      _peer("p4", [_skill("researcher", busy=True)]),
                      _peer("p0", [_skill("researcher")])])
    assert fleet_lib.route_candidates("researcher", view) == ["p4", "p0"]
    assert fleet_lib.route_candidates("planner", view) == []
    assert not fleet_lib.HOST_ID_RE.fullmatch(fleet_lib.LOCAL)


def test_t22_failover():
    outcomes = {"a": "busy", "b": "timeout", "c": "bad_signature", "d": "ok"}
    calls = []

    def attempt(host_id):
        calls.append(host_id)
        return outcomes[host_id], ({"answer": host_id} if outcomes[host_id] == "ok" else None)

    result = fleet_lib.failover(["a", "b", "c", "d"], attempt)
    assert result == {"outcome": "ok", "host_id": "d", "envelope": {"answer": "d"},
                      "tried": [("a", "busy"), ("b", "timeout"), ("c", "bad_signature")]}
    assert calls == ["a", "b", "c", "d"]
    result = fleet_lib.failover(["a", "b"], attempt)
    assert result == {"outcome": "exhausted", "host_id": None, "envelope": None,
                      "tried": [("a", "busy"), ("b", "timeout")]}

    def raising(host_id):
        if host_id == "x":
            raise ValueError("boom")
        return "ok", {"answer": "y"}

    result = fleet_lib.failover(["x", "y"], raising)
    assert result["outcome"] == "ok" and result["tried"] == [("x", "error")]
    assert fleet_lib.failover([], attempt) == {"outcome": "exhausted", "host_id": None,
                                               "envelope": None, "tried": []}

    def interrupted(host_id):
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        fleet_lib.failover(["a"], interrupted)


def test_t23_delegate_enum_and_valid_view():
    view = _view([_skill("analyst")], [_peer("p1", [_skill("researcher")]),
                                       _peer("p2", [_skill("planner", verified=False)])])
    targets = ("investigator", "analyst", "planner", "researcher")
    assert fleet_lib.delegate_enum(targets, view) == ["analyst", "researcher"]
    assert fleet_lib.delegate_enum(("researcher", "analyst"), view) == ["researcher", "analyst"]
    assert fleet_lib.valid_view(view) is True
    assert fleet_lib.valid_view(dict(view, schema="qwen-agentd.peers.v2")) is False
    assert fleet_lib.valid_view(dict((k, v) for k, v in view.items() if k != "self")) is False
    bad = copy.deepcopy(view)
    bad["peers"][0]["skills"][0]["verified"] = "true"
    assert fleet_lib.valid_view(bad) is False
    bad = copy.deepcopy(view)
    bad["peers"][0]["compatible"] = 1
    assert fleet_lib.valid_view(bad) is False
    bad = copy.deepcopy(view)
    bad["self"]["skills"] = None
    assert fleet_lib.valid_view(bad) is False
    for obj in (None, [], "x", 5, {"schema": fleet_lib.PEERS_SCHEMA}):
        assert fleet_lib.valid_view(obj) is False


def test_t24_routes_loopback_and_daemon_url():
    assert fleet_lib.http_route("GET", "/health") == ("signed", "health")
    assert fleet_lib.http_route("GET", "/skills") == ("signed", "skills")
    assert fleet_lib.http_route("POST", "/run") == ("signed", "run")
    assert fleet_lib.http_route("GET", "/peers") == ("loopback", "peers")
    assert fleet_lib.http_route("POST", "/delegate") == ("loopback", "delegate")
    for method, path in (("GET", "/run"), ("POST", "/health"), ("GET", "/peers/"),
                         ("PUT", "/peers"), ("GET", "/health?x=1"), ("GET", "/nowhere")):
        assert fleet_lib.http_route(method, path) == ("unknown", None)
    assert fleet_lib.is_loopback_client("127.0.0.1") is True
    assert fleet_lib.is_loopback_client("::1") is True
    for ip in ("127.0.0.2", "192.168.1.5", "::ffff:127.0.0.1"):
        assert fleet_lib.is_loopback_client(ip) is False
    assert fleet_lib.daemon_url_from_env({}) == ("http://127.0.0.1:8190", None)
    assert fleet_lib.daemon_url_from_env({"QWEN_AGENT_DAEMON_URL": ""}) == ("http://127.0.0.1:8190", None)
    assert fleet_lib.daemon_url_from_env({"QWEN_AGENT_DAEMON_URL": "http://127.0.0.1:18190"}) == \
        ("http://127.0.0.1:18190", None)
    for bad in ("http://192.168.1.5:8190", "http://localhost:8190", "https://127.0.0.1:8190",
                "http://127.0.0.1:0", "http://127.0.0.1:65536", "http://127.0.0.1:8190/"):
        url, warning = fleet_lib.daemon_url_from_env({"QWEN_AGENT_DAEMON_URL": bad})
        assert url is None
        assert warning == ("qwen-agent: warning: ignoring QWEN_AGENT_DAEMON_URL=%s: it must be "
                           "http://127.0.0.1:<port>; fleet routing disabled" % bad)


def test_review_focus_3_daemon_url_with_trailing_newline_is_rejected():
    """Review Focus 3: QWEN_AGENT_DAEMON_URL set from a file or a heredoc often ends in
    a newline. It is rejected with the F63 warning, never half-accepted."""
    for value in ("http://127.0.0.1:8190\n", " http://127.0.0.1:8190", "http://127.0.0.1:8190 "):
        url, warning = fleet_lib.daemon_url_from_env({"QWEN_AGENT_DAEMON_URL": value})
        assert url is None and warning.startswith("qwen-agent: warning: ignoring QWEN_AGENT_DAEMON_URL=")


class _Scripted(object):
    """An in-process loopback HTTP server: routes[(method, path)] = (status, body bytes)."""

    def __init__(self, routes):
        self.routes = routes
        self.requests = []
        outer = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def _serve(self):
                length = int(self.headers.get("Content-Length") or 0)
                body = self.rfile.read(length) if length else b""
                outer.requests.append((self.command, self.path, body))
                status, raw = outer.routes.get((self.command, self.path), (404, b""))
                self.send_response(status)
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            do_GET = _serve
            do_POST = _serve

        self.httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = "http://127.0.0.1:%d" % self.httpd.server_address[1]
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


def _closed_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


_ENVELOPE = {"schema": "qwen-agent.oneshot.v1", "status": "ok", "answer": "A", "error": None,
             "rounds": 1, "tool_calls": []}


def test_fetch_view_mapping():
    view = _view([_skill("analyst")], [])
    srv = _Scripted({("GET", "/peers"): (200, json.dumps(view).encode())})
    try:
        assert fleet_lib.fetch_view(srv.url) == (view, None)
        warning = ("qwen-agent: warning: qwen-agentd at %s returned an unrecognized fleet view; "
                   "fleet routing disabled" % srv.url)
        for status, body in ((403, b""), (200, b"not json"), (200, b'{"schema": "x"}'), (500, b"{}")):
            srv.routes[("GET", "/peers")] = (status, body)
            assert fleet_lib.fetch_view(srv.url) == (None, warning)
    finally:
        srv.close()
    assert fleet_lib.fetch_view("http://127.0.0.1:%d" % _closed_port()) == (None, None)
    assert fleet_lib.fetch_view(None) == (None, None)


def test_delegate_once_mapping():
    srv = _Scripted({})
    try:
        def answer(status, obj):
            srv.routes[("POST", "/delegate")] = (status, obj if isinstance(obj, bytes) else json.dumps(obj).encode())
            return fleet_lib.delegate_once(srv.url, "researcher", "té", "ollama-168")

        assert answer(200, {"outcome": "ok", "envelope": _ENVELOPE, "detail": ""}) == ("ok", _ENVELOPE, "")
        method, path, body = srv.requests[-1]
        assert (method, path) == ("POST", "/delegate")
        assert json.loads(body) == {"skill": "researcher", "task": "té", "host_id": "ollama-168"}
        assert answer(200, {"outcome": "busy", "envelope": None, "detail": ""}) == ("busy", None, "")
        assert answer(500, b"") == ("daemon_error", None, "http 500")
        assert answer(200, b"[]") == ("daemon_error", None, "bad response")
        assert answer(200, {"outcome": "ok", "detail": ""}) == ("daemon_error", None, "bad response")
        assert answer(200, {"outcome": "ok", "envelope": {"schema": "x"}, "detail": ""}) == \
            ("daemon_error", None, "bad response")
        assert answer(200, b"garbage") == ("daemon_error", None, "bad response")
    finally:
        srv.close()
    outcome, envelope, detail = fleet_lib.delegate_once("http://127.0.0.1:%d" % _closed_port(), "a", "t", "h")
    assert (outcome, envelope) == ("daemon_error", None) and detail == "ConnectionRefusedError"
    assert fleet_lib.delegate_once(None, "a", "t", "h") == ("daemon_error", None, "no daemon")


def test_review_focus_4_proxy_environment_is_ignored(monkeypatch):
    """Review Focus 4: the Mac runs Netskope, and shells often export proxy variables.
    Fleet traffic goes through http.client, so a dead proxy in the environment changes
    nothing."""
    dead = "http://127.0.0.1:%d" % _closed_port()
    for name in ("HTTP_PROXY", "http_proxy", "HTTPS_PROXY", "https_proxy", "ALL_PROXY", "all_proxy"):
        monkeypatch.setenv(name, dead)
    monkeypatch.delenv("NO_PROXY", raising=False)
    monkeypatch.delenv("no_proxy", raising=False)
    view = _view([], [])
    srv = _Scripted({("GET", "/peers"): (200, json.dumps(view).encode()),
                     ("POST", "/delegate"): (200, json.dumps({"outcome": "ok", "envelope": _ENVELOPE,
                                                              "detail": ""}).encode())})
    try:
        assert fleet_lib.fetch_view(srv.url) == (view, None)
        assert fleet_lib.delegate_once(srv.url, "researcher", "t", "h")[0] == "ok"
    finally:
        srv.close()
    with open(fleet_lib.__file__, encoding="utf-8") as f:
        source = f.read()
    assert "import urllib" not in source and "urlopen" not in source


# --- T27, T28, T29a: tags, the update cycle, state, pruning, version (F80-F88a) -----

def test_t27_tag_key_and_select_candidate():
    ordered = ["v2026.10.17", "v2026.10.17.1", "v2026.10.17.2", "v2026.10.17.10", "v2026.10.18"]
    assert sorted(reversed(ordered), key=fleet_lib.tag_key) == ordered
    assert fleet_lib.tag_key("v2026.10.17.10") == (2026, 10, 17, 10)
    for bad in ("v2026.10.17.0", "2026.10.17", "v2026.1.17", "vX", "v2026.10.17\n", "", None, "dev"):
        assert fleet_lib.tag_key(bad) is None, bad

    def ancestor_of(pairs):
        return lambda a, b: (a, b) in pairs

    tags = ["v2026.10.17", "v2026.10.18", "v2026.10.19", "v2026.10.20", "v2026.10.16", "junk", "v2026.10.18"]
    every = ancestor_of({("v2026.10.17", t) for t in tags})
    assert fleet_lib.select_candidate(tags, "v2026.10.17", [], every) == "v2026.10.20"
    # A higher tag that does not descend from current is skipped.
    some = ancestor_of({("v2026.10.17", "v2026.10.18"), ("v2026.10.17", "v2026.10.19")})
    assert fleet_lib.select_candidate(tags, "v2026.10.17", [], some) == "v2026.10.19"
    assert fleet_lib.select_candidate(tags, "v2026.10.17", ["v2026.10.20", "v2026.10.19"], every) == "v2026.10.18"
    assert fleet_lib.select_candidate(["v2026.10.16", "v2026.10.17", "x"], "v2026.10.17", [], every) is None
    assert fleet_lib.select_candidate(tags, "dev", [], every) is None
    asked = []

    def lazy(a, b):
        asked.append(b)
        return True

    assert fleet_lib.select_candidate(tags, "v2026.10.17", [], lazy) == "v2026.10.20"
    assert asked == ["v2026.10.20"]


class _FakeCtx(object):
    """A scripted F85 ctx that records every call in order."""

    def __init__(self, tags=("v2026.01.01", "v2026.01.02"), fetch_ok=True, dirty=False,
                 lock_free=True, stage_ok=True, gate_ok=True, stage_raises=False, swap_raises=False):
        self.tags = list(tags)
        self.fetch_ok, self.dirty, self.lock_free = fetch_ok, dirty, lock_free
        self.stage_ok, self.gate_ok = stage_ok, gate_ok
        self.stage_raises, self.swap_raises = stage_raises, swap_raises
        self.state = {"from": None, "to": "v2026.01.01", "status": "ok", "attempts": 0,
                      "bad_tags": ["v2025.12.31"]}
        self.locked = False
        self.calls = []
        self.logs = []

    def fetch(self):
        self.calls.append("fetch")
        return (True, "") if self.fetch_ok else (False, "exit 128: fatal: unable to access")

    def list_tags(self):
        return list(self.tags)

    def is_ancestor(self, a, b):
        return True

    def current_tag(self):
        return "v2026.01.01"

    def is_dirty(self):
        return self.dirty

    def try_lock(self):
        if not self.lock_free:
            return False
        self.locked = True
        self.calls.append("lock")
        return True

    def unlock(self):
        assert self.locked
        self.locked = False
        self.calls.append("unlock")

    def read_state(self):
        return copy.deepcopy(self.state)

    def write_state(self, state):
        self.calls.append(("write_state", copy.deepcopy(state)))
        self.state = copy.deepcopy(state)

    def stage(self, tag):
        self.calls.append(("stage", tag))
        if self.stage_raises:
            raise RuntimeError("disk full")
        return (True, "") if self.stage_ok else (False, "exit 128: fatal: invalid reference")

    def gate(self, tag):
        self.calls.append(("gate", tag))
        return (True, "") if self.gate_ok else (False, "selftest exit 1")

    def unstage(self, tag):
        self.calls.append(("unstage", tag))

    def swap(self, tag):
        self.calls.append(("swap", tag))
        if self.swap_raises:
            raise OSError("read-only file system")

    def restart(self):
        self.calls.append("restart")

    def log(self, level, msg):
        self.logs.append((level, msg))


def test_t28_run_update_cycle_outcomes():
    ctx = _FakeCtx(fetch_ok=False)
    assert fleet_lib.run_update_cycle(ctx) == "fetch_failed"
    assert ctx.logs == [("WARNING", "update: git fetch failed (exit 128: fatal: unable to access); "
                                    "retrying next cycle")]

    ctx = _FakeCtx(tags=("v2026.01.01",))
    assert fleet_lib.run_update_cycle(ctx) == "up_to_date" and ctx.logs == []

    ctx = _FakeCtx(dirty=True)
    assert fleet_lib.run_update_cycle(ctx) == "dirty"
    assert ctx.logs[0][0] == "WARNING" and "not updating" in ctx.logs[0][1]

    ctx = _FakeCtx(lock_free=False)
    assert fleet_lib.run_update_cycle(ctx) == "busy"
    assert ctx.logs == [("INFO", "update: v2026.01.02 deferred: a run is in flight")]

    ctx = _FakeCtx(stage_ok=False)
    assert fleet_lib.run_update_cycle(ctx) == "stage_failed"
    assert not ctx.locked and "unlock" in ctx.calls
    assert ctx.state["bad_tags"] == ["v2025.12.31"]

    ctx = _FakeCtx(gate_ok=False)
    assert fleet_lib.run_update_cycle(ctx) == "gate_failed"
    assert not ctx.locked
    assert ctx.state["bad_tags"] == ["v2025.12.31", "v2026.01.02"]
    assert ("unstage", "v2026.01.02") in ctx.calls
    assert ctx.logs[-1] == ("WARNING", "update: v2026.01.02 failed its gate (selftest exit 1); marked bad")

    ctx = _FakeCtx(stage_raises=True)
    assert fleet_lib.run_update_cycle(ctx) == "error"
    assert not ctx.locked and ctx.logs[-1] == ("ERROR", "update: RuntimeError: disk full")

    ctx = _FakeCtx(swap_raises=True)
    before = copy.deepcopy(ctx.state)
    assert fleet_lib.run_update_cycle(ctx) == "error"
    assert not ctx.locked and ctx.state == before and "restart" not in ctx.calls

    ctx = _FakeCtx()
    assert fleet_lib.run_update_cycle(ctx) == "switched"
    pending = {"from": "v2026.01.01", "to": "v2026.01.02", "status": "pending", "attempts": 0,
               "bad_tags": ["v2025.12.31"]}
    i_write = ctx.calls.index(("write_state", pending))
    i_swap = ctx.calls.index(("swap", "v2026.01.02"))
    assert i_write < i_swap < ctx.calls.index("restart")
    assert ctx.locked is True          # held through the restart (F85 step 4)
    assert ("INFO", "update: switching v2026.01.01 -> v2026.01.02") in ctx.logs


def test_t29a_state_io_prune_and_version(tmp_path):
    default = {"from": None, "to": None, "status": "ok", "attempts": 0, "bad_tags": []}
    path = str(tmp_path / "update-state.json")
    assert fleet_lib.read_state(path) == default
    for text in ("not json", "[]", '{"from": null}',
                 '{"from": null, "to": null, "status": "weird", "attempts": 0, "bad_tags": []}',
                 '{"from": null, "to": null, "status": "ok", "attempts": true, "bad_tags": []}',
                 '{"from": null, "to": null, "status": "ok", "attempts": -1, "bad_tags": []}',
                 '{"from": 1, "to": null, "status": "ok", "attempts": 0, "bad_tags": []}',
                 '{"from": null, "to": null, "status": "ok", "attempts": 0, "bad_tags": [1]}'):
        with open(path, "w") as f:
            f.write(text)
        assert fleet_lib.read_state(path) == default, text
    state = {"from": "v2026.01.01", "to": "v2026.01.02", "status": "pending", "attempts": 2,
             "bad_tags": ["v2026.01.03"]}
    fleet_lib.write_state(path, state)
    assert fleet_lib.read_state(path) == state
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o600
    assert not os.path.exists(path + ".tmp")
    with open(path, "rb") as f:
        assert f.read() == fleet_lib.canonical_json(state) + b"\n"

    present = ["v2026.01.01", "v2026.01.02", "v2026.01.03", "v2026.01.04", "v2026.01.05",
               "v2026.01.06", "notes", ".DS_Store"]
    st = {"from": "v2026.01.02", "to": "v2026.01.03", "status": "ok", "attempts": 0, "bad_tags": []}
    assert fleet_lib.releases_to_prune(present, "v2026.01.03", st) == ["v2026.01.01"]
    st["from"] = None
    assert fleet_lib.releases_to_prune(present, "v2026.01.03", st) == ["v2026.01.01", "v2026.01.02"]

    d = tmp_path / "D"
    ws = d / "releases" / "v2026.10.17" / "qwen-agent-workspace"
    ws.mkdir(parents=True)
    assert fleet_lib.release_version(str(ws), str(d)) == "v2026.10.17"
    (d / "current").symlink_to("releases/v2026.10.17")
    assert fleet_lib.release_version(str(d / "current" / "qwen-agent-workspace"), str(d)) == "v2026.10.17"
    link = tmp_path / "linked-D"
    link.symlink_to(d)
    assert fleet_lib.release_version(str(ws), str(link)) == "v2026.10.17"
    assert fleet_lib.release_version(WS, str(d)) == "dev"
    other = d / "releases" / "notatag" / "qwen-agent-workspace"
    other.mkdir(parents=True)
    assert fleet_lib.release_version(str(other), str(d)) == "dev"
    wrong = d / "releases" / "v2026.10.18" / "workspace"
    wrong.mkdir(parents=True)
    assert fleet_lib.release_version(str(wrong), str(d)) == "dev"
    assert fleet_lib.deploy_root("x") == os.path.expanduser("~/agents/x")
    assert fleet_lib.log_dir("x") == os.path.expanduser("~/agents/x/logs")


def test_tag_re_rejects_non_ascii_digits():
    assert fleet_lib.TAG_RE.fullmatch("v2026.10.17")
    assert fleet_lib.TAG_RE.fullmatch("v٢٠٢٦.10.17") is None


# --- T26, T29b: bin/qwen-agentd-launch (F89, F83) ------------------------------------

def _load_launcher():
    path = os.path.join(WS, "bin", "qwen-agentd-launch")
    loader = importlib.machinery.SourceFileLoader("qwen_agentd_launch", path)
    spec = importlib.util.spec_from_loader("qwen_agentd_launch", loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def test_t26_launcher_step():
    launch = _load_launcher()
    assert launch.MAX_START_ATTEMPTS == fleet_lib.MAX_START_ATTEMPTS == 3
    for status in ("ok", "rolled_back"):
        state = {"from": "v1", "to": "v2026.01.02", "status": status, "attempts": 0, "bad_tags": []}
        assert launch.launcher_step(state, True) == (state, "exec")
    pending = {"from": "v2026.01.01", "to": "v2026.01.02", "status": "pending", "attempts": 0,
               "bad_tags": ["v2025.12.31"]}
    assert launch.launcher_step(pending, True) == (dict(pending, attempts=1), "exec")
    assert launch.launcher_step(dict(pending, attempts=1), True) == (dict(pending, attempts=2), "exec")
    new, action = launch.launcher_step(dict(pending, attempts=2), True)
    assert action == "rollback"
    assert new == {"from": "v2026.01.01", "to": "v2026.01.02", "status": "rolled_back", "attempts": 3,
                   "bad_tags": ["v2025.12.31", "v2026.01.02"]}
    again, _ = launch.launcher_step(dict(pending, attempts=2, bad_tags=["v2026.01.02"]), True)
    assert again["bad_tags"] == ["v2026.01.02"]
    assert launch.launcher_step(dict(pending, attempts=2), False) == (dict(pending, attempts=3), "exec")
    with open(os.path.join(WS, "bin", "qwen-agentd-launch"), encoding="utf-8") as f:
        source = f.read()
    assert "import fleet_lib" not in source and "from fleet_lib" not in source


def test_t29b_launcher_and_fleet_lib_state_files_agree(tmp_path):
    launch = _load_launcher()
    state = {"from": "v2026.01.01", "to": "v2026.01.02", "status": "pending", "attempts": 1,
             "bad_tags": ["v2026.01.03"]}
    a = str(tmp_path / "a.json")
    b = str(tmp_path / "b.json")
    fleet_lib.write_state(a, state)
    launch.write_state(b, state)
    with open(a, "rb") as fa, open(b, "rb") as fb:
        assert fa.read() == fb.read()
    assert launch.read_state(a) == fleet_lib.read_state(b) == state
    assert stat.S_IMODE(os.stat(b).st_mode) == 0o600
    for text in ("garbage", '{"from": null}'):
        with open(a, "w") as f:
            f.write(text)
        assert launch.read_state(a) == fleet_lib.read_state(a) == {
            "from": None, "to": None, "status": "ok", "attempts": 0, "bad_tags": []}
    assert launch.read_state(str(tmp_path / "missing.json")) == fleet_lib.read_state(str(tmp_path / "missing.json"))


# --- multi-agent hosts: agent IDs, names, resolution (multi-agent spec M2, M6, M8, M21, M22) ---

BAD_AGENT_IDS = ("", "Mac", "../x", "a/b", "mac-local\n", None)


def test_mt1a_service_and_command_names(monkeypatch):
    monkeypatch.setenv("HOME", "/h")
    assert fleet_lib.launchd_label("mac-local") == "com.qwen-agent.qwen-agentd.mac-local"
    assert fleet_lib.systemd_unit("ollama-168") == "qwen-agentd-ollama-168.service"
    assert fleet_lib.command_path("mac-local") == "/h/.local/bin/qwen-agent-mac-local"
    assert fleet_lib.default_command_path() == "/h/.local/bin/qwen-agent"
    for bad in BAD_AGENT_IDS:
        for func in (fleet_lib.launchd_label, fleet_lib.systemd_unit, fleet_lib.command_path):
            with pytest.raises(ValueError):
                func(bad)


def test_mt6_agent_ids_on_disk_and_resolve_agent(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    agents = tmp_path / "agents"
    assert fleet_lib.agent_ids_on_disk() == []
    assert fleet_lib.resolve_agent(None) == (
        None, "qwen-agentd: no agent found in %s; pass --agent-id ID" % agents)
    (agents / "alpha").mkdir(parents=True)
    (agents / "alpha" / "fleet.env").write_text("x")
    assert fleet_lib.agent_ids_on_disk() == ["alpha"]
    assert fleet_lib.resolve_agent(None) == ("alpha", None)
    (agents / "bravo").mkdir()
    (agents / "bravo" / "current").symlink_to("releases/v2026.01.01")
    (agents / "Bad_Name").mkdir()
    (agents / "Bad_Name" / "fleet.env").write_text("x")
    (agents / "empty").mkdir()
    (agents / "file").write_text("x")
    (agents / "notes").mkdir()
    (agents / "notes" / "readme").write_text("x")
    assert fleet_lib.agent_ids_on_disk() == ["alpha", "bravo"]
    assert fleet_lib.resolve_agent(None) == (
        None, "qwen-agentd: more than one agent in %s (alpha, bravo); pass --agent-id ID" % agents)
    assert fleet_lib.resolve_agent("zed") == ("zed", None)
    assert fleet_lib.resolve_agent("Bad") == (None, "qwen-agentd: invalid --agent-id 'Bad'")


# --- multi-agent hosts: registry ports, beacon targets, agent_port, fleet.env (M4, M7, M16, M19, M24) ---

def test_mt4_port_range_and_duplicate_address(monkeypatch):
    reg = _f18_registry()
    reg["hosts"]["mac-local"]["port"] = 1023
    errors = fleet_lib.validate_registry(reg, TEST_FLEET_ID)
    assert len(errors) == 1 and errors[0].startswith("hosts.mac-local.port: must be an integer in 1024..65535")
    for good in (1024, 65535):
        reg["hosts"]["mac-local"]["port"] = good
        assert fleet_lib.validate_registry(reg, TEST_FLEET_ID) == []

    def agent(port):
        return {"role": "agent", "address": "192.168.1.185", "port": port,
                "model_server": {"type": "vllm", "url": "http://127.0.0.1:8000/v1"},
                "model": "m", "skills": []}
    two = {"protocol": 1, "fleet_id": TEST_FLEET_ID,
           "hosts": {"vision-185": agent(8190), "gemma-185": agent(8190)}}
    assert fleet_lib.validate_registry(two, TEST_FLEET_ID) == [
        "hosts.vision-185: address 192.168.1.185:8190 is already used by hosts.gemma-185"]
    two["hosts"]["gemma-185"]["port"] = 8191
    assert fleet_lib.validate_registry(two, TEST_FLEET_ID) == []


def test_mt5_default_beacon_targets(tmp_path):
    assert fleet_lib.default_beacon_targets(_f18_registry()) == [("255.255.255.255", 8190)]
    reg = _f18_registry()
    reg["hosts"]["mac-local"]["port"] = 9000
    reg["hosts"]["ollama-168"]["port"] = 8191
    reg["hosts"]["gemma-185"] = dict(reg["hosts"]["ollama-168"], address="192.168.1.185", port=8190)
    reg["hosts"]["orchestrator"]["port"] = 8190
    expected = [("255.255.255.255", 8190), ("255.255.255.255", 8191), ("255.255.255.255", 9000)]
    assert fleet_lib.default_beacon_targets(reg) == expected
    reg["hosts"]["orchestrator"]["port"] = 9100
    with_orchestrator = expected + [("255.255.255.255", 9100)]
    assert fleet_lib.default_beacon_targets(reg) == with_orchestrator
    loaded = fleet_lib.load_registry(_write_json(tmp_path / "r.json", reg), TEST_FLEET_ID)
    assert fleet_lib.default_beacon_targets(loaded) == with_orchestrator
    raw = _f18_registry()
    loaded = fleet_lib.load_registry(_write_json(tmp_path / "f18.json", raw), TEST_FLEET_ID)
    assert fleet_lib.default_beacon_targets(loaded) == fleet_lib.default_beacon_targets(raw)


def test_mt7_agent_port_and_atomic_fleet_env(tmp_path):
    fleets = tmp_path / "fleets"
    assert fleet_lib.agent_port(str(fleets), "h1") == (None, [])
    fleets.mkdir()
    assert fleet_lib.agent_port(str(fleets), "h1") == (None, [])

    def registry(fleet_id, port):
        host = {"role": "agent", "address": "127.0.0.1", "model_server": {"type": "vllm",
                "url": "http://127.0.0.1:9/v1"}, "model": "m", "skills": []}
        if port is not None:
            host["port"] = port
        return {"protocol": 1, "fleet_id": fleet_id, "hosts": {"h1": host}}
    _write_json(fleets / "a.json", registry(TEST_FLEET_ID, 9001))
    assert fleet_lib.agent_port(str(fleets), "h1") == (9001, ["a.json"])
    assert fleet_lib.agent_port(str(fleets), "h2") == (None, [])
    _write_json(fleets / "a.json", registry(TEST_FLEET_ID, None))
    assert fleet_lib.agent_port(str(fleets), "h1") == (8190, ["a.json"])
    _write_json(fleets / "a.json", registry(TEST_FLEET_ID, 9001))
    _write_json(fleets / "b.json", registry("fedcba9876543210", 9001))
    assert fleet_lib.agent_port(str(fleets), "h1") == (9001, ["a.json", "b.json"])
    _write_json(fleets / "b.json", registry("fedcba9876543210", 9002))
    assert fleet_lib.agent_port(str(fleets), "h1") == (None, ["a.json", "b.json"])
    _write_json(fleets / "b.json", registry("fedcba9876543210", 9001))
    (fleets / "bad.json").write_text("{not json")
    invalid = registry(TEST_FLEET_ID, 9005)
    invalid["protocol"] = 2
    _write_json(fleets / "invalid.json", invalid)
    (fleets / "notes.txt").write_text(json.dumps(registry(TEST_FLEET_ID, 9006)))
    assert fleet_lib.agent_port(str(fleets), "h1") == (9001, ["a.json", "b.json"])

    path = str(tmp_path / "agents" / "h1" / "fleet.env")
    os.makedirs(os.path.dirname(path))
    with open(path + ".tmp", "w") as f:
        f.write("leftover")
    fleet_lib.write_fleet_env(path, TEST_FLEET_ID, TEST_TOKEN)
    assert not os.path.lexists(path + ".tmp")
    assert stat.S_IMODE(os.stat(os.path.dirname(path)).st_mode) == 0o700
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o600
    assert fleet_lib.load_fleet_env(path) == (TEST_FLEET_ID, TEST_TOKEN)
    with open(path, "rb") as f:
        before = f.read()
    with pytest.raises(FileExistsError):
        fleet_lib.write_fleet_env(path, "fedcba9876543210", OTHER_TOKEN)
    with open(path, "rb") as f:
        assert f.read() == before
    assert not os.path.lexists(path + ".tmp")


def test_mt1b_agent_root_paths(monkeypatch):
    monkeypatch.setenv("HOME", "/h")
    assert fleet_lib.deploy_root("mac-local") == "/h/agents/mac-local"
    assert fleet_lib.fleet_env_path("mac-local") == "/h/agents/mac-local/fleet.env"
    assert fleet_lib.log_dir("mac-local") == "/h/agents/mac-local/logs"
    for bad in BAD_AGENT_IDS:
        for func in (fleet_lib.deploy_root, fleet_lib.fleet_env_path, fleet_lib.log_dir):
            with pytest.raises(ValueError):
                func(bad)
    assert not hasattr(fleet_lib, "DEPLOY_ROOT")
    assert not hasattr(fleet_lib, "SYSTEMD_UNIT")


# --- multi-agent hosts: the generated commands (multi-agent spec M9-M12) ----------------

def _m9_wrapper(home):
    return ("#!/bin/sh\n"
            "# qwen-agentd wrapper\n"
            "# agent-id: mac-local\n"
            "QWEN_AGENT_DAEMON_URL=http://127.0.0.1:8190\n"
            "export QWEN_AGENT_DAEMON_URL\n"
            "exec '%s/agents/mac-local/current/qwen-agent-workspace/bin/qwen-agent' \"$@\"\n" % home).encode("utf-8")


def _fake_release_harness(home, host_id, script):
    """An executable stand-in for A(<id>)/current/qwen-agent-workspace/bin/qwen-agent."""
    target = os.path.join(str(home), "agents", host_id, "current", "qwen-agent-workspace", "bin", "qwen-agent")
    os.makedirs(os.path.dirname(target))
    with open(target, "w") as f:
        f.write(script)
    os.chmod(target, 0o755)


def _run_wrapper(tmp_path, data, argv, env_extra=None):
    w = str(tmp_path / "w")
    with open(w, "wb") as f:
        f.write(data)
    os.chmod(w, 0o755)
    env = dict((k, v) for k, v in os.environ.items() if k != "QWEN_AGENT_DAEMON_URL")
    env.update(env_extra or {})
    return subprocess.run(["/bin/sh", w] + list(argv), env=env, capture_output=True, timeout=30)


def test_mt2_wrapper_bytes_and_detection(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", "/h")
    data = fleet_lib.wrapper_bytes("mac-local", 8190)
    assert data == _m9_wrapper("/h")
    for bad in BAD_AGENT_IDS:
        with pytest.raises(ValueError):
            fleet_lib.wrapper_bytes(bad, 8190)
    for bad_port in (1023, 65536, True, "8190"):
        with pytest.raises(ValueError):
            fleet_lib.wrapper_bytes("mac-local", bad_port)
    monkeypatch.setenv("HOME", "/h/it's")
    assert fleet_lib.wrapper_bytes("x", 8190).decode("utf-8").splitlines()[-1] == (
        "exec '/h/it'\\''s/agents/x/current/qwen-agent-workspace/bin/qwen-agent' \"$@\"")
    assert fleet_lib.is_wrapper(data) is True
    assert fleet_lib.is_wrapper(b"#!/bin/sh\n# qwen-agentd wrapper\n") is True
    for not_wrapper in (b"# qwen-agentd wrapper extra\n", b"#  qwen-agentd wrapper\n", b""):
        assert fleet_lib.is_wrapper(not_wrapper) is False
    assert fleet_lib.wrapper_agent_id(data) == "mac-local"
    assert fleet_lib.wrapper_agent_id(b"#!/bin/sh\n# qwen-agentd wrapper\n") is None
    assert fleet_lib.wrapper_agent_id(b"# qwen-agentd wrapper\n# agent-id: Bad\n") is None

    monkeypatch.setenv("HOME", str(tmp_path))
    _fake_release_harness(tmp_path, "x", "#!/bin/sh\nprintf '%s;%s;%s' \"$QWEN_AGENT_DAEMON_URL\" \"$1\" \"$2\"\n")
    proc = _run_wrapper(tmp_path, fleet_lib.wrapper_bytes("x", 8191), ["a b", "c"])
    assert (proc.returncode, proc.stdout) == (0, b"http://127.0.0.1:8191;a b;c")


def test_multi_agent_focus_1_wrapper_overrides_an_inherited_daemon_url(tmp_path, monkeypatch):
    """Multi-agent Review Focus 1: a shell that already exports QWEN_AGENT_DAEMON_URL (another agent's port,
    or a leftover from debugging) still reaches the wrapper's own agent."""
    monkeypatch.setenv("HOME", str(tmp_path))
    _fake_release_harness(tmp_path, "x", "#!/bin/sh\nprintf '%s' \"$QWEN_AGENT_DAEMON_URL\"\n")
    for inherited in ("http://127.0.0.1:9999", "", "not a url"):
        proc = _run_wrapper(tmp_path, fleet_lib.wrapper_bytes("x", 8191), [],
                            {"QWEN_AGENT_DAEMON_URL": inherited})
        assert (proc.returncode, proc.stdout) == (0, b"http://127.0.0.1:8191"), inherited


def test_multi_agent_focus_2_wrapper_passes_shell_metacharacters_verbatim(tmp_path, monkeypatch):
    """Multi-agent Review Focus 2: prompts typed through the wrapper keep their exact bytes: globs, $VARS,
    quotes, backslashes, newlines and empty arguments are neither expanded nor dropped."""
    monkeypatch.setenv("HOME", str(tmp_path))
    _fake_release_harness(tmp_path, "x", "#!/bin/sh\nfor a in \"$@\"; do printf '[%s]' \"$a\"; done\n")
    argv = ["*", "$HOME", "what's \"this\"?", "a\\b", "line1\nline2", "", "--user-prompt=x y"]
    proc = _run_wrapper(tmp_path, fleet_lib.wrapper_bytes("x", 8191), argv)
    assert proc.returncode == 0
    assert proc.stdout == "".join("[%s]" % a for a in argv).encode("utf-8")


def test_mt3_classify_write_and_actions(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", "/h")
    data = fleet_lib.wrapper_bytes("mac-local", 8190)
    path = str(tmp_path / "cmd")
    assert fleet_lib.classify_command_path(path) == ("absent", None)
    os.symlink(str(tmp_path / "nowhere"), path)
    assert fleet_lib.classify_command_path(path) == ("symlink", None)
    os.unlink(path)
    with open(path, "wb") as f:
        f.write(data)
    assert fleet_lib.classify_command_path(path) == ("wrapper", "mac-local")
    with open(path, "wb") as f:
        f.write(b"#!/bin/sh\necho mine\n")
    assert fleet_lib.classify_command_path(path) == ("other", None)
    assert fleet_lib.classify_command_path(str(tmp_path)) == ("other", None)
    big = b"# qwen-agentd wrapper\n"
    with open(path, "wb") as f:
        f.write(big + b"x" * (fleet_lib.WRAPPER_MAX_BYTES + 1 - len(big)))
    assert os.path.getsize(path) == fleet_lib.WRAPPER_MAX_BYTES + 1
    assert fleet_lib.classify_command_path(path) == ("other", None)

    out = str(tmp_path / "bin" / "qwen-agent-x")
    os.makedirs(os.path.dirname(out))
    with open(out + ".tmp", "w") as f:
        f.write("leftover")
    old_umask = os.umask(0o077)
    try:
        fleet_lib.write_wrapper(out, data)
    finally:
        os.umask(old_umask)
    assert stat.S_IMODE(os.stat(out).st_mode) == 0o755
    assert not os.path.lexists(out + ".tmp")
    with open(out, "rb") as f:
        assert f.read() == data
    target = str(tmp_path / "target")
    with open(target, "w") as f:
        f.write("untouched")
    link = str(tmp_path / "bin" / "qwen-agent")
    os.symlink(target, link)
    fleet_lib.write_wrapper(link, data)
    assert not os.path.islink(link)
    with open(link, "rb") as f:
        assert f.read() == data
    with open(target) as f:
        assert f.read() == "untouched"

    for kind, action in (("absent", "write"), ("symlink", "write"), ("wrapper", "write"), ("other", "refuse")):
        assert fleet_lib.agent_command_action(kind) == action
    rows = [
        (("absent", None, "h1", False), "write"),
        (("absent", None, "h1", True), "write"),
        (("wrapper", "h1", "h1", False), "write"),
        (("wrapper", "h1", "h1", True), "write"),
        (("wrapper", "h2", "h1", True), "write"),
        (("wrapper", None, "h1", True), "write"),
        (("symlink", None, "h1", True), "write"),
        (("other", None, "h1", True), "refuse"),
        (("wrapper", "h2", "h1", False), "keep"),
        (("wrapper", None, "h1", False), "keep"),
        (("symlink", None, "h1", False), "keep"),
        (("other", None, "h1", False), "keep"),
    ]
    for args, action in rows:
        assert fleet_lib.default_command_action(*args) == action, args
