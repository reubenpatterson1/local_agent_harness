"""Tests for casting through the movie pipeline (spec docs/superpowers/specs/
2026-10-05-character-library-design.md Section 9.5, P1-P49).

Run from the workspace root: python3 -m pytest tests/test_casting_pipeline.py
Plain pytest asserts only (no check() helper). No GPU, no model, no network: the render
harness stubs SKILL.generate_video (a fresh copy of the tests/test_ltx_mlx_render.py
_Harness pattern, not an import), Z-Image runs against fake torch/z_image_skill/
content_safety modules, and every character library lives under tmp_path through
$CHARACTER_LIBRARY_DIR.
"""

import contextlib
import glob
import hashlib
import importlib.machinery
import io
import json
import os
import subprocess
import sys
import types

import pytest

WS = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
sys.path.insert(0, WS)

import character_lib  # noqa: E402
import ltx2_mlx_video_skill as SKILL  # noqa: E402


def _load(name, rel):
    return importlib.machinery.SourceFileLoader(name, os.path.join(WS, rel)).load_module()


render = _load("ltx_mlx_render_casting", "bin/ltx-mlx-render")
story_manifest = _load("ltx_story_manifest_casting", "bin/ltx-story-manifest")
story_images = _load("ltx_story_images_casting", "bin/ltx-story-images")
ltx_movie = _load("ltx_movie_casting", "bin/ltx-movie")

# --- shared fixtures (spec 9.1) --------------------------------------------------------
DESCRIPTOR = "a young woman with long black hair pinned up with jade hairpins wearing a grey kimono"
VIDEO_BYTES = b"fake-video-lora!"
STILLS_BYTES = b"fake-stills-lora"


@pytest.fixture
def lib_dir(tmp_path, monkeypatch):
    lib = tmp_path / "lib"
    monkeypatch.setenv("CHARACTER_LIBRARY_DIR", str(lib))
    return str(lib)


