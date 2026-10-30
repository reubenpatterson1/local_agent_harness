"""Tests for bin/location end to end (docs/superpowers/specs/2026-10-29-location-lora-design.md,
Sections 2.2, 2.12, 3.1 and 6.1, test table 6.5: LT1-LT10, with the plan's Review Focus pins).

Run from the workspace root: python3 -m pytest -q -p no:cacheprovider tests/test_location_tool.py
Stdlib plus pytest and PIL. No test reads the real HOME, renders, trains, runs Z-Image or the
editor, contacts a model server or touches port 8178: the VLM, the story server, the gates and the
image children are fakes (spec 6.2), the bin/location-train-vlm checks run against stub tools in
a temporary bin/, and every library lives under tmp_path (HOME, CHARACTER_LIBRARY_DIR,
LOCATION_LIBRARY_DIR and LORA_CATALOG_DIR). Real ffmpeg/ffprobe wrap the kept stills.
"""

import importlib.machinery
import json
import os
import shutil
import signal
import subprocess
import sys
import time

import pytest
from PIL import Image

WS = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
sys.path.insert(0, WS)
sys.path.insert(0, os.path.join(WS, "tests"))

import character_dataset  # noqa: E402
import location_testutil as lt  # noqa: E402
import story_engine_testutil as seu  # noqa: E402

TOOL_PATH = os.path.join(WS, "bin", "location")
tool = importlib.machinery.SourceFileLoader("location_tool", TOOL_PATH).load_module()
ll = tool.location_lib
CAFE_DESC = ("a small café terrace in Montréal with wrought iron chairs, striped awnings, cracked "
             "terracotta tiles and a faded blue sign above the door")
PASS = {"match_score": 9, "people_visible": False, "shot": "wide shot", "time_of_day": "dusk",
        "weather": "fog"}


@pytest.fixture(autouse=True)
def env(monkeypatch, tmp_path):
    return seu.set_story_env(monkeypatch, tmp_path)


def _fakes(monkeypatch, vlm_up=True):
    """Every create/edit gate passes, the VLM passes every check, and the Z-Image child writes
    solid 1024x640 stills; returns the story-server call list."""
    calls = []

    def _child(spec, loc_dir, step):
        for job in spec["jobs"]:
            Image.new("RGB", (1024, 640), (60, 90, 120)).save(job["output_path"])
        return {"jobs": [{"output_path": j["output_path"], "status": "ok", "seconds": 1.0}
                         for j in spec["jobs"]], "injected_lora_modules": None}

    monkeypatch.setattr(character_dataset, "image_data_url", lambda path, max_side=768: "file:" + path)
    monkeypatch.setattr(character_dataset, "vlm_call", lambda parts, max_tokens=600: json.dumps(PASS))
    monkeypatch.setattr(character_dataset, "run_zimage_child", _child)
    monkeypatch.setattr(character_dataset, "run_edit_child", _child)
    monkeypatch.setattr(character_dataset, "edit_models_missing", lambda: [])
    monkeypatch.setattr(character_dataset, "restore_story_server",
                        lambda wait=False: calls.append("restore") or 0)
    monkeypatch.setattr(character_dataset, "story_server", lambda cmd: calls.append(cmd) or 0)
    monkeypatch.setattr(character_dataset, "wait_for_vlm", lambda timeout_s: True)
    monkeypatch.setattr(character_dataset, "wait_for_avail", lambda gib, timeout_s: True)
    monkeypatch.setattr(character_dataset, "vlm_ready", lambda: vlm_up)
    monkeypatch.setattr(character_dataset, "busy_process", lambda: None)
    monkeypatch.setattr(character_dataset, "story_server_state", lambda: "STOPPED")
    monkeypatch.setattr(character_dataset, "free_gib", lambda path: 100.0)
    return calls


def _photo(tmp_path, name, size=(800, 500), colour=(10, 20, 30)):
    path = str(tmp_path / name)
    Image.new("RGB", size, colour).save(path)
    return path


def _tree(lib):
    return sorted(os.listdir(lib)) if os.path.isdir(lib) else []


def _subprocess(args, env=None, timeout=120):
    return subprocess.run([sys.executable, "-B", TOOL_PATH] + list(args), capture_output=True,
                          text=True, env=env or dict(os.environ), timeout=timeout)


# --- LT1-LT3: help, the stdlib-only list/show, show's output (L1.2) ------------------------

