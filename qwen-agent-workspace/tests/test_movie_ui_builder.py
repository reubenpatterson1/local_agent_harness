"""movie-ui command builder and version-aware form tests (movie-ui spec MUT1, MUT3, MUT25, MUT26).
Run from the workspace root: python3 -m pytest tests/test_movie_ui_builder.py -v"""

import os
import re
import subprocess
import sys
import time

import pytest

import movie_ui_testutil as mt
import movie_ui_lib as lib

PY = "/py"
WS = "/w"
STATE = "/s"
LTX = "/w/bin/ltx-movie"


def _f(**overrides):
    fields = lib.compose_fields({"story_id": "ronin", "narrative": "  A ronin walks.  "})
    fields.update(overrides)
    return fields


def _lora(kind, path, strength=0.8, lora_id=None):
    return {"id": lora_id, "path": path, "strength": strength, "kind": kind}


def test_mut1_golden_argv():
    base = [PY, LTX, "A ronin walks.", "--story-id", "ronin"]
    defaults = ["--fps", "24", "--frames", "145", "--model", lib.DEFAULT_MODEL, "--gemma", lib.DEFAULT_GEMMA]
    cases = [
        (_f(), base + ["--panels", "15"] + defaults + ["--story-only", "--no-review"]),
        (_f(action="regenerate"), base + ["--panels", "15"] + defaults + ["--force-story", "--story-only", "--no-review"]),
        (_f(action="movie", panels=6), base + ["--panels", "6"] + defaults + ["--no-review"]),
        (_f(action="movie", panels=None, length=30), base + ["--length", "30.0"] + defaults + ["--no-review"]),
        (_f(action="movie", seed_upload="ab.png", width=None),
         base + ["--panels", "15", "--fps", "24", "--frames", "145", "--seed-image", "/s/uploads/ab.png",
                 "--model", lib.DEFAULT_MODEL, "--gemma", lib.DEFAULT_GEMMA, "--no-review"]),
        (_f(action="movie", width=768, height=512),
         base + ["--panels", "15", "--fps", "24", "--frames", "145", "--video-width", "768", "--video-height", "512",
                 "--model", lib.DEFAULT_MODEL, "--gemma", lib.DEFAULT_GEMMA, "--no-review"]),
        (_f(action="redo", mode="shots", redo=[7, 3, 3]),
         base + ["--panels", "15"] + defaults + ["--shots", "--redo", "3,7", "--no-review"]),
        (_f(action="movie", mode="no_stills"), base + ["--panels", "15"] + defaults + ["--no-stills", "--no-review"]),
        (_f(action="movie", video_loras=[_lora("style", "/l/style.safetensors", 1.0, "ink"),
                                         _lora("motion", "/l/pan.safetensors", 0.75, "pan"),
                                         _lora(None, "/l/free.safetensors", 0.5),
                                         _lora("physics", "/l/water.safetensors", 1.5, "water")]),
         base + ["--panels", "15"] + defaults + ["--lora", "/l/pan.safetensors:0.75", "--lora", "/l/water.safetensors:1.5",
                                                 "--lora", "/l/style.safetensors:1.0", "--lora", "/l/free.safetensors:0.5",
                                                 "--no-review"]),
        (_f(action="movie", stills_loras=[_lora(None, "/l/s.safetensors", 2), _lora("style", "/l/t.safetensors", 1, "t"),
                                         _lora("physics", "/l/p.safetensors", 0.5, "p")]),
         base + ["--panels", "15"] + defaults + ["--stills-lora", "/l/p.safetensors:0.5",
                                                 "--stills-lora", "/l/s.safetensors:2.0",
                                                 "--stills-lora", "/l/t.safetensors:1.0", "--no-review"]),
        (_f(action="movie", characters=["kyra", "ronin"]),
         base + ["--panels", "15"] + defaults + ["--character", "kyra", "--character", "ronin", "--no-review"]),
        (_f(action="movie", model=None, gemma=None, story_model="qwen38", goal=" Make it tense. ", auto_lora=False,
            judge=True, no_low_ram=True, panel_timeout=900, overwrite_movie=True),
         base + ["--panels", "15", "--fps", "24", "--frames", "145", "--story-model", "qwen38",
                 "--goal", "Make it tense", "--no-auto-lora", "--judge", "--no-low-ram", "--panel-timeout", "900",
                 "--force", "--no-review"]),
        (_f(story_legacy=True), base + ["--panels", "15"] + defaults + ["--story-legacy", "--story-only", "--no-review"]),
        (_f(action="movie", narration="speech"), base + ["--panels", "15"] + defaults + ["--speech-only", "--no-review"]),
        (_f(action="movie", narration="none"), base + ["--panels", "15"] + defaults + ["--no-narration", "--no-review"]),
        (_f(action="movie", narration="full"), base + ["--panels", "15"] + defaults + ["--no-review"]),
    ]
    for fields, expected in cases:
        assert lib.build_argv(fields, WS, STATE, py=PY) == expected
        assert lib.build_argv(fields, WS, STATE, py=PY)[-1] == "--no-review"