def make_character(lib, name="kyra", trigger="kyrawmn", phrase="the woman in grey",
                   class_noun="woman", status="trained", stills=False, strength=None):
    """Write a valid character.json (spec 2.2 shape) under lib/name and return the dict. A
    trained character also gets a 16-byte lora/video.safetensors, plus a 16-byte
    lora/stills.safetensors when stills is true; each entry carries the real sha256."""
    cdir = os.path.join(lib, name)
    os.makedirs(os.path.join(cdir, "lora"), exist_ok=True)
    dataset = None
    if status in ("untrained", "trained"):
        dataset = {"reference": "char_00", "kept": 24, "total": 25, "min_score": 7,
                   "face_height": 0.38,
                   "contact_sheet": os.path.join(cdir, "dataset", "contact_sheet.jpg")}
    video = stills_entry = None
    if status == "trained":
        video_path = os.path.join(cdir, "lora", "video.safetensors")
        with open(video_path, "wb") as f:
            f.write(VIDEO_BYTES)
        video = {"path": video_path, "sha256": hashlib.sha256(VIDEO_BYTES).hexdigest(),
                 "base_model": "/models/ltx-2.3-mlx-q8-dev", "rank": 32, "alpha": 32,
                 "steps": 1000, "trained_at": "2026-10-06T02:00:00Z",
                 "sample_path": None, "control_path": None}
        if stills:
            stills_path = os.path.join(cdir, "lora", "stills.safetensors")
            with open(stills_path, "wb") as f:
                f.write(STILLS_BYTES)
            stills_entry = {"path": stills_path,
                            "sha256": hashlib.sha256(STILLS_BYTES).hexdigest(),
                            "base_model": "Tongyi-MAI/Z-Image-Turbo", "rank": 16, "alpha": 16,
                            "steps": 2400, "trained_at": "2026-10-06T03:00:00Z",
                            "sample_path": None, "control_path": None}
    data = {"schema_version": 1, "name": name, "trigger": trigger, "class_noun": class_noun,
            "referring_phrase": phrase, "descriptor": DESCRIPTOR, "seed": 0,
            "source": {"type": "seed_image", "path": "/fixtures/seed.png"},
            "strength": strength, "status": status, "created_at": "2026-10-06T01:02:03Z",
            "dataset": dataset, "loras": {"video": video, "stills": stills_entry},
            "stills_skip_reason": None}
    with open(os.path.join(cdir, "character.json"), "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    return data


def _ronin(lib, **kw):
    return make_character(lib, name="ronin", trigger="roninmn", phrase="the ronin",
                          class_noun="man", **kw)


# --- P1-P5: ltx2_mlx_video_skill multi-LoRA argv and validation (spec 5.1) -------------
def _argv(**extra):
    return SKILL.build_command(prompt="p", output_path="/o.mp4", image_path="/i.png",
                               width=704, height=448, num_frames=145, frame_rate=24, seed=1,
                               model="M", gemma="G", **extra)


def test_p1_loras_follow_the_gemma_value(monkeypatch):
    monkeypatch.setattr(SKILL, "LTX2_MLX_BIN", "/bin/ltx")
    plain = _argv()
    cast = _argv(loras=[("/a.safetensors", 1.0), ("/b.safetensors", 0.8)])
    at = plain.index("--gemma") + 2
    assert cast == plain[:at] + ["--lora", "/a.safetensors", "1.0",
                                 "--lora", "/b.safetensors", "0.8"] + plain[at:]


def test_p2_empty_or_none_loras_change_nothing(monkeypatch):
    monkeypatch.setattr(SKILL, "LTX2_MLX_BIN", "/bin/ltx")
    assert _argv(loras=[]) == _argv()
    assert _argv(loras=None) == _argv()


def test_p3_lora_path_and_loras_are_exclusive():
    with pytest.raises(ValueError) as info:
        _argv(lora_path="/x", loras=[("/a", 1.0)])
    assert str(info.value) == "lora_path and loras are mutually exclusive"


def test_p4_generate_video_rejects_bad_loras(tmp_path, monkeypatch):
    def _never(*args, **kwargs):
        raise AssertionError("subprocess.Popen ran")
    monkeypatch.setattr(SKILL.subprocess, "Popen", _never)
    good = str(tmp_path / "a.safetensors")
    with open(good, "wb") as f:
        f.write(b"x")
    missing = str(tmp_path / "missing.safetensors")
    out = str(tmp_path / "o.mp4")
    cases = [
        ({"loras": {good: 1.0}},
         "loras must be a list of (path, strength) pairs, got %r" % ({good: 1.0},)),
        ({"loras": [(good, 1.0, 2)]},
         "loras[0] must be a (path, strength) pair, got %r" % ((good, 1.0, 2),)),
        ({"loras": [(missing, 1.0)]}, "loras[0]: path is not a readable file: %r" % missing),
        ({"loras": [(good, 0)]}, "loras[0]: strength must be a number in (0, 2], got 0"),
        ({"loras": [(good, 2.5)]}, "loras[0]: strength must be a number in (0, 2], got 2.5"),
        ({"loras": [(good, True)]}, "loras[0]: strength must be a number in (0, 2], got True"),
        ({"loras": [(good, "1")]}, "loras[0]: strength must be a number in (0, 2], got '1'"),
        ({"loras": [(good, 1.0)], "lora_path": good}, "lora_path and loras are mutually exclusive"),
    ]
    for kwargs, message in cases:
        with pytest.raises(ValueError) as info:
            SKILL.generate_video("p", out, width=704, height=448, num_frames=145,
                                 frame_rate=24, **kwargs)
        assert str(info.value) == message


def test_p5_child_argv_carries_the_lora_once(tmp_path, monkeypatch):
    stub = tmp_path / "ltx-stub"
    stub.write_text("#!%s\n"
                    "import json, os, sys\n"
                    "argv = sys.argv[1:]\n"
                    "with open(os.environ['CASTING_STUB_ARGV'], 'w') as f:\n"
                    "    json.dump(argv, f)\n"
                    "with open(argv[argv.index('--output') + 1], 'wb') as f:\n"
                    "    f.write(b'mp4')\n" % sys.executable)
    stub.chmod(0o755)
    argv_file = tmp_path / "argv.json"
    monkeypatch.setenv("CASTING_STUB_ARGV", str(argv_file))
    monkeypatch.setattr(SKILL, "LTX2_MLX_BIN", str(stub))
    monkeypatch.setattr(SKILL, "LTX2_MLX_DIR", str(tmp_path))
    lora = str(tmp_path / "k.safetensors")
    with open(lora, "wb") as f:
        f.write(b"lora")
    SKILL.generate_video("p", str(tmp_path / "o.mp4"), width=704, height=448, num_frames=145,
                         frame_rate=24, loras=[(lora, 0.6)], force=True)
    argv = json.loads(argv_file.read_text())
    windows = [argv[i:i + 3] for i in range(len(argv) - 2)]
    assert windows.count(["--lora", lora, "0.6"]) == 1
    assert argv.count("--lora") == 1


def test_p60_parse_lora_spec_table():
    parse = SKILL.parse_lora_spec
    assert parse("a.safetensors") == ("a.safetensors", 1.0, False)
    assert parse("a.safetensors:0.5") == ("a.safetensors", 0.5, True)
    assert parse("/p/a:b.safetensors:0.8") == ("/p/a:b.safetensors", 0.8, True)
    assert parse("org/repo:main") == ("org/repo:main", 1.0, False)
    assert parse(":0.5") == (":0.5", 1.0, False)
    assert parse("a.safetensors:2") == ("a.safetensors", 2.0, True)
    for bad in ("a.safetensors:0", "a.safetensors:2.5", "a.safetensors:-1", "a.safetensors:nan",
                "a.safetensors:inf", ""):
        with pytest.raises(ValueError):
            parse(bad)


def test_p74_strength_two_is_the_upper_bound(tmp_path, monkeypatch):
    stub = tmp_path / "ltx-stub"
    stub.write_text("#!%s\n"
                    "import json, os, sys\n"
                    "argv = sys.argv[1:]\n"
                    "with open(os.environ['CASTING_STUB_ARGV'], 'w') as f:\n"
                    "    json.dump(argv, f)\n"
                    "with open(argv[argv.index('--output') + 1], 'wb') as f:\n"
                    "    f.write(b'mp4')\n" % sys.executable)
    stub.chmod(0o755)
    argv_file = tmp_path / "argv.json"
    monkeypatch.setenv("CASTING_STUB_ARGV", str(argv_file))
    monkeypatch.setattr(SKILL, "LTX2_MLX_BIN", str(stub))
    monkeypatch.setattr(SKILL, "LTX2_MLX_DIR", str(tmp_path))
    g, k = str(tmp_path / "g.safetensors"), str(tmp_path / "k.safetensors")
    for path in (g, k):
        with open(path, "wb") as f:
            f.write(b"lora")
    SKILL.generate_video("p", str(tmp_path / "o.mp4"), width=704, height=448, num_frames=145,
                         frame_rate=24, loras=[(g, 2.0), (k, 1.0)], force=True)
    argv = json.loads(argv_file.read_text())
    at = argv.index("--lora")
    assert argv[at:at + 6] == ["--lora", g, "2.0", "--lora", k, "1.0"]
    with pytest.raises(ValueError):
        SKILL.generate_video("p", str(tmp_path / "o2.mp4"), width=704, height=448,
                             num_frames=145, frame_rate=24, loras=[(g, 2.0001)], force=True)


# --- P6-P17: bin/ltx-mlx-render per-unit LoRAs, provenance, reuse (spec 5.3) -----------
R4L_KEYS = {"index", "label", "seed", "prompt", "image_path", "clip_path", "log_path",
            "conditioning", "chain_source"}


def _lora(tmp_path, name, content=None):
    path = os.path.join(str(tmp_path), "%s.safetensors" % name)
    with open(path, "wb") as f:
        f.write(content if content is not None else ("lora-%s" % name).encode())
    return path


def _entry(name, path, strength):
    phrase = {"kyra": "the woman in grey", "ronin": "the ronin"}[name]
    trigger = {"kyra": "kyrawmn", "ronin": "roninmn"}[name]
    return {"name": name, "phrase": phrase, "trigger": trigger, "video_lora": path,
            "strength": strength}


def _chain_panels(k, r):
    """The P9 manifest: panel 1 t2v [kyra@1.0], panel 2 chain [kyra@0.8, ronin@0.8],
    panel 3 chain with no characters."""
    return [
        {"index": 1, "image_path": None, "panel_text": "m1", "motion_prompt": "m1",
         "conditioning": "t2v", "characters": [_entry("kyra", k, 1.0)]},
        {"index": 2, "image_path": None, "panel_text": "m2", "motion_prompt": "m2",
         "conditioning": "chain",
         "characters": [_entry("kyra", k, 0.8), _entry("ronin", r, 0.8)]},
        {"index": 3, "image_path": None, "panel_text": "m3", "motion_prompt": "m3",
         "conditioning": "chain"},
    ]


def _write_manifest(directory, panels, story_id="cast-render"):
    path = os.path.join(str(directory), "manifest.json")
    with open(path, "w") as f:
        json.dump({"schema_version": 3, "story_id": story_id, "fps": 24, "panels": panels}, f)
    return path


def _render_args(model, **over):
    args = render.build_parser().parse_args(["/tmp/m.json", "/tmp/o.mp4"])
    args.model = model
    for key, value in over.items():
        setattr(args, key, value)
    return args


def _model_fixture(directory):
    model = os.path.join(str(directory), "model-fixture")
    os.makedirs(model, exist_ok=True)
    with open(os.path.join(model, "split_model.json"), "w") as f:
        json.dump({"recipe": "ltx-2.5"}, f)
    return model


class _CastHarness(object):
    """main() in-process with generate_video, probe_streams, assert_clips_uniform,
    build_concat_command, clip_frame_count and prepare_chain_seed stubbed and the story
    dir under tmp_path. Every stub render writes 128 bytes unique to that call, as a real
    render would, so a re-rendered clip changes the chain source of the next panel."""

    def __init__(self, monkeypatch, directory, panels, story_id="cast-render"):
        self.dir = str(directory)
        os.makedirs(self.dir, exist_ok=True)
        self.story_id = story_id
        self.received = []
        self.renders = [0]
        self.manifest = _write_manifest(self.dir, panels, story_id)
        self.model = _model_fixture(self.dir)
        self.clips = os.path.join(self.dir, "clips")
        os.makedirs(self.clips, exist_ok=True)
        self.out = os.path.join(self.dir, "movie.mp4")
        fake_bin = os.path.join(self.dir, "fake-ltx")
        with open(fake_bin, "w") as f:
            f.write("#!/bin/sh\nexit 0\n")
        os.chmod(fake_bin, 0o755)
        harness = self

        def _gen(prompt, output_path, image_path=None, **kw):
            harness.renders[0] += 1
            index = int(os.path.basename(output_path)[len("panel_"):-len(".mp4")])
            harness.received.append((index, kw))
            with open(output_path, "wb") as f:
                f.write(("render %d" % harness.renders[0]).encode().ljust(128, b"\0"))
            return os.path.abspath(output_path)

        def _seed(unit, args):
            with open(unit["image_path"], "wb") as f:
                f.write(b"seed")
            return []

        monkeypatch.setattr(render.SKILL, "generate_video", _gen)
        monkeypatch.setattr(render.SKILL, "LTX2_MLX_BIN", fake_bin)
        monkeypatch.setattr(render, "probe_streams", lambda p: {"streams": []})
        monkeypatch.setattr(render, "assert_clips_uniform", lambda pairs, w, h, fr: None)
        monkeypatch.setattr(render, "build_concat_command", lambda lp, out: [
            sys.executable, "-c", "import sys; open(sys.argv[1],'wb').write(b'MOVIE')", out])
        monkeypatch.setattr(render, "clip_frame_count", lambda p: 241)
        monkeypatch.setattr(render, "prepare_chain_seed", _seed)
        monkeypatch.setattr(render, "story_dir_for",
                            lambda sid: os.path.join(harness.dir, "stories", sid))

    def run(self, *extra):
        return render.main([self.manifest, self.out, "--clips-dir", self.clips,
                            "--skip-input-screen", "--model", self.model] + list(extra))

    def rendered(self):
        return [index for index, _ in self.received]

    def kwargs(self, index):
        return [kw for i, kw in self.received if i == index][-1]

    def newest_summary(self):
        paths = glob.glob(os.path.join(self.dir, "stories", self.story_id, "runs", "*",
                                       "story_summary.json"))
        with open(max(paths, key=os.path.getmtime)) as f:
            return json.load(f)

    def rewrite(self, panels):
        _write_manifest(self.dir, panels, self.story_id)


def test_p6_valid_characters_become_unit_loras(tmp_path):
    k, r = _lora(tmp_path, "kyra"), _lora(tmp_path, "ronin")
    manifest = render.load_manifest(_write_manifest(tmp_path, _chain_panels(k, r)))
    units = render.build_units(manifest["panels"], 0, str(tmp_path / "clips"))
    assert units[1]["loras"] == [{"kind": "character", "name": "kyra", "path": k, "strength": 0.8},
                                 {"kind": "character", "name": "ronin", "path": r, "strength": 0.8}]
    assert units[0]["loras"] == [{"kind": "character", "name": "kyra", "path": k, "strength": 1.0}]


def test_p7_malformed_characters_are_refused(tmp_path):
    k, r = _lora(tmp_path, "kyra"), _lora(tmp_path, "ronin")
    missing = os.path.join(str(tmp_path), "missing.safetensors")
    cases = [
        ({}, "panel 2: characters must be a list"),
        ([{"video_lora": k, "strength": 0.8}],
         "panel 2: every characters entry needs a non-empty name"),
        ([_entry("kyra", k, 0.8), _entry("kyra", k, 0.8)],
         "panel 2: character kyra is listed more than once"),
        ([_entry("kyra", "kyra.safetensors", 0.8)],
         "panel 2: character kyra's video_lora is not a readable file: 'kyra.safetensors'"),
        ([_entry("kyra", missing, 0.8)],
         "panel 2: character kyra's video_lora is not a readable file: %r" % missing),
        ([_entry("kyra", k, 0)],
         "panel 2: character kyra's strength must be a number in (0, 1], got 0"),
        ([_entry("kyra", k, 1.2)],
         "panel 2: character kyra's strength must be a number in (0, 1], got 1.2"),
        ([_entry("kyra", k, True)],
         "panel 2: character kyra's strength must be a number in (0, 1], got True"),
    ]
    for characters, message in cases:
        panels = _chain_panels(k, r)
        panels[1]["characters"] = characters
        with pytest.raises(ValueError) as info:
            render.load_manifest(_write_manifest(tmp_path, panels))
        assert str(info.value) == message


def test_p8_uncast_units_keep_the_r4l_keys():
    panels = [{"index": 1, "image_path": None, "panel_text": "a", "motion_prompt": "a",
               "conditioning": "t2v", "characters": []},
              {"index": 2, "image_path": None, "panel_text": "b", "motion_prompt": "b",
               "conditioning": "t2v"}]
    for unit in render.build_units(panels, 0, "/clips"):
        assert set(unit) == R4L_KEYS


def test_p9_each_panel_renders_with_its_own_loras(tmp_path, monkeypatch):
    k, r = _lora(tmp_path, "kyra"), _lora(tmp_path, "ronin")
    h = _CastHarness(monkeypatch, tmp_path / "run", _chain_panels(k, r))
    assert h.run() == 0
    assert h.rendered() == [1, 2, 3]
    assert h.kwargs(1)["loras"] == [(k, 1.0)]
    assert h.kwargs(2)["loras"] == [(k, 0.8), (r, 0.8)]
    assert "loras" not in h.kwargs(3)
    assert all(kw["lora_path"] is None for _, kw in h.received)


def test_p10_global_lora_combines_with_the_cast(tmp_path, monkeypatch):
    k, r, g = _lora(tmp_path, "kyra"), _lora(tmp_path, "ronin"), _lora(tmp_path, "global")
    h = _CastHarness(monkeypatch, tmp_path / "run", _chain_panels(k, r))
    assert h.run("--lora", g) == 0
    assert h.kwargs(1)["loras"] == [(g, 1.0), (k, 1.0)]
    assert h.kwargs(2)["loras"] == [(g, 1.0), (k, 0.8), (r, 0.8)]
    assert h.kwargs(3)["loras"] == [(g, 1.0)]
    assert all(kw["lora_path"] is None for _, kw in h.received)


def test_p11_dry_run_lists_each_panels_loras(tmp_path, monkeypatch, capsys):
    k, r = _lora(tmp_path, "kyra"), _lora(tmp_path, "ronin")
    h = _CastHarness(monkeypatch, tmp_path / "run", _chain_panels(k, r))
    assert h.run("--dry-run") == 0
    lines = capsys.readouterr().out.splitlines()
    p1 = next(i for i, line in enumerate(lines) if line.startswith("  panel  1:"))
    p2 = next(i for i, line in enumerate(lines) if line.startswith("  panel  2:"))
    assert lines[p1 + 1] == "            lora: %s @ 1.0 (kyra)" % k
    assert lines[p2 + 1:p2 + 3] == ["            lora: %s @ 0.8 (kyra)" % k,
                                    "            lora: %s @ 0.8 (ronin)" % r]
    first = next(line for line in lines if line.startswith("first render command:"))
    assert "--lora %s 1.0" % k in first
    assert h.received == []


def test_p12_uncast_dry_run_has_no_lora_lines(tmp_path, monkeypatch, capsys):
    k, r = _lora(tmp_path, "kyra"), _lora(tmp_path, "ronin")
    panels = _chain_panels(k, r)
    for panel in panels:
        panel.pop("characters", None)
    h = _CastHarness(monkeypatch, tmp_path / "run", panels)
    assert h.run("--dry-run") == 0
    out = capsys.readouterr().out
    assert "lora:" not in out
    assert "--lora" not in out


def test_p13_provenance_records_the_lora_set(tmp_path):
    k, r = _lora(tmp_path, "kyra"), _lora(tmp_path, "ronin")
    args = _render_args(_model_fixture(tmp_path))
    cast_unit = render.build_units(_chain_panels(k, r)[:1], 0, str(tmp_path))[0]
    provenance = render.build_clip_provenance(cast_unit, args)
    with open(k, "rb") as f:
        digest = hashlib.sha256(f.read()).hexdigest()
    assert provenance["loras"] == [{"kind": "character", "path": k, "sha256": digest,
                                    "strength": 1.0}]
    uncast = [{"index": 1, "image_path": None, "panel_text": "m1", "motion_prompt": "m1",
               "conditioning": "t2v"}]
    assert "loras" not in render.build_clip_provenance(
        render.build_units(uncast, 0, str(tmp_path))[0], args)


def test_p14_resume_reuses_an_identical_cast_render(tmp_path, monkeypatch):
    k, r = _lora(tmp_path, "kyra"), _lora(tmp_path, "ronin")
    h = _CastHarness(monkeypatch, tmp_path / "run", _chain_panels(k, r))
    assert h.run() == 0
    h.received[:] = []
    assert h.run("--resume", "--force") == 0
    assert h.rendered() == []
    assert [u["resumed"] for u in h.newest_summary()["units"]] == [True, True, True]


def test_p15_resume_never_reuses_a_different_lora_set(tmp_path, monkeypatch):
    k, r = _lora(tmp_path, "kyra"), _lora(tmp_path, "ronin")

    def _first_run(sub):
        h = _CastHarness(monkeypatch, tmp_path / sub, _chain_panels(k, r))
        assert h.run() == 0
        h.received[:] = []
        return h

    h = _first_run("a")
    panels = _chain_panels(k, r)
    panels[1]["characters"][1]["strength"] = 0.6
    h.rewrite(panels)
    assert h.run("--resume", "--force") == 0
    assert h.rendered() == [2, 3]

    h = _first_run("b")
    info = os.stat(k)
    with open(k, "wb") as f:
        f.write(b"retrained kyra lora")
    os.utime(k, ns=(info.st_atime_ns, info.st_mtime_ns + 10 ** 9))
    assert h.run("--resume", "--force") == 0
    assert h.rendered() == [1, 2, 3]

    h = _first_run("c")
    panels = _chain_panels(k, r)
    del panels[0]["characters"]
    h.rewrite(panels)
    assert h.run("--resume", "--force") == 0
    assert h.rendered() == [1, 2, 3]


def test_p16_lora_hash_is_memoized_on_identity(tmp_path, monkeypatch):
    k = _lora(tmp_path, "kyra")
    calls = []
    real = render.file_sha256

    def _counting(path):
        calls.append(path)
        return real(path)

    monkeypatch.setattr(render, "file_sha256", _counting)
    monkeypatch.setattr(render, "_LORA_SHA256_CACHE", {})
    first = render.lora_sha256(k)
    assert render.lora_sha256(k) == first
    assert len(calls) == 1
    info = os.stat(k)
    os.utime(k, ns=(info.st_atime_ns, info.st_mtime_ns + 10 ** 9))
    assert render.lora_sha256(k) == first
    assert len(calls) == 2


def test_p17_lora_deleted_before_strict_provenance(tmp_path, monkeypatch, capsys):
    k, r = _lora(tmp_path, "kyra"), _lora(tmp_path, "ronin")
    args = _render_args(_model_fixture(tmp_path))
    unit = render.build_units(_chain_panels(k, r)[:1], 0, str(tmp_path))[0]

    def _never(*a, **kw):
        raise AssertionError("generate_video ran")

    monkeypatch.setattr(render.SKILL, "generate_video", _never)
    os.remove(k)
    result = render.render_panel(unit, args)
    assert result["status"] == "error"
    assert "panel 1 FAILED (provenance)" in capsys.readouterr().err


# --- P61-P67: global LoRAs on the render (spec 5.7.2, 5.7.3, amendment 2) ----------------
def _t2v_panels(n=2):
    return [{"index": i, "image_path": None, "panel_text": "m%d" % i, "motion_prompt": "m%d" % i,
             "conditioning": "t2v"} for i in range(1, n + 1)]


def _provenances(h):
    out = []
    for path in sorted(glob.glob(os.path.join(h.clips, "panel_*.mp4.provenance.json"))):
        with open(path) as f:
            data = json.load(f)
        data.pop("output_sha256")
        out.append(data)
    return out


def _without_logs(received):
    return [(i, {key: v for key, v in kw.items() if key != "log_path"}) for i, kw in received]


def test_p61_legacy_route_is_unchanged(tmp_path, monkeypatch):
    h = _CastHarness(monkeypatch, tmp_path / "run", _t2v_panels())
    assert h.run("--lora", "/tmp/my.safetensors") == 0
    assert all(kw["lora_path"] == "/tmp/my.safetensors" and "loras" not in kw
               for _, kw in h.received)
    g = _lora(tmp_path, "global")
    h.received[:] = []
    assert h.run("--lora", g, "--force") == 0
    plain, plain_provenance = _without_logs(h.received), _provenances(h)
    h.received[:] = []
    assert h.run("--lora", g + ":1.0", "--force") == 0
    assert _without_logs(h.received) == plain
    assert _provenances(h) == plain_provenance
    assert all(p["lora_path"] == g and "loras" not in p for p in plain_provenance)


def test_p62_merged_route_without_a_cast(tmp_path, monkeypatch):
    a, b = _lora(tmp_path, "a"), _lora(tmp_path, "b")
    h = _CastHarness(monkeypatch, tmp_path / "run", _t2v_panels())
    assert h.run("--lora", a + ":1.0", "--lora", b + ":0.5") == 0
    assert all(kw["loras"] == [(a, 1.0), (b, 0.5)] and kw["lora_path"] is None
               for _, kw in h.received)
    assert [[l["kind"] for l in p["loras"]] for p in _provenances(h)] == [["global", "global"]] * 2


def test_p63_global_strength_is_untouched_by_the_character_rule(tmp_path, monkeypatch):
    k, r, a = _lora(tmp_path, "kyra"), _lora(tmp_path, "ronin"), _lora(tmp_path, "a")
    h = _CastHarness(monkeypatch, tmp_path / "run", _chain_panels(k, r))
    assert h.run("--lora", a + ":0.7") == 0
    assert h.kwargs(1)["loras"] == [(a, 0.7), (k, 1.0)]
    assert h.kwargs(2)["loras"] == [(a, 0.7), (k, 0.8), (r, 0.8)]
    assert h.kwargs(3)["loras"] == [(a, 0.7)]


def test_p64_duplicate_loras_are_refused(tmp_path, monkeypatch, capsys):
    k, r, a = _lora(tmp_path, "kyra"), _lora(tmp_path, "ronin"), _lora(tmp_path, "a")
    link_a, link_k = str(tmp_path / "link-a.safetensors"), str(tmp_path / "link-k.safetensors")
    os.symlink(a, link_a)
    os.symlink(k, link_k)
    h = _CastHarness(monkeypatch, tmp_path / "run", _chain_panels(k, r))
    cases = [
        (["--lora", a, "--lora", a], "Error: --lora %s is given more than once\n" % a),
        (["--lora", link_a, "--lora", a], "Error: --lora %s is given more than once\n" % a),
        (["--lora", k], "Error: --lora %s is also character kyra's video LoRA (panel 1); pass it "
                        "once\n" % k),
        (["--lora", link_k], "Error: --lora %s is also character kyra's video LoRA (panel 1); "
                             "pass it once\n" % link_k),
    ]
    for extra, message in cases:
        assert h.run(*extra) == 2, extra
        assert capsys.readouterr().err == message
    assert h.received == []


def test_p65_merged_route_argument_errors(tmp_path, monkeypatch, capsys):
    a = _lora(tmp_path, "a")
    h = _CastHarness(monkeypatch, tmp_path / "run", _t2v_panels())
    assert h.run("--lora", a, "--lora", "/missing.safetensors") == 2
    assert capsys.readouterr().err == "Error: --lora /missing.safetensors: not a readable file\n"
    assert h.run("--lora", a + ":0") == 2
    assert capsys.readouterr().err == (
        "Error: --lora: LoRA strength must be in (0, 2], got '0' in %r\n" % (a + ":0"))
    assert h.run("--lora", a + ":3") == 2
    assert capsys.readouterr().err == (
        "Error: --lora: LoRA strength must be in (0, 2], got '3' in %r\n" % (a + ":3"))
    assert h.received == []


def test_p66_resume_treats_the_global_set_as_identity(tmp_path, monkeypatch):
    k, r = _lora(tmp_path, "kyra"), _lora(tmp_path, "ronin")
    a, b = _lora(tmp_path, "a"), _lora(tmp_path, "b")

    def _rerun(sub, first, second, panels=None, second_panels=None):
        h = _CastHarness(monkeypatch, tmp_path / sub, panels or _chain_panels(k, r))
        assert h.run(*first) == 0
        h.received[:] = []
        if second_panels is not None:
            h.rewrite(second_panels)
        assert h.run(*(list(second) + ["--resume", "--force"])) == 0
        return h.rendered()

    assert _rerun("a", ["--lora", a + ":0.7"], ["--lora", a + ":0.7"]) == []
    assert _rerun("b", ["--lora", a + ":0.7"], ["--lora", a + ":0.6"]) == [1, 2, 3]
    assert _rerun("c", ["--lora", a, "--lora", b], ["--lora", b, "--lora", a]) == [1, 2, 3]
    cast_panel_3 = _t2v_panels(3)
    cast_panel_3[2]["characters"] = [_entry("kyra", a, 0.8)]
    assert _rerun("d", ["--lora", a + ":0.8"], [], panels=_t2v_panels(3),
                  second_panels=cast_panel_3) == [1, 2, 3]


def test_p67_dry_run_lists_globals_first(tmp_path, monkeypatch, capsys):
    k, r, a = _lora(tmp_path, "kyra"), _lora(tmp_path, "ronin"), _lora(tmp_path, "a")
    h = _CastHarness(monkeypatch, tmp_path / "run", _chain_panels(k, r))
    assert h.run("--dry-run", "--lora", a + ":0.7") == 0
    lines = capsys.readouterr().out.splitlines()
    glob_line = "            lora: %s @ 0.7 (global)" % a
    p1 = next(i for i, line in enumerate(lines) if line.startswith("  panel  1:"))
    p2 = next(i for i, line in enumerate(lines) if line.startswith("  panel  2:"))
    p3 = next(i for i, line in enumerate(lines) if line.startswith("  panel  3:"))
    assert lines[p1 + 1:p1 + 3] == [glob_line, "            lora: %s @ 1.0 (kyra)" % k]
    assert lines[p2 + 1:p2 + 4] == [glob_line, "            lora: %s @ 0.8 (kyra)" % k,
                                    "            lora: %s @ 0.8 (ronin)" % r]
    assert lines[p3 + 1] == glob_line


# --- P20-P25: bin/ltx-story-manifest --cast (spec 5.4) -----------------------------------
CAST_STORY = """# Cast test

Two travellers on a forest trail.

## Panel 1 — One
Image: A medium shot of the woman in grey standing on a forest trail. Photorealistic live-action film still.
Motion: {motion1}
Narration: She listens to the trees.

## Panel 2 — Two
Motion: The ronin nods to the woman in grey.
Narration: They agree without a word.

## Panel 3 — Three
Motion: Leaves drift across the empty trail.
Narration: The forest is quiet again.
"""
MOTION_1 = "The woman in grey turns her head; the camera stays static."


def _manifest_env(tmp_path, monkeypatch, motion1=MOTION_1):
    """A workspace root under tmp_path for bin/ltx-story-manifest (its module WS is patched),
    with character_lib.py symlinked in so _character_lib() loads the real module, plus the
    story.md and panel 1's still. Returns (story_md, image, ws)."""
    from PIL import Image
    ws = tmp_path / "ws"
    ws.mkdir()
    os.symlink(os.path.join(WS, "character_lib.py"), str(ws / "character_lib.py"))
    monkeypatch.setattr(story_manifest, "WS", str(ws))
    story_md = tmp_path / "story.md"
    story_md.write_text(CAST_STORY.format(motion1=motion1), encoding="utf-8")
    image = str(tmp_path / "panel_01.png")
    Image.new("RGB", (64, 64), (90, 90, 90)).save(image)
    return str(story_md), image, str(ws)


def _manifest_argv(story_id, story_md, image, *extra):
    return ["--story-id", story_id, "--prompts-md", story_md, "--chain", "--image", image,
            "--fps", "24", "--target-seconds", "18.125", "--min-frames", "145",
            "--max-frames", "145", "--force"] + list(extra)


def _read_manifest(ws, story_id):
    with open(os.path.join(ws, "generated", "stories", story_id, "manifest.json")) as f:
        return json.load(f)


def _short(characters):
    return [(c["name"], c["strength"]) for c in characters]


def test_p20_cast_inserts_triggers_and_lists_characters(tmp_path, monkeypatch, capsys, lib_dir):
    make_character(lib_dir)
    _ronin(lib_dir)
    story_md, image, ws = _manifest_env(tmp_path, monkeypatch)
    assert story_manifest.main(_manifest_argv("uncast", story_md, image)) == 0
    capsys.readouterr()
    assert story_manifest.main(_manifest_argv(
        "cast", story_md, image, "--cast", "the woman in grey=kyra",
        "--cast", "the ronin=ronin")) == 0
    out = capsys.readouterr().out
    uncast, cast = _read_manifest(ws, "uncast"), _read_manifest(ws, "cast")
    assert cast["schema_version"] == 3
    assert [p["motion_prompt"] for p in cast["panels"]] == [
        "The kyrawmn woman in grey turns her head; the camera stays static.",
        "The roninmn ronin nods to the kyrawmn woman in grey.",
        "Leaves drift across the empty trail."]
    assert [p["panel_text"] for p in cast["panels"]] == [p["panel_text"] for p in uncast["panels"]]
    assert [_short(p["characters"]) for p in cast["panels"]] == [
        [("kyra", 1.0)], [("kyra", 0.8), ("ronin", 0.8)], []]
    kyra = cast["panels"][0]["characters"][0]
    assert kyra == {"name": "kyra", "phrase": "the woman in grey", "trigger": "kyrawmn",
                    "video_lora": os.path.join(lib_dir, "kyra", "lora", "video.safetensors"),
                    "strength": 1.0}
    assert all(set(c) == {"name", "phrase", "trigger", "video_lora", "strength"}
               for p in cast["panels"] for c in p["characters"])
    assert "cast: panel 1: kyra@1.0" in out.splitlines()
    assert "cast: panel 2: kyra@0.8, ronin@0.8" in out.splitlines()
    assert not any(line.startswith("cast: panel 3") for line in out.splitlines())


def test_p21_character_strength_and_override(tmp_path, monkeypatch, lib_dir):
    make_character(lib_dir)
    _ronin(lib_dir, strength=0.5)
    story_md, image, ws = _manifest_env(tmp_path, monkeypatch)
    assert story_manifest.main(_manifest_argv(
        "cast", story_md, image, "--cast", "the woman in grey=kyra",
        "--cast", "the ronin=ronin", "--character-strength", "0.6")) == 0
    panels = _read_manifest(ws, "cast")["panels"]
    assert _short(panels[0]["characters"]) == [("kyra", 1.0)]
    assert _short(panels[1]["characters"]) == [("kyra", 0.6), ("ronin", 0.5)]


def test_p22_unused_cast_phrase_warns(tmp_path, monkeypatch, capsys, lib_dir):
    _ronin(lib_dir)
    story_md, image, ws = _manifest_env(tmp_path, monkeypatch)
    assert story_manifest.main(_manifest_argv(
        "cast", story_md, image, "--cast", "the stranger=ronin")) == 0
    assert ("WARNING: cast phrase 'the stranger' (character ronin) occurs in no panel's "
            "Motion: text; that character gets no LoRA") in capsys.readouterr().out
    assert [p["characters"] for p in _read_manifest(ws, "cast")["panels"]] == [[], [], []]


def test_p23_cast_argument_errors(tmp_path, monkeypatch, capsys, lib_dir):
    make_character(lib_dir)
    story_md, image, ws = _manifest_env(tmp_path, monkeypatch)
    manifest = os.path.join(ws, "generated", "stories", "bad", "manifest.json")
    with pytest.raises(SystemExit) as info:
        story_manifest.main(["--story-id", "bad", "--prompts-md", story_md, "--image", image,
                             "--cast", "the woman in grey=kyra"])
    assert info.value.code == 2
    assert "--cast requires --chain" in capsys.readouterr().err
    with pytest.raises(SystemExit) as info:
        story_manifest.main(_manifest_argv("bad", story_md, image, "--character-strength", "0.5"))
    assert info.value.code == 2
    assert "--character-strength requires --cast" in capsys.readouterr().err
    assert story_manifest.main(_manifest_argv("bad", story_md, image,
                                              "--cast", "the ghost=ghost")) == 2
    assert capsys.readouterr().err == "Error: unknown character: ghost (no %s)\n" % os.path.join(
        lib_dir, "ghost", "character.json")
    assert story_manifest.main(_manifest_argv("bad", story_md, image,
                                              "--cast", "the woman in grey=kyra",
                                              "--character-strength", "0")) == 2
    assert capsys.readouterr().err == "Error: --character-strength must be in (0, 1], got 0.0\n"
    assert not os.path.exists(manifest)


def test_p24_uncast_manifest_has_no_characters_key(tmp_path, monkeypatch, lib_dir):
    story_md, image, ws = _manifest_env(tmp_path, monkeypatch)
    assert story_manifest.main(_manifest_argv("uncast", story_md, image)) == 0
    assert all("characters" not in p for p in _read_manifest(ws, "uncast")["panels"])


def test_p25_length_warning_measures_the_cast_prompt(tmp_path, monkeypatch, capsys, lib_dir):
    make_character(lib_dir)
    for filler, warned in ((145, False), (146, True)):
        sub = tmp_path / ("w%d" % filler)
        sub.mkdir()
        motion = "The woman in grey " + " ".join(["walks"] * filler)
        story_md, image, ws = _manifest_env(sub, monkeypatch, motion1=motion)
        capsys.readouterr()
        assert story_manifest.main(_manifest_argv(
            "long", story_md, image, "--cast", "the woman in grey=kyra")) == 0
        out = capsys.readouterr().out
        assert ("WARNING: unit 1 prompt is 151 words" in out) is warned
        assert "WARNING: unit 1 prompt is 150 words" not in out


# --- P30-P35: bin/ltx-story-images --cast (spec 5.5) -------------------------------------
IMAGES_STORY = """# Stills cast test

Two travellers.

## Panel 1 — One
Image: A medium shot of the woman in grey standing on a forest trail. Photorealistic live-action film still.
Motion: The woman in grey turns her head.
Narration: She listens.

## Panel 2 — Two
Image: A medium shot of the ronin waiting under a cedar. Photorealistic live-action film still.
Motion: The ronin nods.
Narration: He waits.
"""


class _FakeContentSafetyError(Exception):
    pass


def _fake_zimage(monkeypatch):
    """Fake torch, z_image_skill and content_safety modules in sys.modules; returns the list
    of (prompt, kwargs) generate_image calls."""
    calls = []

    class _Generator(object):
        def __init__(self, device):
            self.device = device

        def manual_seed(self, seed):
            self.seed = seed
            return self

    fake_torch = types.ModuleType("torch")
    fake_torch.Generator = _Generator
    fake_zimage = types.ModuleType("z_image_skill")
    fake_zimage.generate_image = lambda prompt, **kwargs: calls.append((prompt, kwargs))
    fake_safety = types.ModuleType("content_safety")
    fake_safety.ContentSafetyError = _FakeContentSafetyError
    monkeypatch.setitem(sys.modules, "torch", fake_torch)
    monkeypatch.setitem(sys.modules, "z_image_skill", fake_zimage)
    monkeypatch.setitem(sys.modules, "content_safety", fake_safety)
    return calls


def _images_env(tmp_path):
    story_md = tmp_path / "story.md"
    story_md.write_text(IMAGES_STORY, encoding="utf-8")
    return str(story_md), str(tmp_path / "images")


def _images_json(out_dir):
    with open(os.path.join(out_dir, "images.json")) as f:
        return json.load(f)


def test_p30_still_renders_with_the_stills_lora(tmp_path, monkeypatch, lib_dir):
    make_character(lib_dir, stills=True)
    calls = _fake_zimage(monkeypatch)
    story_md, out_dir = _images_env(tmp_path)
    assert story_images.main(["--story-md", story_md, "--out-dir", out_dir, "--only", "1",
                              "--cast", "the woman in grey=kyra"]) == 0
    stills = os.path.join(lib_dir, "kyra", "lora", "stills.safetensors")
    assert len(calls) == 1
    prompt, kwargs = calls[0]
    assert kwargs["loras"] == [(stills, 1.0)]
    assert kwargs["lora_path"] is None
    assert "the kyrawmn woman in grey" in prompt
    panel = _images_json(out_dir)["panels"][0]
    assert panel["loras"] == [{"kind": "character", "name": "kyra", "path": stills,
                               "strength": 1.0}]
    assert panel["prompt"] == prompt


def test_p31_member_without_stills_lora_warns(tmp_path, monkeypatch, capsys, lib_dir):
    make_character(lib_dir)
    calls = _fake_zimage(monkeypatch)
    story_md, out_dir = _images_env(tmp_path)
    assert story_images.main(["--story-md", story_md, "--out-dir", out_dir, "--only", "1",
                              "--cast", "the woman in grey=kyra"]) == 0
    assert ("WARNING: character kyra has no stills LoRA (not trained); its trigger is not "
            "inserted into Image: prompts and panel stills render without it"
            in capsys.readouterr().out)
    prompt, kwargs = calls[0]
    assert "kyrawmn" not in prompt
    assert "loras" not in kwargs
    assert _images_json(out_dir)["panels"][0]["loras"] == []
    # plan-added (final review): a longer phrase owned by a member WITHOUT a stills LoRA
    # must not lend its span to a shorter phrase owned by a member with one.
    make_character(lib_dir, name="mira", trigger="miragrl", phrase="the woman", stills=True)
    del calls[:]
    assert story_images.main(["--story-md", story_md, "--out-dir", out_dir + "2", "--only", "1",
                              "--cast", "the woman in grey=kyra", "--cast", "the woman=mira"]) == 0
    prompt, kwargs = calls[0]
    assert "miragrl" not in prompt and "kyrawmn" not in prompt
    assert "loras" not in kwargs


def test_p32_different_lora_sets_are_refused(tmp_path, monkeypatch, capsys, lib_dir):
    make_character(lib_dir, stills=True)
    _ronin(lib_dir, stills=True)
    calls = _fake_zimage(monkeypatch)
    story_md, out_dir = _images_env(tmp_path)
    assert story_images.main(["--story-md", story_md, "--out-dir", out_dir, "--only", "1,2",
                              "--cast", "the woman in grey=kyra",
                              "--cast", "the ronin=ronin"]) == 2
    assert capsys.readouterr().err == (
        "Error: the selected panels need different stills LoRA sets (z_image_skill loads one "
        "set per process); run one --only panel per invocation\n")
    assert calls == []
    # plan-added (final review): a LoRA set and an EMPTY set also differ (z_image_skill would
    # keep the fused LoRA for the uncast panel).
    assert story_images.main(["--story-md", story_md, "--out-dir", out_dir, "--only", "1,2",
                              "--cast", "the woman in grey=kyra"]) == 2
    assert "need different stills LoRA sets" in capsys.readouterr().err
    assert calls == []


def test_p33_global_stills_lora_combines_with_the_cast(tmp_path, monkeypatch, lib_dir):
    make_character(lib_dir, stills=True)
    calls = _fake_zimage(monkeypatch)
    story_md, out_dir = _images_env(tmp_path)
    g = str(tmp_path / "g.safetensors")
    with open(g, "wb") as f:
        f.write(b"global")
    assert story_images.main(["--story-md", story_md, "--out-dir", out_dir, "--only", "1",
                              "--cast", "the woman in grey=kyra", "--lora", g + ":0.5"]) == 0
    stills = os.path.join(lib_dir, "kyra", "lora", "stills.safetensors")
    assert calls[0][1]["loras"] == [(g, 0.5), (stills, 1.0)]
    assert calls[0][1]["lora_path"] is None
    assert [l["kind"] for l in _images_json(out_dir)["panels"][0]["loras"]] == ["global",
                                                                               "character"]


def test_p34_dry_run_shows_the_cast_plan_without_torch(tmp_path, lib_dir):
    make_character(lib_dir, stills=True)
    story_md, out_dir = _images_env(tmp_path)
    script = (
        "import sys\n"
        "sys.path.insert(0, %r)\n"
        "import importlib.machinery\n"
        "m = importlib.machinery.SourceFileLoader('ltx_story_images', %r).load_module()\n"
        "rc = m.main(['--story-md', %r, '--out-dir', %r, '--only', '1', '--dry-run',\n"
        "             '--cast', 'the woman in grey=kyra'])\n"
        "print('TORCH_IMPORTED=%%s' %% ('torch' in sys.modules))\n"
        "print('RC=%%d' %% rc)\n"
    ) % (WS, os.path.join(WS, "bin", "ltx-story-images"), story_md, out_dir)
    proc = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True,
                          env=dict(os.environ, CHARACTER_LIBRARY_DIR=lib_dir))
    lines = proc.stdout.splitlines()
    stills = os.path.join(lib_dir, "kyra", "lora", "stills.safetensors")
    assert "RC=0" in lines
    assert "TORCH_IMPORTED=False" in lines
    assert any(line.startswith("1 | ") and "the kyrawmn woman in grey" in line for line in lines)
    assert "    loras: kyra=%s@1.0" % stills in lines