def test_lt1_help(env):
    top = _subprocess(["--help"])
    assert top.returncode == 0
    for command in ("create", "edit", "list", "show"):
        assert command in top.stdout
    create = _subprocess(["create", "--help"])
    assert create.returncode == 0
    for flag in ("--description TEXT", "--photo PATH", "--trigger WORD", "--seed N", "--force",
                 "--regenerate", "--new-seed"):
        assert flag in create.stdout, flag
    assert "3-5 photos" in " ".join(create.stdout.split())
    edit = _subprocess(["edit", "--help"])
    assert edit.returncode == 0 and "--description TEXT" in edit.stdout
    for command in ("list", "show"):
        assert _subprocess([command, "--help"]).returncode == 0


def test_lt2_list_and_show_need_only_the_standard_library(env):
    lt.harbour(env["locations"])
    script = (
        "import importlib.abc, importlib.machinery, sys\n"
        "class Block(importlib.abc.MetaPathFinder):\n"
        "    def find_spec(self, name, path=None, target=None):\n"
        "        if name.split('.')[0] in ('PIL', 'psutil', 'character_dataset',\n"
        "                                  'location_dataset', 'character_lib'):\n"
        "            raise ImportError('blocked: ' + name)\n"
        "        return None\n"
        "sys.meta_path.insert(0, Block())\n"
        "m = importlib.machinery.SourceFileLoader('location_tool', %r).load_module()\n"
        "print(m.main(['list']), m.main(['show', 'harbour-street']))\n"
    ) % TOOL_PATH
    proc = subprocess.run([sys.executable, "-I", "-c", script], capture_output=True, text=True,
                          env=dict(os.environ), timeout=60)
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.splitlines()[-1] == "0 0"
    assert "harbour-street   harboplc" in proc.stdout


def test_lt3_show(env, capsys):
    lib = env["locations"]
    data = lt.make_location(lib, "old-mill", "oldmiplc", lt.MILL_DESC, source="photos",
                            stills=True)
    ldir = os.path.join(lib, "old-mill")
    open(os.path.join(lib, "old-mill", "contact_sheet.jpg"), "wb").close()
    assert tool.main(["show", "old-mill"]) == 0
    out = capsys.readouterr().out
    record, files = out.split("files:\n")
    assert json.loads(record) == data
    assert files.splitlines() == [
        "  ok       %s" % os.path.join(ldir, "location.json"),
        "  MISSING  %s" % os.path.join(ldir, "photos", "photo_01.png"),
        "  ok       %s" % os.path.join(ldir, "contact_sheet.jpg"),
        "  ok       %s" % os.path.join(ldir, "lora", "video.safetensors"),
        "  ok       %s" % os.path.join(ldir, "lora", "stills.safetensors"),
        "  MISSING  %s" % os.path.join(ldir, "tests", "video_lora.mp4"),
        "  MISSING  %s" % os.path.join(ldir, "tests", "video_control.mp4")]
    lt.harbour(lib, status="dataset")
    assert tool.main(["show", "harbour-street"]) == 0
    assert capsys.readouterr().out.split("files:\n")[1].splitlines() == [
        "  ok       %s" % os.path.join(lib, "harbour-street", "location.json")]
    assert tool.main(["show", "nowhere"]) == 2
    assert capsys.readouterr().err == "Error: unknown location: nowhere (no %s)\n" % (
        os.path.join(lib, "nowhere", "location.json"))
    assert tool.main(["show", "Bad"]) == 2
    assert capsys.readouterr().err == (
        "Error: location name must match [a-z][a-z0-9-]{1,23}, got 'Bad'\n")
    assert tool.main(["list"]) == 0
    assert capsys.readouterr().out.splitlines()[0].startswith("NAME             TRIGGER")


# --- LT4, LT5: argument refusals (L5.1) -----------------------------------------------------