def test_mut1_character_argv():
    c = [PY, "/w/bin/character"]
    create = {"name": "kyra", "phrase": "the young woman", "seed_upload": "ab.jpg", "descriptor": None,
              "class_noun": None, "trigger": None, "seed": None, "force": False}
    assert lib.character_argv("character-create", create, WS, STATE, py=PY) == c + [
        "create", "kyra", "--phrase", "the young woman", "--seed-image", "/s/uploads/ab.jpg"]
    create.update(seed_upload=None, descriptor="a tall woman", class_noun="woman", trigger="kyrax", seed=0, force=True)
    assert lib.character_argv("character-create", create, WS, STATE, py=PY) == c + [
        "create", "kyra", "--phrase", "the young woman", "--descriptor", "a tall woman", "--class", "woman",
        "--trigger", "kyrax", "--seed", "0", "--force"]
    assert lib.character_argv("character-regenerate", {"name": "kyra"}, WS, STATE, py=PY) == c + [
        "create", "kyra", "--regenerate"]
    # character-train routes through the VLM-managing wrapper: [wrapper, py, name, flags].
    tw = ["/w/bin/character-train-vlm", PY]
    assert lib.character_argv("character-train", {"name": "kyra", "video": True, "stills": False, "force": False},
                              WS, STATE, py=PY) == tw + ["kyra", "--video"]
    assert lib.character_argv("character-train", {"name": "kyra", "video": True, "stills": True, "force": True},
                              WS, STATE, py=PY) == tw + ["kyra", "--video", "--stills", "--force"]


def test_mu36_compose_fields_defaults_and_unknown_keys():
    fields = lib.compose_fields({"story_id": "x", "bogus": 1, "video_loras": [{"id": None}]})
    assert set(fields) == set(lib.DEFAULT_FIELDS)
    assert fields["story_id"] == "x" and fields["panels"] == 15 and fields["mode"] == "chained"
    assert fields["model"] == lib.DEFAULT_MODEL and fields["redo"] == [] and fields["narration"] == "full"
    # Jobs saved with the earlier boolean narration field still load.
    assert lib.compose_fields({"narration": False})["narration"] == "none"
    assert lib.compose_fields({"narration": True})["narration"] == "full"
    assert lib.ordered([_lora(None, "/a"), _lora("motion", "/b")]) == [_lora("motion", "/b"), _lora(None, "/a")]


ALL_MU37_FLAGS = {"--story-id", "--panels", "--length", "--fps", "--frames", "--video-width", "--video-height",
                  "--seed-image", "--model", "--gemma", "--story-model", "--goal", "--shots", "--no-stills",
                  "--lora", "--stills-lora", "--character", "--no-auto-lora", "--no-narration", "--speech-only", "--story-legacy", "--judge",
                  "--no-low-ram", "--panel-timeout", "--force", "--force-story", "--redo", "--story-only",
                  "--no-review"}


def test_mut3_help_flags_fixtures_real_help_and_cache(tmp_path, monkeypatch):
    mt.set_home(monkeypatch, tmp_path)
    with open(os.path.join(mt.FIXTURES, "ltx-movie-help-current.txt"), encoding="utf-8") as f:
        current = lib.parse_help_flags(f.read())
    with open(os.path.join(mt.FIXTURES, "ltx-movie-help-old.txt"), encoding="utf-8") as f:
        old = lib.parse_help_flags(f.read())
    assert ALL_MU37_FLAGS <= current
    assert {"--story-server-stop-after-story", "--no-story-server-stop-after-story", "--help"} <= current
    assert current - old == {"--story-only", "--story-legacy", "--no-auto-lora", "--judge", "--goal", "--gemma",
                             "--no-narration", "--speech-only"}
    real, error = lib.help_flags(mt.WS)
    assert error is None and ALL_MU37_FLAGS <= real
    supported = lib.supported_map(old)
    assert supported["judge"] is False and supported["story_only"] is False and supported["panels"] is True
    assert set(supported) == {k for k, _flags in lib.FIELD_FLAGS} and len(supported) == 27
    assert lib.supported_map(None)["panels"] is False
    ws = mt.make_stub_workspace(tmp_path)
    flags, error = lib.help_flags(ws)
    assert error is None and flags == frozenset(current)
    mt.stub_config(ws, {"ltx-movie --help": {"stdout": "  --panels N   x\n"}})
    assert lib.help_flags(ws)[0] == frozenset(current)
    os.utime(os.path.join(ws, "bin", "ltx-movie"), ns=(10 ** 9, 10 ** 9))
    assert lib.help_flags(ws)[0] == frozenset({"--panels"})
    mt.stub_config(ws, {"ltx-movie --help": {"exit": 2, "stderr": "Traceback\nImportError: no torch\n"}})
    os.utime(os.path.join(ws, "bin", "ltx-movie"), ns=(2 * 10 ** 9, 2 * 10 ** 9))
    assert lib.help_flags(ws) == (None, "cannot read bin/ltx-movie --help (exit 2): ImportError: no torch")
    assert [c["sub"] for c in mt.stub_calls(ws)] == ["--help", "--help", "--help"]