def test_p35_uncast_run_is_unchanged(tmp_path, monkeypatch, lib_dir):
    calls = _fake_zimage(monkeypatch)
    story_md, out_dir = _images_env(tmp_path)
    assert story_images.main(["--story-md", story_md, "--out-dir", out_dir, "--only", "1"]) == 0
    assert "loras" not in calls[0][1]
    assert all("loras" not in p for p in _images_json(out_dir)["panels"])


# --- P68-P69: global stills LoRAs (spec 5.7.4, amendment 2) -------------------------------
def test_p68_global_stills_without_a_cast(tmp_path, monkeypatch, lib_dir):
    calls = _fake_zimage(monkeypatch)
    story_md, out_dir = _images_env(tmp_path)
    assert story_images.main(["--story-md", story_md, "--out-dir", out_dir, "--only", "1",
                              "--lora", "my_lora.safetensors"]) == 0
    assert calls[0][1]["lora_path"] == "my_lora.safetensors"
    assert "loras" not in calls[0][1]
    assert all("loras" not in p for p in _images_json(out_dir)["panels"])
    g1, g2 = str(tmp_path / "g1.safetensors"), str(tmp_path / "g2.safetensors")
    for path in (g1, g2):
        with open(path, "wb") as f:
            f.write(b"global")
    calls[:] = []
    assert story_images.main(["--story-md", story_md, "--out-dir", out_dir, "--only", "1",
                              "--force", "--lora", g1, "--lora", g2 + ":0.5"]) == 0
    assert calls[0][1]["loras"] == [(g1, 1.0), (g2, 0.5)]
    assert calls[0][1]["lora_path"] is None
    assert [l["kind"] for l in _images_json(out_dir)["panels"][0]["loras"]] == ["global", "global"]