def test_lt4_create_argument_refusals(env, monkeypatch, tmp_path, capsys):
    lib = env["locations"]
    _fakes(monkeypatch)
    lt.harbour(lib, status="dataset")
    ll.register_trigger("harboplc", "harbour-street")
    import character_lib
    character_lib.register_trigger("kyrawmn", "kyra")
    a = _photo(tmp_path, "a.png")
    copy = str(tmp_path / "copy-of-a.png")
    shutil.copy2(a, copy)
    text = str(tmp_path / "notes.png")
    with open(text, "w") as f:
        f.write("not an image")
    small = _photo(tmp_path, "small.png", size=(500, 400))
    missing = str(tmp_path / "missing.png")
    d = ["--description", lt.MILL_DESC]
    cases = [
        (["create", "Bad_Name"] + d,
         "location name must match [a-z][a-z0-9-]{1,23}, got 'Bad_Name'"),
        (["create", "harbour-street"] + d,
         "location harbour-street already exists (%s); use --regenerate to rebuild its dataset"
         % os.path.join(lib, "harbour-street")),
        (["create", "old-mill", "--description", "a quay with boats"],
         "--description: description: must be 15-40 words, got 4"),
        (["create", "old-mill", "--description", "one " + lt.MILL_DESC[3:]],
         '--description: description: must start with "a ", "an " or "the "'),
        (["create", "old-mill", "--description", lt.MILL_DESC.replace(" a slate", ". A slate")],
         "--description: description: must be one noun phrase with no . ! ? or double quote"),
        (["create", "old-mill"], "create needs --description or at least one --photo"),
        (["create", "old-mill"] + ["--photo", a] * 25, "at most 24 --photo, got 25"),
        (["create", "old-mill", "--photo", missing], "--photo not found: %s" % missing),
        (["create", "old-mill", "--photo", small],
         "--photo %s is 500x400; its centred 16:10 crop is 500x312, smaller than the 512x320 "
         "minimum" % small),
        (["create", "old-mill", "--photo", a, "--photo", copy],
         "--photo %s is the same file as photo 1" % copy),
        (["create", "old-mill", "--trigger", "harboplc"] + d,
         "trigger harboplc is already used by location harbour-street; triggers are never reused"),
        (["create", "old-mill", "--trigger", "kyrawmn"] + d,
         "trigger kyrawmn is already used by character kyra; triggers are never reused"),
        (["create", "old-mill", "--trigger", "Bad"] + d,
         "trigger must match [a-z][a-z0-9]{3,15}, got 'Bad'"),
        (["create", "old-mill", "--trigger", "weir"] + d,
         "trigger weir must not be a word of the description"),
        (["create", "old-mill", "--new-seed"] + d, "--new-seed needs --regenerate"),
        (["create", "old-mill", "--seed", "2147483648"] + d,
         "--seed must be between 0 and 2147483647"),
    ]
    before = _tree(lib)
    for argv, message in cases:
        assert tool.main(argv) == 2, argv
        assert capsys.readouterr().err == "Error: %s\n" % message, argv
    assert tool.main(["create", "old-mill", "--photo", text]) == 2
    assert capsys.readouterr().err.startswith("Error: --photo is not a readable image: %s: " % text)
    assert _tree(lib) == before
    with open(os.path.join(lib, ".triggers")) as f:
        assert f.read() == "harboplc harbour-street\n"


def test_lt5_regenerate_refusals(env, monkeypatch, tmp_path, capsys):
    _fakes(monkeypatch)
    lt.harbour(env["locations"], status="untrained")
    with open(os.path.join(env["locations"], "harbour-street", "location.json"), "rb") as f:
        before = f.read()
    flag_message = ("--regenerate takes no --photo or --trigger: a location keeps the photos and "
                    "the trigger it was created with")
    for extra, message in ((["--photo", _photo(tmp_path, "p.png")], flag_message),
                           (["--trigger", "harbtwo"], flag_message),
                           (["--seed", "1", "--new-seed"], "give --seed or --new-seed, not both"),
                           (["--seed", "2147483648"], "--seed must be between 0 and 2147483647"),
                           (["--seed", "-1"], "--seed must be between 0 and 2147483647")):
        assert tool.main(["create", "harbour-street", "--regenerate"] + extra) == 2, extra
        assert capsys.readouterr().err == "Error: %s\n" % message, extra
    assert tool.main(["create", "nowhere", "--regenerate"]) == 2
    assert capsys.readouterr().err.startswith("Error: unknown location: nowhere (no ")
    with open(os.path.join(env["locations"], "harbour-street", "location.json"), "rb") as f:
        assert f.read() == before


# --- LT6: edit (L1.12) ------------------------------------------------------------------------

