"""Tests for bin/pipeline-stop and bin/story-server-restore (spec
docs/superpowers/specs/2026-10-21-clean-stop-design.md).

Run from the workspace root: python3 -m pytest tests/test_clean_stop.py
"""

import importlib.machinery
import os
import signal
import subprocess
import sys
import time

WS = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
stop = importlib.machinery.SourceFileLoader(
    "pipeline_stop", os.path.join(WS, "bin", "pipeline-stop")).load_module()
RESTORE = os.path.join(WS, "bin", "story-server-restore")
PY = "/opt/homebrew/Cellar/python@3.12/3.12.15/Frameworks/Python.framework/Versions/3.12/" \
     "Resources/Python.app/Contents/MacOS/Python"


def test_cs1_classify():
    cases = [
        (PY + " /w/bin/character create kyra --seed-image /s.png", "job"),
        (PY + " /w/bin/character train kyra --video", "job"),
        (PY + " bin/action create kick --clip a.mp4", "job"),
        (PY + " bin/character create t --seed-image /h/.local/share/qwen-agent/movie-ui/uploads/"
              "ab.png --no-review", "job"),
        (PY + " /w/bin/ltx-movie a story --story-id s", "job"),
        ("/bin/bash /w/bin/character-train-vlm /py kyra --video", "job"),
        ("/bin/bash /w/bin/action-train-vlm /py kick", "job"),
        (PY + " /w/character_dataset.py qwenedit --spec /x.json", "worker"),
        (PY + " /w/character_dataset.py zimage --spec /x.json", "worker"),
        ("/x/.venv/bin/python /x/.venv/bin/ltx-2-mlx generate --model m", "worker"),
        ("/x/.venv/bin/python /x/.venv/bin/ltx-2-mlx train --config c", "worker"),
        ("/x/mflux/.venv/bin/mflux-train --config c", "worker"),
        (PY + " /w/bin/ltx-mlx-render m.json o.mp4", "worker"),
        (PY + " /w/bin/character list", None),
        (PY + " /w/bin/character show kyra", None),
        (PY + " bin/movie-ui", None),
        (PY + " /w/bin/movie-ui-job --grace 15.0 /j", None),
        ("/bin/bash /w/bin/story-server mlx-vision", None),
        ("/py -m mlx_vlm.server --model /m --port 8177", None),
        ("vim notes-ltx-2-mlx-train.txt", None),
    ]
    for command, kind in cases:
        assert stop.classify(command) == kind, command


def test_cs2_targets_and_descendants():
    rows = [(10, 1, PY + " /w/bin/character create kyra --no-review"),
            (11, 10, PY + " /w/character_dataset.py qwenedit --spec s"),
            (12, 11, "/usr/bin/some-helper"),
            (13, 10, "/bin/bash /w/bin/story-server mlx-vision"),
            (14, 13, "/py -m mlx_vlm.server --port 8177"),
            (20, 1, PY + " /w/bin/pipeline-stop")]
    found = stop.targets(rows, me={20, 1})
    assert {pid: kind for pid, (kind, _) in found.items()} == {10: "job", 11: "worker"}
    # The story server a cleanup started (13, 14) is never a descendant to signal.
    assert stop.descendants(rows, [10]) == {11, 12}


def test_cs3_shown_drops_the_interpreter():
    assert stop.shown(PY + " /w/bin/character create kyra") == "/w/bin/character create kyra"
    assert stop.shown("/bin/bash /w/bin/action-train-vlm") == "/bin/bash /w/bin/action-train-vlm"


def _fake_story_server(tmp_path, state="STOPPED", sleep=0):
    calls = tmp_path / "calls.txt"
    script = tmp_path / "story-server"
    script.write_text(
        "#!/bin/bash\n"
        "if [ \"$1\" = status ]; then echo '  state:          %s'; exit 0; fi\n"
        "echo \"$1 sid=$(ps -o sess= -p $$) pgid=$(ps -o pgid= -p $$)\" >> %s\n"
        "sleep %s\n" % (state, calls, sleep))
    script.chmod(0o755)
    return str(script), calls


def _run_restore(tmp_path, script, *args):
    env = dict(os.environ, STORY_SERVER_RESTORE_BIN=script, HOME=str(tmp_path))
    return subprocess.run([sys.executable, RESTORE] + list(args), env=env, capture_output=True,
                          text=True, timeout=30)


def test_cs4_restore_starts_in_its_own_session(tmp_path):
    script, calls = _fake_story_server(tmp_path)
    result = _run_restore(tmp_path, script, "--wait")
    assert result.returncode == 0, result.stderr
    assert "own session" in result.stdout
    line = calls.read_text().split()
    assert line[0] == "mlx-vision"
    # A new session: its process group is not the caller's.
    assert line[2] != "pgid=%d" % os.getpgid(0)


def test_cs5_restore_is_a_no_op_when_serving(tmp_path):
    script, calls = _fake_story_server(tmp_path, state="SERVING mlx-vision")
    result = _run_restore(tmp_path, script)
    assert result.returncode == 0 and "already serving mlx-vision" in result.stdout
    assert not calls.exists()


def test_cs6_restore_without_wait_returns_at_once(tmp_path):
    script, calls = _fake_story_server(tmp_path, sleep=5)
    started = time.monotonic()
    result = _run_restore(tmp_path, script)
    assert result.returncode == 0 and time.monotonic() - started < 4
    for _ in range(50):
        if calls.exists():
            break
        time.sleep(0.1)
    assert calls.read_text().startswith("mlx-vision")
    os.killpg(int(calls.read_text().split("pgid=")[1]), signal.SIGTERM)


def test_cs7_restore_usage():
    result = subprocess.run([sys.executable, RESTORE, "a", "b"], capture_output=True, text=True)
    assert result.returncode == 2 and "usage" in result.stderr