def test_p69_global_stills_errors(tmp_path, monkeypatch, capsys, lib_dir):
    make_character(lib_dir, stills=True)
    _ronin(lib_dir, stills=True)
    calls = _fake_zimage(monkeypatch)
    story_md, out_dir = _images_env(tmp_path)
    stills = os.path.join(lib_dir, "kyra", "lora", "stills.safetensors")
    g = str(tmp_path / "g.safetensors")
    with open(g, "wb") as f:
        f.write(b"global")
    base = ["--story-md", story_md, "--out-dir", out_dir]
    assert story_images.main(base + ["--only", "1", "--cast", "the woman in grey=kyra",
                                     "--lora", stills]) == 2
    assert capsys.readouterr().err == (
        "Error: --lora %s is also character kyra's stills LoRA; pass it once\n" % stills)
    assert story_images.main(base + ["--only", "1", "--lora", "/missing:0.5"]) == 2
    assert capsys.readouterr().err == "Error: --lora /missing: not a readable file\n"
    assert story_images.main(base + ["--only", "1,2", "--cast", "the woman in grey=kyra",
                                     "--cast", "the ronin=ronin", "--lora", g + ":0.5"]) == 2
    assert capsys.readouterr().err == (
        "Error: the selected panels need different stills LoRA sets (z_image_skill loads one "
        "set per process); run one --only panel per invocation\n")
    assert calls == []