def test_lt6_edit(env, monkeypatch, capsys):
    lib = env["locations"]
    lt.mill(lib, status="untrained", source="photos")
    lt.harbour(lib, status="untrained")
    new = "The " + lt.TEMPLE_DESC[3:] + "."
    assert tool.main(["edit", "old-mill", "--description", new]) == 0
    assert capsys.readouterr().out == "description: the %s\n" % lt.TEMPLE_DESC[3:]
    assert ll.load_location("old-mill")["description"] == "the " + lt.TEMPLE_DESC[3:]
    assert not os.path.exists(os.path.join(env["lib"], ".lock"))
    assert tool.main(["edit", "harbour-street", "--description", lt.TEMPLE_DESC]) == 2
    assert capsys.readouterr().err == (
        "Error: location harbour-street is a text location: its stills are drawn from its "
        "description; run bin/location create harbour-street --regenerate --description TEXT "
        "(add --force when it is trained)\n")
    assert tool.main(["edit", "old-mill", "--description", "a mill"]) == 2
    assert capsys.readouterr().err == "Error: --description: description: must be 15-40 words, got 2\n"
    os.makedirs(env["lib"], exist_ok=True)
    with open(os.path.join(env["lib"], ".lock"), "w") as f:
        f.write(str(os.getppid()))
    assert tool.main(["edit", "old-mill", "--description", lt.MILL_DESC]) == 2
    assert capsys.readouterr().err == (
        "Error: another bin/character create/train is running (pid %d); run one at a time\n"
        % os.getppid())
    assert ll.load_location("old-mill")["description"] == "the " + lt.TEMPLE_DESC[3:]


# --- LT7, LT8: the re-exec and the signal path (L1.2) ----------------------------------------

def test_lt7_missing_pil_re_executes_under_character_python(env, tmp_path):
    shim = tmp_path / "shim" / "PIL"
    shim.mkdir(parents=True)
    (shim / "__init__.py").write_text("raise ImportError('no PIL here')\n")
    log = str(tmp_path / "reexec.json")
    stub = tmp_path / "fake-python"
    stub.write_text("#!%s\nimport json, os, sys\njson.dump({'argv': sys.argv, 'marker': "
                    "os.environ.get('LOCATION_REEXEC')}, open(%r, 'w'))\n" % (sys.executable, log))
    stub.chmod(0o755)
    run_env = dict(os.environ, PYTHONPATH=str(tmp_path / "shim"), CHARACTER_PYTHON=str(stub))
    run_env.pop("LOCATION_REEXEC", None)
    argv = ["create", "old-mill", "--description", lt.MILL_DESC]
    proc = _subprocess(argv, env=run_env)
    assert proc.returncode == 0, proc.stderr
    with open(log) as f:
        record = json.load(f)
    assert record == {"argv": [str(stub), os.path.realpath(TOOL_PATH)] + argv, "marker": "1"}
    os.remove(log)
    proc = _subprocess(argv, env=dict(run_env, LOCATION_REEXEC="1"))
    assert proc.returncode == 1 and "ImportError: no PIL here" in proc.stderr
    assert not os.path.exists(log)
    listed = _subprocess(["list"], env=run_env)
    assert listed.returncode == 0 and not os.path.exists(log)


def test_lt8_sigterm_during_a_create_exits_130(env, tmp_path):
    marker = str(tmp_path / "waiting")
    driver = tmp_path / "driver.py"
    driver.write_text(
        "import importlib.machinery, os, sys, time\n"
        "sys.path.insert(0, %r)\n"
        "import character_dataset\n"
        "def _slow_ready():\n"
        "    open(%r, 'w').close()\n"
        "    time.sleep(60)\n"
        "    os._exit(99)\n"
        "character_dataset.vlm_ready = _slow_ready\n"
        "character_dataset.busy_process = lambda: None\n"
        "character_dataset.free_gib = lambda path: 100.0\n"
        "def _forbidden(name):\n"
        "    def _f(*a, **k):\n"
        "        raise AssertionError('LT8 reached ' + name)\n"
        "    return _f\n"
        "for _n in ('story_server', 'restore_story_server', 'run_zimage_child', 'run_edit_child', 'wait_for_avail', 'wait_for_vlm'):\n"
        "    setattr(character_dataset, _n, _forbidden(_n))\n"
        "tool = importlib.machinery.SourceFileLoader('location_tool', %r).load_module()\n"
        "sys.exit(tool.run(['create', 'old-mill', '--description', %r]))\n"
        % (WS, marker, TOOL_PATH, lt.MILL_DESC))
    proc = subprocess.Popen([sys.executable, "-B", str(driver)], stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, text=True, env=dict(os.environ))
    try:
        deadline = time.monotonic() + 60
        while not os.path.exists(marker):
            assert time.monotonic() < deadline and proc.poll() is None, proc.stderr.read()
            time.sleep(0.05)
        proc.send_signal(signal.SIGTERM)
        _out, err = proc.communicate(timeout=60)
    finally:
        if proc.poll() is None:
            proc.kill()
    assert proc.returncode == 130
    assert err.endswith("location: interrupted\n")
    assert not os.path.exists(os.path.join(env["lib"], ".lock"))
    assert not os.path.exists(os.path.join(env["locations"], "old-mill"))