def test_run_light_timeout_kills_grandchild(tmp_path):
    pid_file = str(tmp_path / "grand.pid")
    code = ("import subprocess, time\n"
            "p = subprocess.Popen(['sleep', '30'])\n"
            "open(%r, 'w').write(str(p.pid))\n"
            "time.sleep(30)\n" % pid_file)
    grand = None
    try:
        result = lib.run_light([sys.executable, "-c", code], str(tmp_path), timeout=1)
        assert result["timed_out"] is True
        with open(pid_file) as f:
            grand = int(f.read())
        deadline = time.time() + 3
        gone = False
        while time.time() < deadline:
            try:
                os.kill(grand, 0)
            except ProcessLookupError:
                gone = True
                break
            time.sleep(0.05)
        assert gone
    finally:
        if grand:
            try:
                os.kill(grand, 9)
            except OSError:
                pass


def test_run_light_nul_argv_returns_value_error_result(tmp_path):
    result = lib.run_light(["true", "a\x00b"], str(tmp_path))
    assert result["exit_code"] is None and result["stderr"].startswith("ValueError")


def test_mut1_smoke_manifest_and_argv(monkeypatch, tmp_path):
    state = mt.set_home(monkeypatch, tmp_path)
    job_id = "20261019-142233-a1b2"
    path = lib.write_smoke_manifest(state, job_id)
    sdir = os.path.join(state, "smoke", job_id)
    assert path == os.path.join(sdir, "manifest.json") and os.stat(sdir).st_mode & 0o777 == 0o700
    assert lib.read_json(path) == {"schema_version": 3, "story_id": "movie-ui-smoke", "panels": [
        {"index": 1, "conditioning": "t2v", "image_path": None,
         "panel_text": "A slow camera pan across a quiet forest clearing at golden hour, leaves moving gently in the wind."}]}
    fields = _f(action="smoke", model=None, no_low_ram=True, stills_loras=[{"id": "x"}],
                video_loras=[_lora(None, "/l/free.safetensors", 0.5), _lora("motion", "/l/pan.safetensors", 1, "pan")])
    assert lib.build_smoke_argv(fields, WS, state, job_id, py=PY) == [
        PY, "/w/bin/ltx-mlx-render", path, os.path.join(sdir, "smoke.mp4"), "--frames", "9", "--width", "512",
        "--height", "320", "--frame-rate", "24", "--clips-dir", os.path.join(sdir, "clips"),
        "--model", lib.DEFAULT_MODEL, "--gemma", lib.DEFAULT_GEMMA, "--lora", "/l/pan.safetensors:1.0",
        "--lora", "/l/free.safetensors:0.5", "--no-low-ram", "--panel-timeout", "1800"]


NEW_PY = ("movie_ui_lib.py", "movie_ui_server.py", "bin/movie-ui", "bin/movie-ui-job", "tests/movie_ui_testutil.py",
          "tests/test_movie_ui_builder.py", "tests/test_movie_ui_checks.py", "tests/test_movie_ui_jobs.py",
          "tests/test_movie_ui_progress.py", "tests/test_movie_ui_http.py", "tests/test_movie_ui_traces.py")
CHANGED_PY = ("fleet_lib.py", "bin/qwen-agentd", "tests/test_fleet_lib.py", "tests/test_fleet_self_update.py")
PIPELINE_FILES = ("bin/ltx-movie", "bin/ltx-mlx-render", "bin/ltx-story-images", "bin/ltx-story-manifest",
                  "bin/ltx-story-video", "bin/ltx-chain", "bin/ltx-generate", "bin/ltx-host-prep",
                  "bin/ltx-host-restore", "bin/character", "bin/lora-catalog", "bin/judge-story", "bin/judge-clips",
                  "bin/judge-stills", "bin/iterate-story", "bin/qwen-agent", "story_engine.py", "character_lib.py",
                  "character_dataset.py", "lora_catalog.py", "pipeline_log.py", "z_image_skill.py",
                  "ltx2_mlx_video_skill.py")