# --- P40-P49: bin/ltx-movie --character / --cast (spec 5.6) ------------------------------
ANCHOR = "\n\nHow this movie is made:"
MOVIE_STORY = """# Movie cast test

Two travellers.

## Panel 1 — One
Image: A medium shot of {phrase} standing on a forest trail. Photorealistic live-action film still.
Motion: {phrase_cap} turns; the camera stays static.
Narration: A pause.

## Panel 2 — Two
Motion: {phrase_cap} steps forward.
Narration: A step.

## Panel 3 — Three
Motion: {phrase_cap} stops.
Narration: A stop.
"""


def _movie_stories(tmp_path, monkeypatch):
    """Point bin/ltx-movie's story dirs at tmp_path/stories (WS itself is unchanged, so
    _character_lib() and the story.md validator still load from the real workspace)."""
    stories = tmp_path / "stories"
    monkeypatch.setattr(ltx_movie, "_story_dir", lambda sid: str(stories / sid))
    return stories


def _write_story(stories, story_id, phrase):
    directory = stories / story_id
    directory.mkdir(parents=True)
    path = directory / "story.md"
    path.write_text(MOVIE_STORY.format(phrase=phrase, phrase_cap=phrase[0].upper() + phrase[1:]),
                    encoding="utf-8")
    return str(path)