# --- Review Focus 1, 2 --------------------------------------------------------------------------

def test_review_focus_1_a_new_description_with_the_trigger_is_refused(env, monkeypatch, capsys):
    lib = env["locations"]
    _fakes(monkeypatch)
    lt.mill(lib, status="untrained", source="photos")
    trained = lt.harbour(lib)
    ldir = os.path.join(lib, "harbour-street")
    with open(os.path.join(lib, "old-mill", "location.json"), "rb") as f:
        mill_before = f.read()
    with open(os.path.join(ldir, "location.json"), "rb") as f:
        harbour_before = f.read()
    assert tool.main(["edit", "old-mill", "--description",
                      lt.MILL_DESC.replace("mossy wheel", "oldmiplc wheel")]) == 2
    assert capsys.readouterr().err == (
        "Error: --description: trigger oldmiplc must not be a word of the description\n")
    assert tool.main(["create", "harbour-street", "--regenerate", "--force", "--description",
                      lt.HARBOUR_DESC.replace("granite quays", "harboplc quays")]) == 2
    assert capsys.readouterr().err == (
        "Error: --description: trigger harboplc must not be a word of the description\n")
    with open(os.path.join(lib, "old-mill", "location.json"), "rb") as f:
        assert f.read() == mill_before
    with open(os.path.join(ldir, "location.json"), "rb") as f:
        assert f.read() == harbour_before
    assert os.path.isfile(trained["loras"]["video"]["path"])


def test_review_focus_2_an_accented_place_name_round_trips(env, monkeypatch, capsys):
    _fakes(monkeypatch)
    assert tool.main(["create", "cafe-terrace", "--description", CAFE_DESC]) == 0
    capsys.readouterr()
    data = ll.load_location("cafe-terrace")
    assert (data["description"], data["trigger"], data["status"]) == (
        CAFE_DESC, "cafetplc", "untrained")
    with open(os.path.join(env["locations"], "cafe-terrace", "location.json"), "rb") as f:
        assert "café terrace in Montréal".encode("utf-8") in f.read()
    c_locale = dict(os.environ, LC_ALL="C", LANG="C")
    c_locale.pop("PYTHONIOENCODING", None)
    for argv in (["list"], ["show", "cafe-terrace"]):
        proc = subprocess.run([sys.executable, "-B", TOOL_PATH] + argv, capture_output=True,
                              env=c_locale, timeout=60)
        assert proc.returncode == 0, proc.stderr
        assert CAFE_DESC in proc.stdout.decode("utf-8"), argv


# --- LT9, LT10: bin/location-train-vlm and train's kinds (L2.1, L2.2) -------------------------

def test_lt1b_train_help(env):
    proc = _subprocess(["train", "--help"])
    assert proc.returncode == 0
    for flag in ("--video", "--stills", "--force"):
        assert flag in proc.stdout, flag


def _vlm_wrapper_bin(tmp_path, location_body):
    """A temporary bin/ holding a copy of bin/location-train-vlm and stub story-server,
    story-server-restore and location scripts that log their arguments to calls.log."""
    bindir = tmp_path / "bin"
    bindir.mkdir()
    shutil.copy2(os.path.join(WS, "bin", "location-train-vlm"), str(bindir / "location-train-vlm"))
    log = tmp_path / "calls.log"
    for name, body in (("story-server", 'echo "story-server $*" >> %s\n' % log),
                       ("story-server-restore", 'echo "story-server-restore $*" >> %s\n' % log),
                       ("location", 'echo "location $*" >> %s\n%s' % (log, location_body))):
        path = bindir / name
        path.write_text("#!/bin/sh\n" + body)
        path.chmod(0o755)
    return str(bindir / "location-train-vlm"), log


