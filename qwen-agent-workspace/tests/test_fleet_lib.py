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
