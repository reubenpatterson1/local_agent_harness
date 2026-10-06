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