def _movie_args(*argv):
    return ltx_movie.build_parser().parse_args(list(argv))


def test_p40_cast_block_sits_before_the_how_anchor():
    plain = ltx_movie.build_story_prompt("n", "sid", 3, seconds="6")
    expected = plain.replace(ANCHOR, "\n\nCAST" + ANCHOR)
    assert plain.count(ANCHOR) == 1
    assert ltx_movie.build_story_prompt("n", "sid", 3, seconds="6", cast_block="CAST") == expected
    assert ltx_movie.build_story_prompt("n", "sid", 3, seed_image=True, seconds="6",
                                        cast_block="CAST") == (
        ltx_movie.SEED_IMAGE_PREFACE + "\n\n" + expected + "\n\n" + ltx_movie.SEED_IMAGE_POSTFACE)


def test_p41_no_cast_block_means_no_change():
    plain = ltx_movie.build_story_prompt("n", "sid", 3, seconds="6")
    assert ltx_movie.build_story_prompt("n", "sid", 3, seconds="6", cast_block=None) == plain
    assert ltx_movie.build_story_prompt("n", "sid", 3, seconds="6", cast_block="") == plain


def test_p42_resolve_casting_errors(tmp_path, monkeypatch, capsys, lib_dir):
    make_character(lib_dir)
    _ronin(lib_dir)
    stories = _movie_stories(tmp_path, monkeypatch)
    override = tmp_path / "prompt.txt"
    override.write_text("verbatim prompt", encoding="utf-8")
    new_md = str(stories / "new" / "story.md")
    old_md = _write_story(stories, "old", "the traveller")
    cases = [
        (["n", "--story-id", "new", "--character-strength", "0.5"],
         "Error: --character-strength requires --character or --cast"),
        (["n", "--story-id", "new", "--character", "kyra", "--no-stills"],
         "Error: --character/--cast are not supported with --no-stills: casting needs the "
         "chained flow"),
        (["n", "--story-id", "new", "--character", "kyra", "--character-strength", "1.5"],
         "Error: --character-strength must be in (0, 1], got 1.5"),
        (["n", "--story-id", "new", "--cast", "the ronin"],
         "Error: --cast must be PHRASE=NAME, got 'the ronin'"),
        (["n", "--story-id", "new", "--character", "ghost"],
         "Error: unknown character: ghost (no %s)\n"
         "available characters: kyra (the woman in grey), ronin (the ronin)"
         % os.path.join(lib_dir, "ghost", "character.json")),
        (["n", "--story-id", "new", "--character", "kyra", "--cast", "the woman in grey=ronin"],
         "Error: cast phrase 'the woman in grey' is used for both kyra and ronin"),
        (["n", "--story-id", "new", "--cast", "the ronin=ronin"],
         "Error: --cast needs an existing story.md that already uses the phrase, and Phase 1 is "
         "about to write a new one (%s); use --character to cast a new story" % new_md),
        (["--story-id", "new", "--character", "kyra", "--story-prompt-override", str(override)],
         "Error: --character cannot be combined with --story-prompt-override when Phase 1 runs: "
         "the override is used verbatim, so the Cast block cannot be added"),
        (["n", "--story-id", "old", "--character", "kyra"],
         "Error: cast phrase 'the woman in grey' (character kyra) does not occur in %s" % old_md),
    ]
    for argv, message in cases:
        args = _movie_args(*argv)
        assert ltx_movie._resolve_casting(args) == 2, argv
        assert capsys.readouterr().err == message + "\n"
        assert args.cast_members == []