@pytest.mark.parametrize("python", ["/usr/bin/python3", sys.executable])
def test_mut25_every_new_and_changed_file_compiles(python, tmp_path):
    if not os.path.isfile(python):
        pytest.skip("%s is not installed" % python)
    paths = [os.path.join(mt.WS, rel) for rel in NEW_PY + CHANGED_PY]
    proc = subprocess.run([python, "-m", "py_compile"] + paths, capture_output=True, text=True, timeout=120,
                          env=dict(os.environ, PYTHONPYCACHEPREFIX=str(tmp_path)))
    assert proc.returncode == 0, proc.stderr


def test_mut25_source_scan_of_new_python_files():
    forbidden = [(re.compile(r"^\s*(import|from)\s+cgi\b", re.M), "cgi"),
                 (re.compile(r"\burllib\b"), "urllib"),
                 (re.compile(r"shell\s*=\s*True"), "shell=True"),
                 (re.compile(r"^\s*match\s+\S.*:\s*$", re.M), "match statement"),
                 (re.compile(r"->[^:\n]*\|"), "X | Y return annotation"),
                 (re.compile(r":\s*[A-Za-z_][\w.\[\], ]*\|\s*None"), "X | None annotation"),
                 (re.compile(r"strict\s*=\s*True\s*\)"), "zip(strict=)"),
                 (re.compile(r"load_module\("), "load_module")]
    for rel in NEW_PY:
        with open(os.path.join(mt.WS, rel), encoding="utf-8") as f:
            source = f.read()
        if rel == "tests/test_movie_ui_builder.py":
            start = source.index("    forbidden = [")
            end = source.index("    for rel in NEW_PY:", start)
            source = source[:start] + source[end:]
        for regex, what in forbidden:
            assert not regex.search(source), (rel, what)
    for rel in NEW_PY[:2]:
        with open(os.path.join(mt.WS, rel), encoding="utf-8") as f:
            source = f.read()
        imported = set(re.findall(r"^(?:import|from)\s+([A-Za-z_][\w.]*)", source, re.M))
        allowed = {"argparse", "calendar", "errno", "fcntl", "hashlib", "hmac", "http.server", "json", "os",
                   "platform", "re", "secrets", "shlex", "shutil", "signal", "socket", "struct", "subprocess",
                   "sys", "threading", "time", "fleet_lib", "movie_ui_lib"}
        assert imported <= allowed, (rel, imported - allowed)
        for loader in ("importlib", "SourceFileLoader", "runpy", "exec(", "__import__"):
            assert loader not in source, (rel, loader)


def test_mut26_pipeline_files_are_unchanged():
    # MUK3: the movie-ui must not modify any pipeline file. Baseline re-based from
    # 22dc4a1 (pre-movie-ui) to fb8b9a5 when the action-LoRA / pipeline PR
    # intentionally advanced the pipeline, then to 6bcb54b (character_dataset.py's
    # TEST_MODEL_DIR host-adapted ltx-2.5 -> ltx-2.3), then to 9f71234 (character_dataset.py's
    # VLM restart switched from the vLLM "vision" mode to "mlx-vision", the mlx_vlm path
    # this host serves), then to 8921fa9 (character_dataset.py's DESCRIBE_PROMPT
    # strengthened to capture makeup and habitual bearing). The movie-ui itself still
    # makes zero pipeline changes), then to c35b6bc (apparent age pinned in DESCRIBE_PROMPT
    # and scored in CHECK_PROMPT, fixing age drift), then to 3b6b317 (descriptor word cap
    # 60->70 for the richer prompt), then to d7e9036 (character_lib.py's matching descriptor
    # word cap 60->70), then to 69460eb (bin/qwen-agent's --model default resolves to the
    # served model), then to d3796bf (bin/qwen-agent's 120000 fallback context window and
    # --danger-auto-approve reaching any path). This invariant holds from the new baseline.
    BASELINE = "f7c25173361c6c9345f6f18d1432744a9f2dc580"
    root = subprocess.run(["git", "-C", mt.WS, "rev-parse", "--show-toplevel"], capture_output=True, text=True)
    if root.returncode != 0:
        pytest.skip("not a git checkout")
    if subprocess.run(["git", "-C", mt.WS, "cat-file", "-e", BASELINE + "^{commit}"],
                      capture_output=True).returncode:
        pytest.skip("baseline commit %s is not in this checkout" % BASELINE)
    proc = subprocess.run(["git", "-C", mt.WS, "diff", "--quiet", BASELINE, "--"] + list(PIPELINE_FILES),
                          capture_output=True, text=True)
    assert proc.returncode == 0, proc.stdout + proc.stderr
