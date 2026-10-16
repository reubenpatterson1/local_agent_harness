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