def test_p43_character_on_a_new_story_builds_the_cast_block(tmp_path, monkeypatch, lib_dir):
    make_character(lib_dir)
    _movie_stories(tmp_path, monkeypatch)
    args = _movie_args("n", "--story-id", "new", "--character", "kyra")
    assert ltx_movie._resolve_casting(args) == 0
    members = character_lib.resolve_cast([(None, "kyra")])
    assert args.cast_block == character_lib.build_cast_block(members)
    assert args.cast_members == members
    assert args.character_strength == 0.8


def test_p44_existing_story_mixes_character_and_cast(tmp_path, monkeypatch, lib_dir):
    make_character(lib_dir)
    _ronin(lib_dir)
    stories = _movie_stories(tmp_path, monkeypatch)
    path = _write_story(stories, "old", "the woman in grey")
    with open(path, "a", encoding="utf-8") as f:
        f.write("\n## Panel 4 — Four\nMotion: The ronin waits.\nNarration: He waits.\n")
    args = _movie_args("n", "--story-id", "old", "--character", "kyra",
                       "--cast", "the ronin=ronin")
    assert ltx_movie._resolve_casting(args) == 0
    assert args.cast_block is None
    assert [m.name for m in args.cast_members] == ["kyra", "ronin"]
    assert ltx_movie._cast_flags(args) == [
        "--cast", "the woman in grey=kyra", "--cast", "the ronin=ronin",
        "--character-strength", "0.8"]


def test_p45_cast_flags_empty_when_uncast():
    import argparse
    assert ltx_movie._cast_flags(argparse.Namespace()) == []
    assert ltx_movie._cast_flags(argparse.Namespace(cast_members=[],
                                                    character_strength=0.8)) == []


def test_p46_dry_run_with_character(tmp_path, monkeypatch, capsys, lib_dir):
    make_character(lib_dir)
    _movie_stories(tmp_path, monkeypatch)
    assert ltx_movie.main(["two travellers", "--story-id", "casting-p46", "--dry-run",
                           "--no-review", "--character", "kyra"]) == 0
    out = capsys.readouterr().out
    video = os.path.join(lib_dir, "kyra", "lora", "video.safetensors")
    assert "--- Cast ---" in out.splitlines()
    assert ('cast: kyra as "the woman in grey" (trigger kyrawmn; video LoRA %s; stills LoRA '
            'none: not trained)' % video) in out.splitlines()
    block = character_lib.build_cast_block(character_lib.resolve_cast([(None, "kyra")]))
    assert "\n\n" + block + ANCHOR in out
    commands = [line for line in out.splitlines() if line.startswith("Command: ")]
    flags = "--cast 'the woman in grey=kyra' --character-strength 0.8"
    assert flags in next(c for c in commands if "ltx-story-images" in c)
    assert flags in next(c for c in commands if "ltx-story-manifest" in c)


def test_p47_phase1_warns_when_story_md_omits_a_cast_phrase(tmp_path, monkeypatch, capsys,
                                                            lib_dir):
    make_character(lib_dir)
    stories = _movie_stories(tmp_path, monkeypatch)
    _write_story(stories, "old", "the traveller")
    args = _movie_args("n", "--story-id", "old", "--panels", "3", "--no-review")
    args.cast_members = character_lib.resolve_cast([(None, "kyra")])
    assert ltx_movie.phase1_story(args) == 0
    assert ("Warning: story.md does not use cast phrase 'the woman in grey'; character kyra "
            "gets no LoRA in this story") in capsys.readouterr().out


def test_p48_phase2_warns_about_a_reused_panel_01(tmp_path, monkeypatch, capsys, lib_dir):
    make_character(lib_dir)
    stories = _movie_stories(tmp_path, monkeypatch)
    _write_story(stories, "old", "the woman in grey")
    images = stories / "old" / "images"
    images.mkdir()
    (images / "panel_01.png").write_bytes(b"png")
    runs = []
    monkeypatch.setattr(ltx_movie.subprocess, "run",
                        lambda cmd, **kw: runs.append(cmd) or subprocess.CompletedProcess(cmd, 0))
    args = _movie_args("n", "--story-id", "old")
    args.video_width, args.video_height = 704, 448
    args.cast_members = character_lib.resolve_cast([(None, "kyra")])
    args.character_strength = 0.8
    assert ltx_movie.phase2_stills(args) == 0
    assert ("Warning: %s exists and will be reused as-is; it was not necessarily rendered with "
            "the cast's stills LoRAs (delete it to regenerate)" % (images / "panel_01.png")
            in capsys.readouterr().out)
    assert runs[0][-4:] == ["--cast", "the woman in grey=kyra", "--character-strength", "0.8"]


def test_p49_uncast_ltx_movie_never_loads_character_lib():
    script = (
        "import contextlib, io, sys\n"
        "sys.path.insert(0, %r)\n"
        "import importlib.machinery\n"
        "m = importlib.machinery.SourceFileLoader('ltx_movie', %r).load_module()\n"
        "with contextlib.redirect_stdout(io.StringIO()):\n"
        "    rc = m.main(['n', '--story-id', 'x', '--dry-run', '--no-review'])\n"
        "print('RC=%%d' %% rc)\n"
        "print('CHARACTER_LIB_LOADED=%%s' %% ('character_lib' in sys.modules))\n"
    ) % (WS, os.path.join(WS, "bin", "ltx-movie"))
    proc = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True)
    lines = proc.stdout.splitlines()
    assert "RC=0" in lines
    assert "CHARACTER_LIB_LOADED=False" in lines



# --- P50-P57: cast discovery and --list-characters (spec 3.9, 5.6(i), amendment) ---------
def _c45_library(lib):
    """kyra (trained, no stills), ronin (untrained) and an invalid bad (spec C45)."""
    make_character(lib)
    _ronin(lib, status="untrained")
    os.makedirs(os.path.join(lib, "bad"))
    with open(os.path.join(lib, "bad", "character.json"), "w") as f:
        f.write("{bad")


def _casting_stderr(capsys, *argv):
    args = _movie_args(*argv)
    assert ltx_movie._resolve_casting(args) == 2
    assert args.cast_members == []
    return capsys.readouterr().err


def test_p50_unknown_character_lists_the_usable_ones(tmp_path, monkeypatch, capsys, lib_dir):
    make_character(lib_dir)
    _ronin(lib_dir)
    _movie_stories(tmp_path, monkeypatch)
    assert _casting_stderr(capsys, "n", "--story-id", "new", "--character", "ghost") == (
        "Error: unknown character: ghost (no %s)\n"
        "available characters: kyra (the woman in grey), ronin (the ronin)\n"
        % os.path.join(lib_dir, "ghost", "character.json"))


def test_p51_no_usable_characters(tmp_path, monkeypatch, capsys, lib_dir):
    _movie_stories(tmp_path, monkeypatch)
    none = "available characters: none (create one with bin/character create)"
    err = _casting_stderr(capsys, "n", "--story-id", "new", "--character", "ghost")
    assert err.splitlines()[1] == none
    make_character(lib_dir, name="zed", trigger="zedtrig", phrase="the zed", status="untrained")
    err = _casting_stderr(capsys, "n", "--story-id", "new", "--character", "zed")
    assert err.splitlines() == [
        "Error: character zed is not trained (status untrained); run bin/character train zed",
        none]


