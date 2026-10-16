"""Shared helpers for the fleet test suites (fleet spec Section 11.2, D10).

Not a test module (pytest does not collect it). Loopback only: every server a
helper starts binds 127.0.0.1, and every daemon gets explicit beacon targets.
Every spawned process gets HOME=<tmp dir> and a QWEN_AGENT_SEARXNG_URL that points
at a closed port, so no test touches real user state or needs a running SearXNG.
"""

import http.client
import http.server
import importlib.machinery
import importlib.util
import json
import os
import signal
import socket
import subprocess
import sys
import threading
import time

WS = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
sys.path.insert(0, WS)
import fleet_lib  # noqa: E402

AGENTD = os.path.join(WS, "bin", "qwen-agentd")
QWEN_AGENT = os.path.join(WS, "bin", "qwen-agent")
TEST_FLEET_ID = "0123456789abcdef"
TEST_TOKEN = "5e" * 32
TEST_KEY = bytes.fromhex(TEST_TOKEN)
OTHER_FLEET_ID = "fedcba9876543210"
OTHER_TOKEN = "a7" * 32
INTEGRATION_SCALE = "0.1"
SELF_UPDATE_SCALE = "0.01"

_ISSUED_PORTS = set()
_DROP_PREFIXES = ("QWEN_AGENT_", "SKILL_ENDPOINT_", "SKILL_MODEL_")
_PROXY_KEYS = ("http_proxy", "https_proxy", "all_proxy", "no_proxy")


def load_script(name, path):
    """Import an extensionless script (bin/qwen-agentd, bin/qwen-agent) as a module."""
    loader = importlib.machinery.SourceFileLoader(name, path)
    spec = importlib.util.spec_from_loader(name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def free_port():
    """A port free for both TCP and UDP on 127.0.0.1, never handed out twice per process."""
    for _ in range(20):
        tcp = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            tcp.bind(("127.0.0.1", 0))
            port = tcp.getsockname()[1]
            try:
                udp.bind(("127.0.0.1", port))
            except OSError:
                continue
        finally:
            tcp.close()
            udp.close()
        if port not in _ISSUED_PORTS:
            _ISSUED_PORTS.add(port)
            return port
    raise AssertionError("no free TCP+UDP port after 20 tries")


def clean_env(home, **extra):
    """os.environ without QWEN_AGENT_*, SKILL_ENDPOINT_*/SKILL_MODEL_* or proxy variables,
    with HOME=home and a SearXNG URL at a closed port; `extra` is applied last."""
    env = dict((k, v) for k, v in os.environ.items()
               if not k.startswith(_DROP_PREFIXES) and k.lower() not in _PROXY_KEYS)
    env["HOME"] = str(home)
    env["QWEN_AGENT_SEARXNG_URL"] = "http://127.0.0.1:%d" % free_port()
    env.update(extra)
    return env


def make_fleet(home, fleet_id=TEST_FLEET_ID, token=TEST_TOKEN):
    """Write <home>/.config/qwen-agent/fleet.env; returns its path."""
    path = os.path.join(str(home), ".config", "qwen-agent", "fleet.env")
    fleet_lib.write_fleet_env(path, fleet_id, token)
    return path