def test_lt9_location_train_vlm(env, tmp_path):
    with open(os.path.join(WS, "bin", "location-train-vlm"), encoding="utf-8") as f:
        script = f.read().split("\n")
    with open(os.path.join(WS, "bin", "character-train-vlm"), encoding="utf-8") as f:
        character = f.read().split("\n")
    assert script[1].startswith("# location-train-vlm -- run a location training")
    assert script[5:] == [line.replace("character-train-vlm", "location-train-vlm").replace(
        '"$PY" "$DIR/character" train "$@"', '"$PY" "$DIR/location" train "$@"')
        for line in character[5:]]
    assert os.access(os.path.join(WS, "bin", "location-train-vlm"), os.X_OK)
    for rc in (0, 1):
        case = tmp_path / ("rc%d" % rc)
        case.mkdir()
        wrapper, log = _vlm_wrapper_bin(case, "exit %d\n" % rc)
        proc = subprocess.run(["/bin/bash", wrapper, "/bin/sh", "harbour-street", "--video"],
                              capture_output=True, text=True, timeout=60)
        assert proc.returncode == rc, proc.stderr
        assert log.read_text().splitlines() == ["story-server stop",
                                                "location train harbour-street --video",
                                                "story-server-restore mlx-vision --wait"]
        assert "location-train-vlm: training exited %d" % rc in proc.stderr
    case = tmp_path / "signal"
    case.mkdir()
    marker = case / "running"
    wrapper, log = _vlm_wrapper_bin(case, "touch %s\nsleep 30\n" % marker)
    proc = subprocess.Popen(["/bin/bash", wrapper, "/bin/sh", "harbour-street"],
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                            start_new_session=True)
    try:
        deadline = time.monotonic() + 30
        while not marker.exists():
            assert time.monotonic() < deadline
            time.sleep(0.05)
        os.killpg(proc.pid, signal.SIGTERM)
        _out, err = proc.communicate(timeout=30)
    finally:
        if proc.poll() is None:
            os.killpg(proc.pid, signal.SIGKILL)
    assert proc.returncode == 130
    assert "location-train-vlm: interrupted; restarting the VLM in the background" in err
    assert log.read_text().splitlines() == ["story-server stop", "location train harbour-street",
                                            "story-server-restore mlx-vision"]


def test_lt10_train_with_neither_flag_trains_both(env, monkeypatch, tmp_path, capsys):
    lt.harbour(env["locations"], status="untrained")
    ldir = os.path.join(env["locations"], "harbour-street")
    with open(os.path.join(ldir, "manifest.json"), "w") as f:
        json.dump({"items": [{"n": n, "kept": n <= 21} for n in range(1, 25)]}, f)
    dev = tmp_path / "dev-model"
    dev.mkdir()
    (dev / "transformer-dev.safetensors").write_bytes(b"dev")
    stub = tmp_path / "stub-bin"
    stub.write_text("#!/bin/sh\nexit 0\n")
    stub.chmod(0o755)
    monkeypatch.setattr(character_dataset, "busy_process", lambda: None)
    monkeypatch.setattr(character_dataset, "story_server_state", lambda: "STOPPED")
    monkeypatch.setattr(character_dataset.psutil, "virtual_memory",
                        lambda: type("M", (), {"available": 64.0 * 2 ** 30})())
    monkeypatch.setattr(character_dataset, "TRAIN_MODEL_DIR", str(dev))
    monkeypatch.setattr(character_dataset, "TEST_MODEL_DIR", str(tmp_path))
    monkeypatch.setattr(character_dataset.SKILL, "LTX2_MLX_BIN", str(stub))
    monkeypatch.setattr(character_dataset, "MFLUX_TRAIN", str(stub))
    calls = []

    def _video_core(owner_dir, videos, captions, prompt, note, recorded, tested):
        calls.append("video")
        if len(calls) == 1:
            return "failed"
        path = os.path.join(owner_dir, "lora", "video.safetensors")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            f.write(b"lora")
        recorded({"path": path, "sha256": "0" * 64, "rank": 32, "alpha": 32, "steps": 1000})
        return "test_failed"

    monkeypatch.setattr(character_dataset, "train_video_lora", _video_core)
    monkeypatch.setattr(character_dataset, "train_stills_lora",
                        lambda *args: calls.append("stills") or "ok")
    monkeypatch.setattr(character_dataset, "free_gib", lambda path: 15.9)
    assert tool.main(["train", "harbour-street"]) == 2
    assert capsys.readouterr().err == (
        "Error: only 15.9 GiB free at %s; training video and stills needs 16 GiB\n" % ldir)
    assert tool.main(["train", "harbour-street", "--video"]) == 1
    assert calls == ["video"]
    monkeypatch.setattr(character_dataset, "free_gib", lambda path: 16.0)
    assert tool.main(["train", "harbour-street"]) == 1
    assert calls == ["video", "video", "stills"]
    assert ll.load_location("harbour-street")["status"] == "trained"