def test_p52_which_errors_list_alternatives(tmp_path, monkeypatch, capsys, lib_dir):
    make_character(lib_dir)
    _ronin(lib_dir)
    _movie_stories(tmp_path, monkeypatch)
    both = "available characters: kyra (the woman in grey), ronin (the ronin)"
    assert _casting_stderr(capsys, "n", "--story-id", "new", "--cast", "the ronin=Ronin") == (
        "Error: character name must match [a-z][a-z0-9-]{1,23}, got 'Ronin'\n" + both + "\n")
    assert _casting_stderr(capsys, "n", "--story-id", "new", "--character", "kyra",
                           "--character", "kyra") == (
        "Error: character kyra is cast more than once\n")
    assert _casting_stderr(capsys, "n", "--story-id", "new", "--cast", "the ronin") == (
        "Error: --cast must be PHRASE=NAME, got 'the ronin'\n")
    video = os.path.join(lib_dir, "kyra", "lora", "video.safetensors")
    os.remove(video)
    assert _casting_stderr(capsys, "n", "--story-id", "new", "--character", "kyra") == (
        "Error: character kyra's video LoRA is missing or empty: %s\n"
        "available characters: ronin (the ronin)\n" % video)


def _story_locks():
    return set(glob.glob(os.path.join(WS, "generated", "stories", "**", ".movie.lock"),
                         recursive=True))


def test_p53_list_characters_prints_the_table_and_touches_nothing(monkeypatch, capsys,
                                                                  lib_dir):
    import builtins
    _c45_library(lib_dir)

    def _forbidden(*args, **kwargs):
        raise AssertionError("--list-characters ran a subprocess or prompted")

    monkeypatch.setattr(ltx_movie.subprocess, "run", _forbidden)
    monkeypatch.setattr(ltx_movie.subprocess, "Popen", _forbidden)
    monkeypatch.setattr(builtins, "input", _forbidden)
    before = _story_locks()
    assert ltx_movie.main(["--list-characters"]) == 0
    out, err = capsys.readouterr()
    assert out == "\n".join(character_lib.character_table_lines()) + "\n"
    assert err == ""
    assert _story_locks() == before


def test_p54_list_characters_must_be_alone(capsys):
    for argv in (["--list-characters", "--story-id", "x"], ["a narrative", "--list-characters"],
                 ["--list-characters", "--help"],
                 ["--list-char", "--story-id", "x", "--dry-run", "a narrative"]):
        assert ltx_movie.main(argv) == 2, argv
        out, err = capsys.readouterr()
        assert err == "Error: --list-characters takes no other arguments\n"
        assert out == ""


def test_p56_help_lists_the_flag():
    helptext = " ".join(ltx_movie.build_parser().format_help().split())
    assert "--list-characters" in helptext
    assert "145 frames @ 24 fps = 6.04s per clip." in helptext


def test_p57_manifest_and_images_print_no_available_line(tmp_path, monkeypatch, capsys,
                                                         lib_dir):
    make_character(lib_dir)
    unknown = "Error: unknown character: ghost (no %s)\n" % os.path.join(
        lib_dir, "ghost", "character.json")
    story_md, image, ws = _manifest_env(tmp_path, monkeypatch)
    assert story_manifest.main(_manifest_argv("p57", story_md, image,
                                              "--cast", "the ronin=ghost")) == 2
    assert capsys.readouterr().err == unknown
    calls = _fake_zimage(monkeypatch)
    images_dir = tmp_path / "images-case"
    images_dir.mkdir()
    images_md, out_dir = _images_env(images_dir)
    assert story_images.main(["--story-md", images_md, "--out-dir", out_dir, "--only", "1",
                              "--cast", "the ronin=ghost"]) == 2
    assert capsys.readouterr().err == unknown
    assert calls == []



# --- P70-P73, P75: global LoRAs in bin/ltx-movie (spec 5.7.1, 5.7.5, amendment 2) ---------
def _global_args(*argv):
    args = _movie_args(*argv)
    args.video_width, args.video_height = 704, 448
    return args


def _resolve_both(args):
    rc = ltx_movie._resolve_casting(args)
    return rc or ltx_movie._resolve_global_loras(args)


def _real_file(tmp_path, name):
    path = str(tmp_path / name)
    with open(path, "wb") as f:
        f.write(name.encode())
    return path


def test_p70_legacy_lora_is_forwarded_raw(tmp_path, monkeypatch):
    _movie_stories(tmp_path, monkeypatch)
    args = _global_args("n", "--story-id", "new", "--lora", "x")
    assert _resolve_both(args) == 0
    assert (args.global_video_loras, args.global_stills_loras) == ([], [])
    flags = ltx_movie._render_flags(args)
    assert flags[flags.index("--lora"):flags.index("--lora") + 2] == ["--lora", "x"]
    assert flags.count("--lora") == 1
    regression = _load("casting_regression_for_p70", "tests/test_casting_regression.py")
    with open(regression.GOLDEN_B1, encoding="utf-8") as f:
        assert regression.b1_text() == f.read()


def test_p71_merged_globals_are_forwarded_with_strengths(tmp_path, monkeypatch, capsys, lib_dir):
    make_character(lib_dir, stills=True)
    _movie_stories(tmp_path, monkeypatch)
    _real_file(tmp_path, "g.safetensors")
    _real_file(tmp_path, "s.safetensors")
    monkeypatch.chdir(tmp_path)
    abs_g, abs_s = os.path.abspath("g.safetensors"), os.path.abspath("s.safetensors")
    args = _global_args("n", "--story-id", "new", "--character", "kyra",
                        "--lora", "g.safetensors:0.7", "--stills-lora", "s.safetensors")
    assert _resolve_both(args) == 0
    flags = ltx_movie._render_flags(args)
    assert flags[flags.index("--lora"):flags.index("--lora") + 2] == ["--lora", abs_g + ":0.7"]
    assert "g.safetensors:0.7" not in flags and "g.safetensors" not in flags
    assert ltx_movie.main(["n", "--story-id", "new", "--dry-run", "--no-review",
                           "--character", "kyra", "--lora", "g.safetensors:0.7",
                           "--stills-lora", "s.safetensors"]) == 0
    phase2 = next(line for line in capsys.readouterr().out.splitlines()
                  if line.startswith("Command: ") and "ltx-story-images" in line)
    assert phase2.endswith("--lora %s:1.0 --cast 'the woman in grey=kyra' --character-strength 0.8"
                           % abs_s)


def test_p72_ltx_movie_global_lora_errors(tmp_path, monkeypatch, capsys, lib_dir):
    make_character(lib_dir)
    _movie_stories(tmp_path, monkeypatch)
    video = os.path.join(lib_dir, "kyra", "lora", "video.safetensors")
    s, g = _real_file(tmp_path, "s.safetensors"), _real_file(tmp_path, "g.safetensors")
    cases = [
        (["--character", "kyra", "--lora", video],
         "Error: --lora %s is also character kyra's video LoRA; pass it once\n" % video),
        (["--stills-lora", s, "--stills-lora", s],
         "Error: --stills-lora %s is given more than once\n" % s),
        (["--character", "kyra", "--lora", "g:abc"],
         "Error: --lora g:abc: not a readable file\n"),
    ]
    for extra, message in cases:
        assert _resolve_both(_global_args("n", "--story-id", "new", *extra)) == 2, extra
        assert capsys.readouterr().err == message
    args = _global_args("n", "--story-id", "new", "--character", "kyra", "--lora", g)
    assert _resolve_both(args) == 0
    assert args.global_video_loras == [(g, 1.0)]


def test_p73_repeatable_lora_action():
    ns = _movie_args("n", "--story-id", "s", "--lora", "a", "--lora", "b")
    assert ns.lora_path == "a"
    assert ns.lora_path_specs == ["a", "b"]
    ns = _movie_args("n", "--story-id", "s")
    assert ns.lora_path is None
    assert not hasattr(ns, "lora_path_specs")


def test_p75_repeatable_lora_action_copies_are_identical():
    import inspect
    sources = [inspect.getsource(module._RepeatableLoraAction)
               for module in (ltx_movie, render, story_images)]
    assert sources[0] == sources[1] == sources[2]


# --- P55: bin/ltx-movie --list-characters == bin/character list (spec 5.6(i)) -------------
def test_p55_list_characters_matches_bin_character_list(lib_dir):
    _c45_library(lib_dir)
    env = dict(os.environ, CHARACTER_LIBRARY_DIR=lib_dir)
    movie = subprocess.run([sys.executable, "bin/ltx-movie", "--list-characters"], cwd=WS,
                           env=env, capture_output=True)
    tool = subprocess.run([sys.executable, "bin/character", "list"], cwd=WS, env=env,
                          capture_output=True)
    assert movie.returncode == 0 and tool.returncode == 0
    assert movie.stdout == tool.stdout
    assert movie.stderr == b"" and tool.stderr == b""
