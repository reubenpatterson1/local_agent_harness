"""bin/qwen-agentd tests: CLI subcommands and single-machine multi-daemon integration
(fleet spec Section 11.5, D8).

Run from the workspace root: python3 -m pytest tests/test_fleet_integration.py -v
Loopback only. Every daemon runs with --timing-scale 0.1, explicit beacon targets,
and HOME=<tmp dir>; the autouse fixture SIGKILLs every process group a test
started and stops every stub server. Time bounds below are the spec's bounds
scaled by 0.1.
"""

import errno
import http.client
import http.server
import json
import os
import signal
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
import fleet_testutil as ftu  # noqa: E402


# --- CLI: init-fleet, join, selftest, top-level errors (F23, F26, F92, F93, F99) ---------

@pytest.fixture
def agentd(monkeypatch, tmp_path):
    """bin/qwen-agentd imported in-process with HOME pointed at an empty temp dir."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    return ftu.load_script("qwen_agentd_cli", ftu.AGENTD)


def test_cli_init_fleet(agentd, capsys):
    assert agentd.main(["init-fleet"]) == 0
    out = capsys.readouterr().out.splitlines()
    assert len(out) == 4
    assert out[0].startswith("fleet_id: ")
    fleet_id = out[0][len("fleet_id: "):]
    assert fleet_lib.FLEET_ID_RE.fullmatch(fleet_id)
    assert out[1] == "join string (shown once; copy it to each other host over ssh):"
    assert out[3] == ("next: create fleets/%s.json (see the fleet spec, Section 2.4), commit, "
                      "tag a release" % fleet_id)
    path = fleet_lib.fleet_env_path()
    assert fleet_lib.parse_join_string(out[2]) == fleet_lib.load_fleet_env(path)
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o600
    assert agentd.main(["init-fleet"]) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ("qwen-agentd: %s already exists; remove it first to create a new fleet\n" % path)


def test_cli_join(agentd, capsys, monkeypatch):
    s = fleet_lib.make_join_string(ftu.TEST_FLEET_ID, ftu.TEST_TOKEN)
    assert agentd.main(["join", "not-a-join-string"]) == 2
    assert capsys.readouterr().err == "qwen-agentd: invalid join string\n"
    prompts = []
    monkeypatch.setattr(agentd.getpass, "getpass", lambda prompt: prompts.append(prompt) or s + "\n")
    assert agentd.main(["join"]) == 0
    assert prompts == ["join string: "]
    assert capsys.readouterr().out == "qwen-agentd: joined fleet %s\n" % ftu.TEST_FLEET_ID
    path = fleet_lib.fleet_env_path()
    assert fleet_lib.load_fleet_env(path) == (ftu.TEST_FLEET_ID, ftu.TEST_TOKEN)
    assert agentd.main(["join", s]) == 0
    assert capsys.readouterr().out == "qwen-agentd: already joined fleet %s\n" % ftu.TEST_FLEET_ID
    other = fleet_lib.make_join_string(ftu.OTHER_FLEET_ID, ftu.OTHER_TOKEN)
    assert agentd.main(["join", other]) == 2
    assert capsys.readouterr().err == ("qwen-agentd: %s exists for a different fleet; remove it first\n" % path)


def test_cli_internal_error_is_one_line(agentd, capsys, monkeypatch):
    def boom(*args):
        raise RuntimeError("disk on fire")
    monkeypatch.setattr(agentd.fleet_lib, "write_fleet_env", boom)
    assert agentd.main(["init-fleet"]) == 1
    err = capsys.readouterr().err
    assert err == "qwen-agentd: internal error: RuntimeError: disk on fire\n"
    assert "Traceback" not in err


def test_cli_selftest_runs_the_unit_suite(tmp_path):
    env = ftu.clean_env(tmp_path, QWEN_AGENT_FLEET_TOKEN=ftu.TEST_TOKEN)
    proc = subprocess.run([sys.executable, ftu.AGENTD, "selftest"], env=env, cwd=str(tmp_path),
                          capture_output=True, text=True, timeout=120)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert " passed" in proc.stdout


def test_cli_unknown_subcommand_exits_2(tmp_path):
    proc = subprocess.run([sys.executable, ftu.AGENTD, "frobnicate"], env=ftu.clean_env(tmp_path),
                          capture_output=True, text=True, timeout=30)
    assert proc.returncode == 2 and "Traceback" not in proc.stderr
    assert "invalid choice: 'frobnicate'" in proc.stderr
