"""Plain-python (no pytest) offline tests for bin/ltx-movie.

Run: python3 tests/test_ltx_movie_offline.py
Prints PASS/FAIL per case, then "OK n/n" and exits 0, or exits 1 on any
failure. Offline only -- no sudo, no network, no calls into the real phase
tools except --dry-run-safe invocations of bin/ltx-movie itself (which
never shells out to the wrapped tools under --dry-run).
"""

import ast
import contextlib
import inspect
import io
import os
import re
import shutil
import subprocess
import sys
import tempfile
import importlib.machinery

WS = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
sys.path.insert(0, WS)

_SCRIPT_PATH = os.path.join(WS, "bin", "ltx-movie")
ltx_movie = importlib.machinery.SourceFileLoader("ltx_movie", _SCRIPT_PATH).load_module()

_IMAGES_SCRIPT_PATH = os.path.join(WS, "bin", "ltx-story-images")
ltx_story_images = importlib.machinery.SourceFileLoader(
    "ltx_story_images", _IMAGES_SCRIPT_PATH).load_module()

TOTAL = 0
FAILED = 0


def check(name, condition, detail=""):
    global TOTAL, FAILED
    TOTAL += 1
    if condition:
        print("PASS %s" % name)
    else:
        FAILED += 1
        print("FAIL %s %s" % (name, detail))


# ---------------------------------------------------------------------------
# L1: parser defaults
# ---------------------------------------------------------------------------

def test_parser_defaults():
    args = ltx_movie.build_parser().parse_args(["some narrative", "--story-id", "test"])
    check("L1 panels == 15", args.panels == 15, "got %r" % args.panels)
    check("L1 frames == 145", args.frames == 145, "got %r" % args.frames)
    helptext = " ".join(ltx_movie.build_parser().format_help().split())
    check("L1 --frames help states 6.04s per clip",
          "145 frames @ 24 fps = 6.04s per clip." in helptext, "got %r" % helptext)
    check("L1 --length help states 6.04s per panel at the defaults",
          "6.04s per panel at the defaults" in helptext)
    check("L1 --panels help describes chained clips",
          "number of chained clips; panel 1 also gets the movie's one still image; "
          "mutually exclusive with --length" in helptext)
    check("L1 the description names the chained render",
          "every clip after the first continues from the previous clip's last frame" in helptext)
    check("L1 fps == 24", args.fps == 24, "got %r" % args.fps)
    check("L1 no --image-width/--image-height any more (the still size is derived)",
          not hasattr(args, "image_width") and not hasattr(args, "image_height"))
    check("L1 video_width defaults to None (derived from the seed, or 704 in main)",
          args.video_width is None, "got %r" % args.video_width)
    check("L1 video_height defaults to None (derived from the seed, or 448 in main)",
          args.video_height is None, "got %r" % args.video_height)
    check("L1 no removed backend attribute", not hasattr(args, "video_" + "backend"))
    check("L1 image_seed == 0", args.image_seed == 0, "got %r" % args.image_seed)
    check("L1 panel_timeout == 7200", args.panel_timeout == 7200, "got %r" % args.panel_timeout)
    check("L1 model is the pack id",
          args.model == "MLXBits/ltx-2.3-10eros-v1.2-dmd-mlx-q8", "got %r" % args.model)
    check("L1 gemma is the ltx-2-mlx default text encoder",
          args.gemma == "mlx-community/gemma-3-12b-it-4bit", "got %r" % args.gemma)
    check("L1 lora_path defaults to None", args.lora_path is None, "got %r" % args.lora_path)
    check("L1 stills_lora_path defaults to None", args.stills_lora_path is None,
          "got %r" % args.stills_lora_path)
    check("L1 story_model defaults to None", args.story_model is None,
          "got %r" % args.story_model)
    check("L1 story_context_window defaults to None", args.story_context_window is None,
          "got %r" % args.story_context_window)
    check("L1 low-ram is ON by default (no_low_ram False)", args.no_low_ram is False,
          "got %r" % args.no_low_ram)
    check("L1 tile_frames == 1", args.tile_frames == 1, "got %r" % args.tile_frames)
    check("L1 tile_spatial == 1", args.tile_spatial == 1, "got %r" % args.tile_spatial)
    check("L1 min_avail_gib == 25.0", args.min_avail_gib == 25.0, "got %r" % args.min_avail_gib)
    check("L1 avail_timeout == 1800", args.avail_timeout == 1800, "got %r" % args.avail_timeout)
    check("L1 no_review is False", args.no_review is False, "got %r" % args.no_review)
    check("L1 force_story is False", args.force_story is False, "got %r" % args.force_story)
    check("L1 force is False", args.force is False, "got %r" % args.force)
    check("L1 dry_run is False", args.dry_run is False, "got %r" % args.dry_run)
    check("L1 length is None", args.length is None, "got %r" % args.length)
    check("L1 seed_image is None", args.seed_image is None, "got %r" % args.seed_image)


def test_render_flags_gemma_lora():
    args = ltx_movie.build_parser().parse_args(["a narrative", "--story-id", "test"])
    args.video_width, args.video_height = 704, 448
    default_flags = ltx_movie._render_flags(args)
    check("L1z1 --gemma with the default value is always present",
          "--gemma" in default_flags
          and default_flags[default_flags.index("--gemma") + 1]
          == "mlx-community/gemma-3-12b-it-4bit",
          "got %r" % default_flags)
    check("L1z2 no --lora when lora_path is unset", "--lora" not in default_flags,
          "got %r" % default_flags)

    args.gemma = "Other/Gemma"
    args.lora_path = "/tmp/my.safetensors"
    with_lora = ltx_movie._render_flags(args)
    check("L1z3 --gemma Other/Gemma reaches the render flags",
          "--gemma" in with_lora
          and with_lora[with_lora.index("--gemma") + 1] == "Other/Gemma",
          "got %r" % with_lora)
    check("L1z4 --lora PATH reaches the render flags",
          "--lora" in with_lora
          and with_lora[with_lora.index("--lora") + 1] == "/tmp/my.safetensors",
          "got %r" % with_lora)


def test_stills_lora_reaches_phase2():
    text = inspect.getsource(ltx_movie)
    check("L1z5 both Phase 2 command-construction sites gate --lora on stills_lora_path",
          text.count('["--lora", args.stills_lora_path]') == 2,
          "got %r occurrences" % text.count('["--lora", args.stills_lora_path]'))

    from PIL import Image
    story_id = "unittest-stills-lora-%d" % os.getpid()
    with tempfile.TemporaryDirectory() as tmp:
        seed = os.path.join(tmp, "seed.png")
        Image.new("RGB", (704, 448), (10, 20, 30)).save(seed, format="PNG")
        result = subprocess.run(
            [sys.executable, _SCRIPT_PATH, "a narrative", "--story-id", story_id,
             "--panels", "1", "--seed-image", seed,
             "--stills-lora", "/tmp/my_stills.safetensors", "--dry-run"],
            capture_output=True, text=True, cwd=WS)
        check("L1z6 exits 0", result.returncode == 0,
              "rc=%r stderr=%r" % (result.returncode, result.stderr))
        phase2_lines = [l for l in result.stdout.splitlines() if "ltx-story-images" in l]
        check("L1z7 exactly one phase-2 command line found", len(phase2_lines) == 1,
              "got %r" % phase2_lines)
        if phase2_lines:
            check("L1z8 --stills-lora reaches ltx-story-images as --lora PATH",
                  "--lora /tmp/my_stills.safetensors" in phase2_lines[0],
                  "got %r" % phase2_lines[0])


def test_story_model_reaches_phase1():
    text = inspect.getsource(ltx_movie)
    check("L1z9 both Phase 1 command-construction sites gate --model on story_model",
          text.count('["--model", args.story_model]') == 2,
          "got %r occurrences" % text.count('["--model", args.story_model]'))

    story_id = "unittest-story-model-%d" % os.getpid()
    result = subprocess.run(
        [sys.executable, _SCRIPT_PATH, "a narrative", "--story-id", story_id,
         "--panels", "1", "--story-model",
         "andrevp/Qwen3.5-9B-Distilled-OPUS-Heretic-MLX-VLM-8bit", "--dry-run"],
        capture_output=True, text=True, cwd=WS)
    check("L1z10 exits 0", result.returncode == 0,
          "rc=%r stderr=%r" % (result.returncode, result.stderr))
    m = re.search(r"Command \(subprocess timeout \d+s\): (.*)", result.stdout)
    check("L1z11 phase-1 command line found", m is not None, "got %r" % result.stdout[:1500])
    if m:
        check("L1z12 --story-model reaches qwen-agent as --model VALUE",
              "--model andrevp/Qwen3.5-9B-Distilled-OPUS-Heretic-MLX-VLM-8bit" in m.group(1),
              "got %r" % m.group(1))

    default_result = subprocess.run(
        [sys.executable, _SCRIPT_PATH, "a narrative", "--story-id", story_id + "-default",
         "--panels", "1", "--dry-run"],
        capture_output=True, text=True, cwd=WS)
    m2 = re.search(r"Command \(subprocess timeout \d+s\): (.*)", default_result.stdout)
    check("L1z13 no --story-model omits --model entirely (qwen-agent's own default governs)",
          m2 is not None and "--model" not in m2.group(1), "got %r" % (m2.group(1) if m2 else None))


def test_story_context_window_reaches_phase1():
    text = inspect.getsource(ltx_movie)
    check("L1z14 both Phase 1 command-construction sites gate --context-window on story_context_window",
          text.count('["--context-window", str(args.story_context_window)]') == 2,
          "got %r occurrences"
          % text.count('["--context-window", str(args.story_context_window)]'))

    story_id = "unittest-story-ctx-%d" % os.getpid()
    result = subprocess.run(
        [sys.executable, _SCRIPT_PATH, "a narrative", "--story-id", story_id,
         "--panels", "1", "--story-context-window", "262144", "--dry-run"],
        capture_output=True, text=True, cwd=WS)
    check("L1z15 exits 0", result.returncode == 0,
          "rc=%r stderr=%r" % (result.returncode, result.stderr))
    m = re.search(r"Command \(subprocess timeout \d+s\): (.*)", result.stdout)
    check("L1z16 phase-1 command line found", m is not None, "got %r" % result.stdout[:1500])
    if m:
        check("L1z17 --story-context-window reaches qwen-agent as --context-window VALUE",
              "--context-window 262144" in m.group(1), "got %r" % m.group(1))

    default_result = subprocess.run(
        [sys.executable, _SCRIPT_PATH, "a narrative", "--story-id", story_id + "-default",
         "--panels", "1", "--dry-run"],
        capture_output=True, text=True, cwd=WS)
    m2 = re.search(r"Command \(subprocess timeout \d+s\): (.*)", default_result.stdout)
    check("L1z18 no --story-context-window omits --context-window entirely "
          "(qwen-agent's own discovery/default governs)",
          m2 is not None and "--context-window" not in m2.group(1),
          "got %r" % (m2.group(1) if m2 else None))


def test_removed_flags_rejected():
    # "--video-" + "backend": the spec's grep gate (12.1 item 5) must not match test sources.
    for flag, value in (("--min-frames", "25"), ("--max-frames", "57"),
                        ("--target-seconds", "30"), ("--keep-down", None),
                        ("--reanchor-every", "3"), ("--video-" + "backend", "mlx"),
                        ("--image-width", "1280"), ("--image-height", "704")):
        argv = [sys.executable, _SCRIPT_PATH, "narrative", "--story-id", "x", flag]
        if value is not None:
            argv.append(value)
        argv.append("--dry-run")
        result = subprocess.run(argv, capture_output=True, text=True, cwd=WS)
        check("L23 %s is rejected by the parser" % flag, result.returncode == 2,
              "rc=%r stderr=%r" % (result.returncode, result.stderr))
        check("L23 %s error names the unrecognized flag" % flag,
              "unrecognized arguments" in result.stderr or flag in result.stderr,
              "stderr=%r" % result.stderr)


# ---------------------------------------------------------------------------
# L2: --dry-run exits 0, never touches sudo/servers, prints all 4 phases +
# the rendered story prompt
# ---------------------------------------------------------------------------

def test_dry_run_prints_phases_and_prompt():
    result = subprocess.run(
        [sys.executable, _SCRIPT_PATH, "some narrative text",
         "--story-id", "_test_dryrun", "--dry-run"],
        capture_output=True, text=True, cwd=WS,
    )
    check("L2 --dry-run exits 0", result.returncode == 0, "rc=%r stderr=%r" % (result.returncode, result.stderr))
    for phase in ("Phase 1", "Phase 2", "Phase 3", "Phase 4"):
        check("L2 stdout contains %r" % phase, phase in result.stdout, "stdout=%r" % result.stdout[:2000])
    check("L2 stdout contains the rendered template's no-verify instruction",
          "do NOT run run_python or any other tool to check it" in result.stdout,
          "stdout=%r" % result.stdout[:2000])


# ---------------------------------------------------------------------------
# L3: AST guard -- no top-level import of torch/diffusers/psutil; psutil IS
# imported, but only inside a function body
# ---------------------------------------------------------------------------

def test_ast_guard_no_toplevel_heavy_imports():
    with open(_SCRIPT_PATH) as f:
        source = f.read()
    tree = ast.parse(source, filename=_SCRIPT_PATH)
    heavy = ("torch", "diffusers", "psutil")

    top_violations = []
    for node in tree.body:
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.split(".")[0] in heavy:
                    top_violations.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module and node.module.split(".")[0] in heavy:
                top_violations.append(node.module)
    check("L3 no top-level import of torch/diffusers/psutil", not top_violations,
          "found: %r" % top_violations)

    psutil_in_func = False
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for sub in ast.walk(node):
                if isinstance(sub, ast.Import) and any(a.name == "psutil" for a in sub.names):
                    psutil_in_func = True
                elif isinstance(sub, ast.ImportFrom) and sub.module == "psutil":
                    psutil_in_func = True
    check("L3 psutil is imported, but only inside a function body", psutil_in_func,
          "psutil import not found inside any top-level function")


# ---------------------------------------------------------------------------
# L4: AST/source guard -- "sudo -n" appears, "sudo -S" never does
# ---------------------------------------------------------------------------

def test_sudo_n_not_sudo_s():
    with open(_SCRIPT_PATH) as f:
        text = f.read()
    check("L4 source contains 'sudo -n'", "sudo -n" in text)
    check("L4 source never contains 'sudo -S'", "sudo -S" not in text)


# ---------------------------------------------------------------------------
# L5: story PROMPT template contains VERBATIM / "Do not verify" and formats
# --panels into it
# ---------------------------------------------------------------------------

def test_story_prompt_template():
    prompt = ltx_movie.build_story_prompt("some narrative", "some_id", 5, seconds="6")
    for phrase in ("ONE continuous take", "exact last frame", "Panel 1 has exactly three fields",
                   "Every later panel has exactly two fields", "15-35 words"):
        check("L5a prompt contains %r" % phrase, phrase in prompt, "got %r" % prompt[:800])
    check("L5b no Style: field anywhere", "Style:" not in prompt, "got %r" % prompt)
    check("L5c no braces survive rendering", "{" not in prompt and "}" not in prompt,
          "got %r" % prompt)
    check("L5d no image_rules placeholder", "image_rules" not in prompt)
    check("L5e formats narrative, story_id and panels",
          "some narrative" in prompt and '"some_id"' in prompt
          and "EXACTLY 5 panel sections" in prompt, "got %r" % prompt[:800])
    check("L5f formats the per-clip seconds", "built 6 seconds at a time" in prompt
          and "a 6-second continuation" in prompt, "got %r" % prompt[:800])
    check("L5g is exactly the template formatted with the four placeholders",
          prompt == ltx_movie.STORY_PROMPT_TEMPLATE.format(
              narrative="some narrative", story_id="some_id", panels=5, seconds="6"))
    check("L5h the stop-after-write terminator is kept",
          "Once the write_file call returns, stop immediately" in prompt)
    for no_stills in (False, True):
        for seed_image in (False, True):
            try:
                p = ltx_movie.build_story_prompt("n", "sid", 3, no_stills, seed_image, seconds="6")
                ok = "{" not in p and "}" not in p
            except KeyError:
                ok = False
            check("L5i no_stills=%s seed_image=%s renders without KeyError or braces"
                  % (no_stills, seed_image), ok)
    try:
        ltx_movie.build_story_prompt("n", "sid", 3)
        raised = False
    except TypeError:
        raised = True
    check("L5j seconds is keyword-only and required", raised)
    new_phrase_rule = ("Introduce each character with a referring phrase of at most four words "
                       "built only from details you already gave them in this Image: field or "
                       "that the narrative states, and use that exact phrase for them "
                       "everywhere else in the file. Never add a colour, garment or trait just "
                       "to make the phrase.")
    check("L5k the referring-phrase rule builds the phrase only from given details",
          new_phrase_rule in prompt, "got %r" % prompt[:1800])
    every_prompt = [ltx_movie.build_story_prompt("n", "sid", 3, no_stills, seed_image, seconds="6")
                    for no_stills in (False, True) for seed_image in (False, True)]
    check("L5l no story prompt carries the copied 'woman in grey' example",
          all("woman in grey" not in p for p in every_prompt))


# ---------------------------------------------------------------------------
# L6: lockfile logic
# ---------------------------------------------------------------------------

def test_lock_state():
    with tempfile.TemporaryDirectory() as td:
        lock_path = os.path.join(td, ".movie.lock")

        with open(lock_path, "w") as f:
            f.write("999999")
        state = ltx_movie._lock_state(lock_path)
        check("L6 dead pid reported stale", state == ("stale", 999999), "got %r" % (state,))

        with open(lock_path, "w") as f:
            f.write(str(os.getpid()))
        state = ltx_movie._lock_state(lock_path)
        check("L6 own live pid reported active", state == ("active", os.getpid()), "got %r" % (state,))


# ---------------------------------------------------------------------------
# L7: story validation -- panel missing Motion: is rejected, naming the panel
# ---------------------------------------------------------------------------

def test_validate_story_md_missing_motion():
    with tempfile.TemporaryDirectory() as td:
        good = _write_md(td, "good.md",
                         "# Story\n\n## Panel 1 — First\nImage: a scene one\n"
                         "Motion: she turns\nNarration: one.\n\n"
                         "## Panel 2 — Second\nMotion: she walks away\nNarration: two.\n")
        check("L7a panel 1 with three fields + panel 2 with two fields is valid",
              ltx_movie._validate_story_md(good, 2) == [],
              "got %r" % ltx_movie._validate_story_md(good, 2))

        no_motion_2 = _write_md(td, "no_motion_2.md",
                                "# Story\n\n## Panel 1 — First\nImage: a scene one\n"
                                "Motion: she turns\nNarration: one.\n\n"
                                "## Panel 2 — Second\nNarration: two.\n")
        v = ltx_movie._validate_story_md(no_motion_2, 2)
        check("L7b panel 2 missing Motion: is a violation",
              "panel 2: missing/empty Motion: field" in v, "got %r" % v)

        no_image_1 = _write_md(td, "no_image_1.md",
                               "# Story\n\n## Panel 1 — First\nMotion: she turns\n"
                               "Narration: one.\n\n"
                               "## Panel 2 — Second\nMotion: she walks away\nNarration: two.\n")
        v = ltx_movie._validate_story_md(no_image_1, 2)
        check("L7c panel 1 missing Image: is a violation",
              "panel 1: missing/empty Image: field" in v, "got %r" % v)

        image_2 = _write_md(td, "image_2.md",
                            "# Story\n\n## Panel 1 — First\nImage: a scene one\n"
                            "Motion: she turns\nNarration: one.\n\n"
                            "## Panel 2 — Second\nImage: an old-format picture\n"
                            "Motion: she walks away\nNarration: two.\n")
        check("L7d an Image: on panel 2 is NOT a violation (old-format story.md still renders)",
              ltx_movie._validate_story_md(image_2, 2) == [],
              "got %r" % ltx_movie._validate_story_md(image_2, 2))
        w = ltx_movie._chain_image_warnings(ltx_movie._load_story_panels(image_2))
        check("L7e it produces exactly one advisory warning naming panel 2",
              w == ["panel 2: has an Image: field, which is ignored -- panels after the first "
                    "continue from the previous clip's last frame"], "got %r" % w)
        check("L7f a panel-1-only Image: produces no warning",
              ltx_movie._chain_image_warnings(ltx_movie._load_story_panels(good)) == [])

        prompt_2 = _write_md(td, "prompt_2.md",
                             "# Story\n\n## Panel 1 — First\nImage: a scene one\n"
                             "Motion: she turns\nNarration: one.\n\n"
                             "## Panel 2 — Second\nPrompt: a collapsed field\n"
                             "Motion: she walks away\nNarration: two.\n")
        v = ltx_movie._validate_story_md(prompt_2, 2)
        check("L7g a Prompt: field in stills mode is a violation",
              "panel 2: has a Prompt: field; the chained flow expects Image:, Motion: and "
              "Narration: on panel 1 and Motion: and Narration: on later panels" in v,
              "got %r" % v)
        check("L7h the require_style parameter is gone",
              "require_style" not in inspect.signature(ltx_movie._validate_story_md).parameters)

    with open(_SCRIPT_PATH) as f:
        text = f.read()
    check("L7i the chain-image warning loop is guarded by --no-stills and appears once",
          text.count('    if not args.no_stills:\n'
                     '        for w in _chain_image_warnings(_load_story_panels(story_md)):\n'
                     '            print("Warning: %s" % w)\n') == 1)
    orphans = ("_style_echo_warnings", "_style_content_warnings", "_content_words", "_ECHO_",
               "_STYLE_BANNED_TOKENS", "require_style")
    check("L7j the Style-echo machinery is gone from bin/ltx-movie",
          not any(o in text for o in orphans) and "\nimport re\n" not in text,
          "still present: %r" % [o for o in orphans if o in text])


# ---------------------------------------------------------------------------
# L8 (addendum): --length 60 resolves to panels=30, target_seconds=60.0
# ---------------------------------------------------------------------------

def test_resolve_length_math():
    def _resolve(argv):
        args = ltx_movie.build_parser().parse_args(argv)
        ltx_movie._resolve_length(args, argv)
        return args.panels

    check("L8a --length 60 -> 10 panels (round(9.931) at 145/24)",
          _resolve(["n", "--story-id", "x", "--length", "60"]) == 10,
          "got %r" % _resolve(["n", "--story-id", "x", "--length", "60"]))
    check("L8b --length 12 -> 2 panels (round(1.986))",
          _resolve(["n", "--story-id", "x", "--length", "12"]) == 2,
          "got %r" % _resolve(["n", "--story-id", "x", "--length", "12"]))
    check("L8c the divisor tracks --frames: --length 100 --frames 121 -> 20 panels",
          _resolve(["n", "--story-id", "x", "--length", "100", "--frames", "121"]) == 20,
          "got %r" % _resolve(["n", "--story-id", "x", "--length", "100",
                               "--frames", "121"]))
    check("L8d --length is a no-op when absent",
          _resolve(["n", "--story-id", "x"]) == 15)


# ---------------------------------------------------------------------------
# L9 (addendum): --length conflicts with --panels / --target-seconds
# ---------------------------------------------------------------------------

def test_length_conflicts():
    result = subprocess.run(
        [sys.executable, _SCRIPT_PATH, "narrative", "--story-id", "x",
         "--length", "60", "--panels", "20", "--dry-run"],
        capture_output=True, text=True, cwd=WS)
    check("L9a --length+--panels exits 2", result.returncode == 2, "rc=%r" % result.returncode)
    check("L9b --length+--panels stderr names --panels", "--panels" in result.stderr,
          "stderr=%r" % result.stderr)


def test_length_too_short():
    result = subprocess.run(
        [sys.executable, _SCRIPT_PATH, "narrative", "--story-id", "x",
         "--length", "8", "--dry-run"],
        capture_output=True, text=True, cwd=WS)
    check("L10a --length 8 exits 2", result.returncode == 2,
          "rc=%r stderr=%r" % (result.returncode, result.stderr))
    check("L10b the message names 6.04s per panel", "6.04s per panel" in result.stderr,
          "stderr=%r" % result.stderr)
    check("L10c the message names the resolved panel count",
          "resolves to 1 panel" in result.stderr, "stderr=%r" % result.stderr)
    check("L10d the message tells the operator what to do",
          "Raise --length or pass --panels directly." in result.stderr,
          "stderr=%r" % result.stderr)
    check("L10e there is no upper --length bound any more",
          subprocess.run([sys.executable, _SCRIPT_PATH, "narrative", "--story-id", "x",
                          "--length", "900", "--dry-run"],
                         capture_output=True, text=True, cwd=WS).returncode == 0)


def test_length_100_panels_and_tokens():
    result = subprocess.run(
        [sys.executable, _SCRIPT_PATH, "narrative", "--story-id", "x",
         "--length", "100", "--dry-run"],
        capture_output=True, text=True, cwd=WS)
    check("L11a --length 100 exits 0", result.returncode == 0,
          "rc=%r stderr=%r" % (result.returncode, result.stderr))
    check("L11b story prompt requests EXACTLY 17 panels (round(16.55) at 145/24)",
          "EXACTLY 17" in result.stdout, "stdout=%r" % result.stdout[:2000])
    m = re.search(r"--max-tokens\s+(\d+)", result.stdout)
    check("L11c --max-tokens present", m is not None)
    if m:
        check("L11d --max-tokens is max(4096, 17*550) == 9350", int(m.group(1)) == 9350,
              "got %s" % m.group(1))


def test_phase1_scaling():
    check("L11e 15 panels -> 8250 tokens", ltx_movie._phase1_max_tokens(15) == 8250)
    check("L11f 30 panels -> 16500 tokens", ltx_movie._phase1_max_tokens(30) == 16500)
    check("L11g 5 panels floors at 4096", ltx_movie._phase1_max_tokens(5) == 4096)
    check("L11h 30 panels -> 2700s timeout", ltx_movie._phase1_timeout(30) == 2700)
    check("L11i 5 panels floors at 900s", ltx_movie._phase1_timeout(5) == 900)


# ---------------------------------------------------------------------------
# L12 (addendum): source guard -- Phase 1 nonzero-rc handling checks
# os.path.isfile(story_md) before any return 1 in that block, so a valid
# story.md on disk survives a nonzero qwen-agent exit
# ---------------------------------------------------------------------------

def test_phase1_nonzero_rc_checks_story_md_before_failing():
    with open(_SCRIPT_PATH) as f:
        text = f.read()
    check("L12 source references os.path.isfile(story_md)",
          "os.path.isfile(story_md)" in text)
    check("L12 source contains the story.md-exists warning",
          "qwen-agent exited %d but story.md exists" in text)
    check("L12 source contains the validate-instead-of-fail message",
          "validating the file instead of failing" in text)


# ---------------------------------------------------------------------------
# L13: --no-stills default. The --reanchor-every half of this test died with
# the chain engine -- the parser now rejects that flag outright, which L23
# covers.
# ---------------------------------------------------------------------------

def test_no_stills_default():
    args = ltx_movie.build_parser().parse_args(["narrative", "--story-id", "x"])
    check("L13a --no-stills default is False", args.no_stills is False,
          "got %r" % args.no_stills)


# ---------------------------------------------------------------------------
# L14: --no-stills is orthogonal to --length (spec 9.1 item 6)
# ---------------------------------------------------------------------------

def test_no_stills_orthogonal_to_length():
    def _resolve(argv):
        args = ltx_movie.build_parser().parse_args(argv)
        ltx_movie._resolve_length(args, argv)
        return args.panels

    plain = _resolve(["narrative", "--story-id", "x", "--length", "100"])
    with_flag = _resolve(["narrative", "--story-id", "x", "--no-stills", "--length", "100"])
    check("L14a --no-stills does not change --length resolution", plain == with_flag,
          "got %r vs %r" % (plain, with_flag))
    check("L14b --length 100 resolves to 17 panels", plain == 17, "got %r" % plain)


# ---------------------------------------------------------------------------
# L15: the --no-stills story template (spec 9.1 item 3)
# ---------------------------------------------------------------------------

def test_no_stills_story_prompt_template():
    p = ltx_movie.build_story_prompt("some narrative", "some_id", 7, no_stills=True, seconds="6")
    check("L15a contains Prompt:", "Prompt: <" in p, "got %r" % p[:400])
    check("L15b contains Narration:", "Narration: <" in p)
    check("L15c keeps the VERBATIM consistency rule", "VERBATIM" in p)
    check("L15d states the rule applies to the Prompt: field",
          "full visual description in the Prompt: field" in p)
    check("L15e no Image: field", "Image: <" not in p)
    check("L15f no Motion: field", "Motion: <" not in p)
    check("L15g forbids emitting the old fields",
          "Do not emit an Image: or Motion: field." in p)
    check("L15h word band is 150-220", "150-220 words" in p, "got %r" % p[:600])
    check("L15l Prompt: line asks for a 7-10 sentence chronological paragraph",
          "one flowing paragraph of 7-10 sentences" in p
          and "in strict chronological order" in p, "got %r" % p[:1400])
    check("L15m Prompt: line demands enough beats to fill the clip's seconds",
          "fill the full 6 seconds instead of rushing the action" in p
          and "ten seconds" not in p, "got %r" % p[:1400])
    check("L15n Prompt: line no longer carries the old single-take framing",
          "ONE CONTINUOUS TEN-SECOND TAKE" not in p, "got %r" % p[:900])
    check("L15o Prompt: line keeps the no-cuts / no-new-plot rule",
          "no cuts, no new plot information beyond what this shot shows" in p,
          "got %r" % p[:900])
    check("L15p Prompt: line states the gemma4 caption element order",
          all(s in p for s in ("opens with the main action", "visible physical attributes",
                               "the setting and background", "the shot type",
                               "the lighting and colour"))
          and [p.index(s) for s in ("opens with the main action", "visible physical attributes",
                                    "the setting and background", "the shot type",
                                    "the lighting and colour")]
              == sorted(p.index(s) for s in ("opens with the main action",
                                             "visible physical attributes",
                                             "the setting and background", "the shot type",
                                             "the lighting and colour")),
          "got %r" % p[:1400])
    check("L15q a style line bans abstract mood words and the old intensifier rule is gone",
          'never "she looks sad" or any other mood word' in p
          and '"a vibrant crimson dress"' not in p, "got %r" % p[:1400])
    check("L15s Prompt: line names the temporal connectors",
          '"initially", "as", "then", "while", "simultaneously", "a moment later"' in p,
          "got %r" % p[:1400])
    check("L15t Prompt: line and style line both demand the present tense",
          p.count("in the present tense") >= 2, "got %r" % p[:1400])
    check("L15u Prompt: line prescribes the LTX shot-type vocabulary",
          "extreme wide shot, wide shot, medium shot, medium close-up, close-up, "
          "extreme close-up" in p, "got %r" % p[:1400])
    check("L15v Prompt: line prescribes the LTX camera-viewpoint vocabulary",
          "front-facing, back-facing, side view, over-the-shoulder, top-down, "
          "low-angle or high-angle" in p, "got %r" % p[:1400])
    check("L15w Prompt: line always states camera motion",
          "if the camera holds, say that it remains static" in p, "got %r" % p[:1400])
    check("L15x a style line requires a soundscape and forbids dialogue",
          "Sound is part of the shot" in p and "write no spoken dialogue" in p,
          "got %r" % p[:1400])
    check("L15r a style line bans scene-opener phrasing",
          'never open with "The scene opens with", "We see" or "There is"' in p,
          "got %r" % p[:900])
    check("L15i formats narrative/story_id/panels",
          "some narrative" in p and "some_id" in p and "EXACTLY 7 panel sections" in p)
    check("L15j equals the no-stills template formatted with the four placeholders",
          p == ltx_movie.STORY_PROMPT_TEMPLATE_NO_STILLS.format(
              narrative="some narrative", story_id="some_id", panels=7, seconds="6"))
    check("L15k seed_image=True does not change the no-stills prompt",
          ltx_movie.build_story_prompt("some narrative", "some_id", 7, True, True,
                                       seconds="6") == p)
    check("L15y the production-quality phrases are the model's own choice",
          "Keep each panel's wording plain and factual apart from at most two short "
          "production-quality phrases of your own choosing that suit the narrative." in p,
          "got %r" % p[-1400:])
    every_prompt = [ltx_movie.build_story_prompt("n", "sid", 3, no_stills, seed_image, seconds="6")
                    for no_stills in (False, True) for seed_image in (False, True)]
    check("L15z no story prompt names a fixed production-value phrase",
          all(s not in q for q in every_prompt
              for s in ("warm cinematic lighting", "film-grade color", "crisp fine detail",
                        "production-value")))


# ---------------------------------------------------------------------------
# L16: --no-stills story validation (spec 9.1 item 4)
# ---------------------------------------------------------------------------

def _write_md(td, name, body):
    path = os.path.join(td, name)
    with open(path, "w") as f:
        f.write(body)
    return path


def test_validate_story_md_no_stills():
    with tempfile.TemporaryDirectory() as td:
        good = _write_md(td, "good.md",
                         "# Story\n\nnarr\n\n"
                         "## Panel 1 — A\nPrompt: shot one here\nNarration: one.\n\n"
                         "## Panel 2 — B\nPrompt: shot two here\nNarration: two.\n")
        check("L16a valid Prompt:/Narration: story returns []",
              ltx_movie._validate_story_md(good, 2, no_stills=True) == [],
              "got %r" % ltx_movie._validate_story_md(good, 2, no_stills=True))

        missing = _write_md(td, "missing.md",
                            "# Story\n\nnarr\n\n"
                            "## Panel 1 — A\nPrompt: shot one here\nNarration: one.\n\n"
                            "## Panel 2 — B\nNarration: two.\n")
        v = ltx_movie._validate_story_md(missing, 2, no_stills=True)
        check("L16b missing Prompt: is a violation naming panel 2",
              any("panel 2: missing/empty Prompt: field" == s for s in v), "got %r" % v)

        both = _write_md(td, "both.md",
                         "# Story\n\nnarr\n\n"
                         "## Panel 1 — A\nPrompt: shot one\nImage: also an image\n"
                         "Narration: one.\n")
        v = ltx_movie._validate_story_md(both, 1, no_stills=True)
        check("L16c both forms is a violation naming panel 1",
              any("panel 1: has both Prompt: and Image:/Motion: fields; "
                  "--no-stills expects Prompt: only" == s for s in v), "got %r" % v)

        check("L16d --no-stills does NOT require Image:/Motion:",
              not any("Image" in s and "missing" in s
                      for s in ltx_movie._validate_story_md(good, 2, no_stills=True)))

        today = _write_md(td, "today.md",
                          "# Story\n\nnarr\n\n"
                          "## Panel 1 — A\nImage: a scene\nMotion: pan\nNarration: one.\n")
        check("L16e the default path is unchanged (Image/Motion/Narration required)",
              ltx_movie._validate_story_md(today, 1) == [],
              "got %r" % ltx_movie._validate_story_md(today, 1))
        check("L16f the default path still rejects a Prompt:-only story",
              len(ltx_movie._validate_story_md(good, 2)) > 0)


# ---------------------------------------------------------------------------
# L17: source guards -- Phase 2 is skipped by phase-tuple construction (not
# by an early return inside phase2_stills), and the Phase 3/4 commands carry
# the new flags in the specified positions
# (Two occurrences at this point: phase3_manifest's dry-run command and
# phase4_render's command. _print_dry_run_plan's Phase-3 and Phase-4 command
# blocks -- both handled by Task 23 -- add two more, bringing the total to 4.)
# ---------------------------------------------------------------------------

def test_no_stills_phase_sequencing_source():
    with open(_SCRIPT_PATH) as f:
        text = f.read()
    check("L17a the phase tuple is built conditionally",
          "(phase1_story, phase3_manifest, phase4_render) if args.no_stills" in text,
          "got no conditional phase tuple")
    check("L17b phase2_stills has no --no-stills early return",
          "def phase2_stills(args):" in text
          and "no_stills" not in text.split("def phase2_stills(args):")[1]
                                      .split("def phase3_manifest")[0])
    check("L17c phase 3 swaps --chain/--image for --no-images",
          '"--no-images"' in text
          and '"--chain", "--image", os.path.join(paths["images_dir"], "panel_01.png")' in text
          and '"--glob"' not in text)
    check("L17d Phase 3 and Phase 4 both build their flags from _render_flags",
          text.count("_render_flags(args)") == 4,
          "got %r occurrences" % text.count("_render_flags(args)"))
    check("L17e the chain engine is gone", '"--engine"' not in text,
          "the --engine chain wiring must be gone")
    check("L17f every render invocation targets bin/ltx-mlx-render",
          text.count('os.path.join(WS, "bin", "ltx-mlx-render")') == 4
          and 'os.path.join(WS, "bin", "ltx-story-video")' not in text,
          "got %r" % text.count('os.path.join(WS, "bin", "ltx-mlx-render")'))
    check("L17g the real Phase 3 manifest cmd pins a flat frame count",
          'cmd_manifest += ["--fps", str(args.fps),' in text
          and '"--min-frames", str(args.frames),' in text
          and '"--max-frames", str(args.frames),' in text)


# ---------------------------------------------------------------------------
# L18: --no-stills --dry-run plan (spec 9.1 item 5, criterion 2)
# ---------------------------------------------------------------------------

def test_no_stills_dry_run_plan():
    result = subprocess.run(
        [sys.executable, _SCRIPT_PATH, "a narrative", "--story-id", "unittest-nostills",
         "--no-stills", "--panels", "6", "--dry-run"],
        capture_output=True, text=True, cwd=WS,
    )
    out = result.stdout
    check("L18a exits 0", result.returncode == 0, "rc=%r stderr=%r" % (result.returncode,
                                                                      result.stderr))
    check("L18b Phase 2 is a one-line SKIPPED banner",
          "--- Phase 2: stills --- SKIPPED (--no-stills: no anchor stills are generated)"
          in out, "got %r" % out)
    check("L18c no ltx-story-images command anywhere in the plan",
          "ltx-story-images" not in out, "got %r" % out)
    check("L18d Phase 3 uses --no-images", "--no-images" in out)
    check("L18e Phase 3 does not glob panel_*.png", "panel_*.png" not in out)
    check("L18f no chain flags anywhere", "--engine chain" not in out
          and "--reanchor-every" not in out, "got %r" % out)
    check("L18g the rendered prompt is the no-stills template",
          "Prompt: <150-220 words in the present tense" in out
          and "one flowing paragraph of 7-10 sentences" in out
          and "Image: <a single still-image prompt" not in out)
    check("L18h no per-panel opener/follower table here (it comes from a real Phase 3)",
          "T2V opener" not in out, "got %r" % out)
    check("L18m --no-stills keeps --on-panel-failure skip and never chains",
          "--on-panel-failure skip" in out and "--chain" not in out, "got %r" % out)


def test_default_dry_run_plan_unchanged():
    result = subprocess.run(
        [sys.executable, _SCRIPT_PATH, "a narrative", "--story-id", "unittest-default",
         "--panels", "6", "--dry-run"],
        capture_output=True, text=True, cwd=WS,
    )
    out = result.stdout
    check("L18i default plan still shows Phase 2", "--- Phase 2: stills ---" in out
          and "SKIPPED" not in out, "got %r" % out)
    check("L18j default plan still calls ltx-story-images", "ltx-story-images" in out)
    check("L18k default plan has no --no-images / --engine chain",
          "--no-images" not in out and "--engine chain" not in out)
    check("L18l default plan carries the chained story template",
          "Every later panel has exactly two fields" in out
          and "Motion: <110-160 words" not in out and "ONE CONTINUOUS TEN-SECOND TAKE" not in out,
          "got %r" % out)
    check("L18n default Phase 3 is --chain --image .../images/panel_01.png",
          "--chain --image " in out and "images/panel_01.png" in out and "--glob" not in out,
          "got %r" % out)
    check("L18o default Phase 4 stops on a failed panel",
          "--on-panel-failure stop" in out and "--on-panel-failure skip" not in out,
          "got %r" % out)
    check("L18p no removed backend flag anywhere", ("--video-" + "backend") not in out)


# ---------------------------------------------------------------------------
# L19 (Task 25.1, inserted fix): both qwen-agent invocation sites (phase1_story's
# real cmd and _print_dry_run_plan's preview phase1_cmd) pass --workspace WS
# immediately after the qwen-agent script path, so qwen-agent writes story.md
# into the same repo copy that ltx-movie itself is running from.
# ---------------------------------------------------------------------------

def test_phase1_qwen_agent_gets_workspace_flag():
    with open(_SCRIPT_PATH) as f:
        text = f.read()
    check("L19a exactly 2 qwen-agent invocations pass --workspace WS",
          text.count('"--workspace", WS,') == 2,
          "got %r occurrences" % text.count('"--workspace", WS,'))
    check("L19b --workspace WS immediately follows the qwen-agent path in cmd",
          'cmd = [sys.executable, os.path.join(WS, "bin", "qwen-agent"),\n'
          '               "--workspace", WS,' in text)
    check("L19c --workspace WS immediately follows the qwen-agent path in phase1_cmd",
          'phase1_cmd = [sys.executable, os.path.join(WS, "bin", "qwen-agent"),\n'
          '                  "--workspace", WS,' in text)


# ---------------------------------------------------------------------------
# L20 (Task 25.2, inserted fix): _top5_rss() skips a process whose
# memory_info is None instead of raising AttributeError
# ---------------------------------------------------------------------------

def test_top5_rss_skips_none_memory_info():
    import psutil

    class _FakeMemInfo(object):
        def __init__(self, rss):
            self.rss = rss

    class _FakeProc(object):
        def __init__(self, pid, name, memory_info):
            self.pid = pid
            self.info = {"name": name, "memory_info": memory_info}

    fake_procs = [
        _FakeProc(1, "proc-a", _FakeMemInfo(3 * (2 ** 30))),
        _FakeProc(2, "proc-none", None),
        _FakeProc(3, "proc-b", _FakeMemInfo(7 * (2 ** 30))),
    ]

    def _fake_process_iter(attrs):
        return iter(fake_procs)

    orig_process_iter = psutil.process_iter
    psutil.process_iter = _fake_process_iter
    try:
        result = ltx_movie._top5_rss()
    finally:
        psutil.process_iter = orig_process_iter

    check("L20a _top5_rss does not raise on memory_info=None", True)
    check("L20b proc-none is excluded from the result",
          not any(name == "proc-none" for name, _ in result), "got %r" % (result,))
    names = [name for name, _ in result]
    check("L20c proc-a and proc-b are both included",
          "proc-a" in names and "proc-b" in names, "got %r" % (result,))
    check("L20d result is sorted by RSS descending",
          result == sorted(result, key=lambda item: item[1], reverse=True),
          "got %r" % (result,))
    check("L20e proc-b (7 GiB) sorts before proc-a (3 GiB)",
          result[0][0] == "proc-b", "got %r" % (result,))


# ---------------------------------------------------------------------------
# L24: the dry-run plan targets bin/ltx-mlx-render, never bin/ltx-story-video
# ---------------------------------------------------------------------------

def test_dry_run_plan_targets_mlx_render():
    result = subprocess.run(
        [sys.executable, _SCRIPT_PATH, "a narrative", "--story-id", "unittest-mlx",
         "--panels", "3", "--dry-run"],
        capture_output=True, text=True, cwd=WS)
    out = result.stdout
    check("L24a exits 0", result.returncode == 0,
          "rc=%r stderr=%r" % (result.returncode, result.stderr))
    check("L24b Phase 3 and Phase 4 both name bin/ltx-mlx-render",
          out.count("ltx-mlx-render") == 2, "got %d" % out.count("ltx-mlx-render"))
    check("L24c bin/ltx-story-video is never named", "ltx-story-video" not in out,
          "got %r" % out)
    check("L24d Phase 3 pins the manifest allocator to a flat 145 frames",
          "--min-frames 145 --max-frames 145" in out, "got %r" % out)
    check("L24e --target-seconds is computed as panels*frames/fps",
          "--target-seconds 18.125" in out, "got %r" % out)

    def _val(line, flag):
        t = line.split()
        return t[t.index(flag) + 1] if flag in t else None

    render_lines = [l for l in out.splitlines() if "ltx-mlx-render" in l]
    check("L24f exactly two ltx-mlx-render commands appear (Phase 3 probe, Phase 4 render)",
          len(render_lines) == 2, "got %r" % render_lines)
    for line in render_lines:
        for flag, want in (("--frames", "145"), ("--width", "704"), ("--height", "448"),
                           ("--frame-rate", "24"), ("--tile-frames", "1"),
                           ("--tile-spatial", "1")):
            check("L24f %r has %s %s" % (line.split()[0:2], flag, want),
                  _val(line, flag) == want,
                  "got %r in %r" % (_val(line, flag), line))
    check("L24g --resume is always passed", out.count("--resume") == 2, "got %r" % out)
    check("L24h --no-low-ram is absent by default", "--no-low-ram" not in out, "got %r" % out)
    check("L24i Phase 4 carries the chained failure policy",
          "--on-panel-failure stop" in out and "--retry-failed 1" in out
          and "--retry-idle 120" in out and "--max-consecutive-failures 3" in out
          and "--panel-timeout 7200" in out, "got %r" % out)
    check("L24j Phase 2 renders panel 1 only, at twice the video size",
          "--only 1 --width 1408 --height 896" in out, "got %r" % out)
    check("L24n no removed backend token anywhere", ("--video-" + "backend") not in out)
    check("L24o Phase 3 builds a chained manifest from panel 1's still",
          re.search(r"--chain --image \S*images/panel_01\.png", out) is not None, "got %r" % out)

    forced = subprocess.run(
        [sys.executable, _SCRIPT_PATH, "a narrative", "--story-id", "unittest-mlx2",
         "--panels", "3", "--no-low-ram", "--force", "--dry-run"],
        capture_output=True, text=True, cwd=WS)
    check("L24k --no-low-ram propagates to both phases",
          forced.stdout.count("--no-low-ram") == 2, "got %r" % forced.stdout)

    def _render_lines(stdout):
        return [l for l in stdout.splitlines() if "ltx-mlx-render" in l]

    fl = _render_lines(forced.stdout)
    check("L24l --force reaches BOTH the Phase 3 probe and the Phase 4 render",
          len(fl) == 2 and all("--force" in l.split() for l in fl), "got %r" % fl)
    pl = _render_lines(out)
    check("L24m neither render command carries --force when it was not given",
          len(pl) == 2 and not any("--force" in l.split() for l in pl), "got %r" % pl)


# ---------------------------------------------------------------------------
# L25: --seed-image story-prompt preface
# ---------------------------------------------------------------------------

def test_seed_prompt_preface():
    pre = ltx_movie.SEED_IMAGE_PREFACE
    post = ltx_movie.SEED_IMAGE_POSTFACE
    p_off = ltx_movie.build_story_prompt("n", "sid", 5, seconds="6")
    p_on = ltx_movie.build_story_prompt("n", "sid", 5, False, True, seconds="6")
    check("L25a the unseeded prompt is the plain template",
          p_off == ltx_movie.STORY_PROMPT_TEMPLATE.format(narrative="n", story_id="sid",
                                                          panels=5, seconds="6"))
    check("L25b the preface sentence appears only when seeded",
          "An image is attached to this message." in p_on
          and "An image is attached to this message." not in p_off)
    check("L25c the seeded prompt starts with SEED_IMAGE_PREFACE", p_on.startswith(pre))
    check("L25d the seeded prompt is preface + unseeded template + postface, exactly",
          p_on == pre + "\n\n" + p_off + "\n\n" + post, "got tail %r" % p_on[-400:])
    check("L25e the preface says the attached image IS the first frame",
          "IS the first frame" in pre)
    for phrase in ("faithful, literal description of what the attached image actually shows",
                   "not a generative prompt",
                   "Panel 1's Motion: must start from the exact pose and position shown in "
                   "the attached image."):
        check("L25f the preface contains %r" % phrase[:60], phrase in pre)
    check("L25g neither the preface nor the postface mentions Style: or FAR BAND",
          all("Style:" not in t and "FAR BAND" not in t for t in (pre, post)))
    check("L25h the assembled seeded prompt carries no Style: and no FAR BAND",
          "Style:" not in p_on and "FAR BAND" not in p_on)
    check("L25i --no-stills wins over --seed-image",
          ltx_movie.build_story_prompt("n", "sid", 5, True, True, seconds="6")
          == ltx_movie.build_story_prompt("n", "sid", 5, True, False, seconds="6"))


# ---------------------------------------------------------------------------
# L26: Phase 0 -- _downscale_seed_image and phase0_seed
# ---------------------------------------------------------------------------

def test_phase0_seed_image():
    from PIL import Image, ImageChops, ImageDraw

    with tempfile.TemporaryDirectory() as tmp:
        out_path = os.path.join(tmp, "out.png")

        missing = os.path.join(tmp, "missing.png")
        v, g = ltx_movie._prepare_seed_image(missing, out_path)
        check("L26a missing file -> violation names 'not found'",
              any("not found" in s for s in v), "got %r" % v)
        check("L26a missing file -> no geometry and no output",
              g is None and not os.path.exists(out_path))

        junk = os.path.join(tmp, "junk.png")
        with open(junk, "w") as f:
            f.write("not a real image xx")
        v, g = ltx_movie._prepare_seed_image(junk, out_path)
        check("L26b unreadable file -> violation names 'not a readable image'",
              any("not a readable image" in s for s in v) and g is None, "got %r" % v)

        tiny = os.path.join(tmp, "tiny.png")
        Image.new("RGB", (32, 32), (1, 2, 3)).save(tiny, format="PNG")
        v, g = ltx_movie._prepare_seed_image(tiny, out_path)
        check("L26c 32x32 -> violation names 'degenerate' and '32x32'",
              any("degenerate" in s and "32x32" in s for s in v) and g is None, "got %r" % v)

        big = os.path.join(tmp, "big.png")
        Image.new("RGB", (4000, 3000), (4, 5, 6)).save(big, format="PNG")
        v, g = ltx_movie._prepare_seed_image(big, out_path)
        check("L26d 4000x3000 -> no violations, geometry (512, 384, 0)",
              v == [] and g == (512, 384, 0), "got %r %r" % (v, g))
        with Image.open(out_path) as img:
            check("L26d the story-model copy is a 1024x768 PNG",
                  img.size == (1024, 768) and img.format == "PNG",
                  "got %r %r" % (img.size, img.format))

        under = os.path.join(tmp, "under.png")
        Image.new("RGB", (800, 600), (7, 8, 9)).save(under, format="PNG")
        v, g = ltx_movie._prepare_seed_image(under, out_path)
        check("L26e 800x600 -> (512, 384, 0)", v == [] and g == (512, 384, 0), "got %r %r" % (v, g))
        with Image.open(out_path) as img:
            check("L26e the copy is 1024x768", img.size == (1024, 768), "got %r" % (img.size,))

        at_cap = os.path.join(tmp, "at_cap.png")
        Image.new("RGB", (1024, 1024), (10, 11, 12)).save(at_cap, format="PNG")
        v, g = ltx_movie._prepare_seed_image(at_cap, out_path)
        check("L26f 1024x1024 -> (512, 512, 0)", v == [] and g == (512, 512, 0), "got %r %r" % (v, g))
        with Image.open(out_path) as img:
            check("L26f the copy is 1024x1024", img.size == (1024, 1024), "got %r" % (img.size,))

        rgba = os.path.join(tmp, "rgba.png")
        Image.new("RGBA", (200, 200), (1, 2, 3, 128)).save(rgba, format="PNG")
        v, g = ltx_movie._prepare_seed_image(rgba, out_path)
        check("L26g RGBA input -> no violations", v == [], "got %r" % v)
        with Image.open(out_path) as img:
            check("L26g the copy is RGB", img.mode == "RGB", "got %r" % img.mode)

        wide = os.path.join(tmp, "wide.png")
        Image.new("RGB", (3001, 1000), (13, 14, 15)).save(wide, format="PNG")
        wide_out = os.path.join(tmp, "wide_out.png")
        v, g = ltx_movie._prepare_seed_image(wide, wide_out)
        check("L26h 3001x1000 -> a violation naming '1:3 to 3:1', nothing written",
              any("1:3 to 3:1" in s for s in v) and g is None and not os.path.exists(wide_out),
              "got %r %r" % (v, g))

        exif_path = os.path.join(tmp, "phone.jpg")
        stored = Image.new("RGB", (400, 300), (200, 10, 10))
        exif = stored.getexif()
        exif[0x0112] = 6
        stored.save(exif_path, format="JPEG", exif=exif)
        v, g = ltx_movie._prepare_seed_image(exif_path, out_path)
        check("L26i a JPEG stored 400x300 with EXIF Orientation=6 -> (384, 512, 0)",
              v == [] and g == (384, 512, 0), "got %r %r" % (v, g))

        # L26j: the story-model copy and panel_01.png frame the SAME picture -- equal
        # aspect within 1 px of rounding, and a centred marker stays centred in both.
        src = Image.new("RGB", (900, 600), (255, 0, 0))
        draw = ImageDraw.Draw(src)
        left, top = int(round(450 - 30)), int(round(300 - 30))
        draw.rectangle([left, top, left + 60 - 1, top + 60 - 1], fill=(0, 0, 0))
        src_path = os.path.join(tmp, "marker.png")
        src.save(src_path, format="PNG")
        llm_out = os.path.join(tmp, "llm.png")
        panel_out = os.path.join(tmp, "panel_01.png")
        v, g = ltx_movie._prepare_seed_image(src_path, llm_out)
        ltx_story_images._write_seed_panel(src_path, panel_out, 576, 384)
        with Image.open(llm_out) as a, Image.open(panel_out) as b:
            a, b = a.convert("RGB"), b.convert("RGB")
            check("L26j 900x600 -> geometry (576, 384, 0) and a 1024x683 copy",
                  g == (576, 384, 0) and a.size == (1024, 683), "got %r %r" % (g, a.size))
            check("L26j the copy and panel_01.png have equal aspect within 1 px",
                  b.size == (576, 384) and abs(a.size[1] - a.size[0] * b.size[1] / float(b.size[0])) <= 1.0,
                  "got %r vs %r" % (a.size, b.size))
            for label, img in (("copy", a), ("panel_01", b)):
                bbox = ImageChops.difference(img, Image.new("RGB", img.size, (255, 0, 0))).getbbox()
                ok = bbox is not None and \
                    abs((bbox[0] + bbox[2]) / 2.0 - img.size[0] / 2.0) <= 2 and \
                    abs((bbox[1] + bbox[3]) / 2.0 - img.size[1] / 2.0) <= 2
                check("L26j the marker is centred (+-2 px) in the %s" % label, ok,
                      "bbox=%r size=%r" % (bbox, img.size))

    story_id = "_test_phase0_seed_%d" % os.getpid()
    story_dir = ltx_movie._story_dir(story_id)
    try:
        with tempfile.TemporaryDirectory() as tmp:
            valid_seed = os.path.join(tmp, "valid.png")
            Image.new("RGB", (800, 600), (1, 2, 3)).save(valid_seed, format="PNG")
            args = ltx_movie.build_parser().parse_args(
                ["n", "--story-id", story_id, "--seed-image", valid_seed])
            rc = ltx_movie.phase0_seed(args)
            expected_path = ltx_movie._story_paths(story_id)["seed_downscaled"]
            check("L26k phase0_seed returns 0 for a valid seed", rc == 0, "got %r" % rc)
            check("L26k args.seed_downscaled_path is the expected path",
                  getattr(args, "seed_downscaled_path", None) == expected_path,
                  "got %r" % getattr(args, "seed_downscaled_path", None))
            check("L26k args.video_width/video_height are the derived 512x384",
                  (args.video_width, args.video_height) == (512, 384),
                  "got %r" % ((args.video_width, args.video_height),))
            check("L26k args.seed_pad_px is the residual pad", getattr(args, "seed_pad_px", None) == 0)

            args2 = ltx_movie.build_parser().parse_args(
                ["n", "--story-id", story_id, "--seed-image", os.path.join(tmp, "nope.png")])
            check("L26l phase0_seed returns 2 for a missing seed", ltx_movie.phase0_seed(args2) == 2)
    finally:
        shutil.rmtree(story_dir, ignore_errors=True)


# ---------------------------------------------------------------------------
# L27: --seed-image --dry-run plan
# ---------------------------------------------------------------------------

def test_seed_dry_run_plan():
    from PIL import Image
    story_id = "unittest-seed-%d" % os.getpid()

    def _val(line, flag):
        t = line.split()
        return t[t.index(flag) + 1] if flag in t else None

    with tempfile.TemporaryDirectory() as tmp:
        seed = os.path.join(tmp, "seed1920.png")
        Image.new("RGB", (1920, 1080), (40, 50, 60)).save(seed, format="PNG")
        result = subprocess.run(
            [sys.executable, _SCRIPT_PATH, "a narrative", "--story-id", story_id,
             "--panels", "3", "--seed-image", seed, "--dry-run"],
            capture_output=True, text=True, cwd=WS)
        out = result.stdout
        check("L27a exits 0", result.returncode == 0,
              "rc=%r stderr=%r" % (result.returncode, result.stderr))
        check("L27b stdout contains a Phase 0 block", "--- Phase 0: seed image ---" in out,
              "got %r" % out[:1500])
        check("L27b2 Phase 0 prints the derived geometry and residual pad",
              "video geometry 576x320" in out and "residual pad 7 px" in out,
              "got %r" % out[:2000])

        m = re.search(r"Command \(subprocess timeout \d+s\): (.*)", out)
        check("L27c phase-1 command line found", m is not None, "got %r" % out[:1500])
        if m:
            check("L27c phase-1 command carries --image with a seed_downscaled.png path",
                  re.search(r"--image \S*seed_downscaled\.png", m.group(1)) is not None,
                  "got %r" % m.group(1))

        phase2_lines = [l for l in out.splitlines() if "ltx-story-images" in l]
        check("L27d exactly one phase-2 command line found", len(phase2_lines) == 1,
              "got %r" % phase2_lines)
        if phase2_lines:
            check("L27d phase 2 renders panel 1 only, at twice the derived video size",
                  "--only 1 --width 1152 --height 640" in phase2_lines[0], "got %r" % phase2_lines[0])
            check("L27d phase-2 command carries --seed-image with the ORIGINAL path",
                  ("--seed-image " + seed) in phase2_lines[0], "got %r" % phase2_lines[0])
            check("L27d phase-2 command does not carry the downscaled path",
                  "seed_downscaled" not in phase2_lines[0], "got %r" % phase2_lines[0])
            check("L27f --seed-image appears exactly once in the ltx-story-images command line",
                  phase2_lines[0].count("--seed-image") == 1, "got %r" % phase2_lines[0])

        render_lines = [l for l in out.splitlines() if "ltx-mlx-render" in l]
        check("L27l both render commands carry the derived --width 576 --height 320",
              len(render_lines) == 2
              and all(_val(l, "--width") == "576" and _val(l, "--height") == "320"
                      for l in render_lines), "got %r" % render_lines)
        check("L27e rendered prompt preview contains the preface sentence",
              "An image is attached to this message." in out, "got %r" % out[-2000:])
        check("L27m the dry run wrote no story-model copy",
              not os.path.exists(ltx_movie._story_paths(story_id)["seed_downscaled"]))

        wide = os.path.join(tmp, "wide.png")
        Image.new("RGB", (3001, 1000), (1, 1, 1)).save(wide, format="PNG")
        r = subprocess.run([sys.executable, _SCRIPT_PATH, "a narrative", "--story-id", story_id,
                            "--seed-image", wide, "--dry-run"],
                           capture_output=True, text=True, cwd=WS)
        check("L27k an out-of-range seed fails the dry run with exit 2 naming the bound",
              r.returncode == 2 and "1:3 to 3:1" in r.stderr,
              "rc=%r stderr=%r" % (r.returncode, r.stderr))

    r = subprocess.run([sys.executable, _SCRIPT_PATH, "a narrative", "--story-id", story_id,
                        "--seed-image", "/nonexistent/seed_for_test.png", "--dry-run"],
                       capture_output=True, text=True, cwd=WS)
    check("L27j a missing seed fails the dry run with exit 2",
          r.returncode == 2 and "--seed-image not found" in r.stderr,
          "rc=%r stderr=%r" % (r.returncode, r.stderr))

    plain = subprocess.run(
        [sys.executable, _SCRIPT_PATH, "a narrative", "--story-id", "unittest-seed-off",
         "--panels", "3", "--dry-run"],
        capture_output=True, text=True, cwd=WS)
    check("L27g non-seeded dry-run prints no Phase 0", "Phase 0" not in plain.stdout,
          "got %r" % plain.stdout[:800])
    m = re.search(r"Command \(subprocess timeout \d+s\): (.*)", plain.stdout)
    check("L27h non-seeded phase-1 command carries no --image flag",
          m is not None and "--image " not in m.group(1), "got %r" % (m.group(1) if m else None))
    check("L27i non-seeded dry-run mentions no seed_downscaled anywhere",
          "seed_downscaled" not in plain.stdout, "got %r" % plain.stdout)


# ---------------------------------------------------------------------------
# L28: --seed-image + --no-stills is a hard error, dry-run or not
# ---------------------------------------------------------------------------

def test_seed_no_stills_conflict():
    result = subprocess.run(
        [sys.executable, _SCRIPT_PATH, "a narrative", "--story-id", "unittest-seed-conflict",
         "--seed-image", "/tmp/x.png", "--no-stills", "--dry-run"],
        capture_output=True, text=True, cwd=WS)
    check("L28a --dry-run + conflict exits 2", result.returncode == 2,
          "rc=%r" % result.returncode)
    check("L28b stderr names the incompatibility",
          "--seed-image is incompatible with --no-stills" in result.stderr,
          "got %r" % result.stderr)

    story_id = "unittest-seed-conflict-real"
    story_dir = ltx_movie._story_dir(story_id)
    try:
        result2 = subprocess.run(
            [sys.executable, _SCRIPT_PATH, "a narrative", "--story-id", story_id,
             "--seed-image", "/tmp/x.png", "--no-stills"],
            capture_output=True, text=True, cwd=WS)
        check("L28c non-dry-run + conflict ALSO exits 2 (checked before lock/phase machinery)",
              result2.returncode == 2, "rc=%r" % result2.returncode)
        check("L28d non-dry-run stderr names the same incompatibility",
              "--seed-image is incompatible with --no-stills" in result2.stderr,
              "got %r" % result2.stderr)
        check("L28e no story directory was created", not os.path.exists(story_dir))
    finally:
        shutil.rmtree(story_dir, ignore_errors=True)


# ---------------------------------------------------------------------------
# L29: source guards
# ---------------------------------------------------------------------------

def test_seed_source_guards():
    with open(_SCRIPT_PATH) as f:
        text = f.read()
    tree = ast.parse(text, filename=_SCRIPT_PATH)

    top_level_pil = []
    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and node.module and node.module.split(".")[0] == "PIL":
            top_level_pil.append(node.module)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.split(".")[0] == "PIL":
                    top_level_pil.append(alias.name)
    check("L29a no top-level PIL import", not top_level_pil, "found: %r" % top_level_pil)

    def _is_fit_loader(call):
        return (isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute)
                and call.func.attr == "SourceFileLoader"
                and any(isinstance(n, ast.Constant) and isinstance(n.value, str)
                        and "ltx_image_fit.py" in n.value for n in ast.walk(call)))

    loader_in_func = loader_at_top = False
    for node in tree.body:
        found = any(_is_fit_loader(sub) for sub in ast.walk(node))
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            loader_in_func = loader_in_func or found
        else:
            loader_at_top = loader_at_top or found
    check("L29b bin/ltx-movie loads ltx_image_fit.py only inside a function body",
          loader_in_func and not loader_at_top,
          "in_func=%r at_top=%r" % (loader_in_func, loader_at_top))
    fit_path = os.path.join(WS, "ltx_image_fit.py")
    with open(fit_path) as f:
        fit_tree = ast.parse(f.read(), filename=fit_path)
    fit_top_pil = [n for n in fit_tree.body
                   if (isinstance(n, ast.ImportFrom) and n.module and n.module.split(".")[0] == "PIL")
                   or (isinstance(n, ast.Import) and any(a.name.split(".")[0] == "PIL" for a in n.names))]
    check("L29b2 ltx_image_fit.py has no top-level PIL import", not fit_top_pil)

    check("L29c --image threaded at exactly the 2 expected call sites",
          text.count('cmd += ["--image", args.seed_downscaled_path]') == 1
          and text.count('phase1_cmd += ["--image", paths["seed_downscaled"]]') == 1)
    check("L29d --seed-image threaded at exactly the 2 expected call sites",
          # NOTE: "phase2_cmd += [...]" ends with "cmd += [...]", so counting the
          # plain-"cmd" literal as a substring would double-count it. Anchored on
          # the newline + exact indentation instead, to count each call site once.
          text.count('\n        cmd += ["--seed-image", args.seed_image]') == 1
          and text.count('phase2_cmd += ["--seed-image", args.seed_image]') == 1)
    check("L29e phase0_seed is prepended to the phase tuple",
          "phases = (phase0_seed,) + phases" in text)
    check("L29f --user-prompt is still the last element of the real phase1 cmd",
          'cmd += ["--user-prompt", prompt]' in text)
    check("L29g --user-prompt is still the last element of the dry-run preview phase1_cmd",
          'phase1_cmd += ["--user-prompt", prompt]' in text)


# ---------------------------------------------------------------------------
# L34: SEED_IMAGE_POSTFACE -- the two overrides are restated AFTER the template
# ---------------------------------------------------------------------------

def test_seed_postface_overrides_last():
    p_on = ltx_movie.build_story_prompt("n", "sid", 5, False, True, seconds="6")
    p_off = ltx_movie.build_story_prompt("n", "sid", 5, seconds="6")
    post = ltx_movie.SEED_IMAGE_POSTFACE
    check("L34a the postface is present only when seeded", post in p_on and post not in p_off)
    check("L34b the postface is the tail of the seeded prompt", p_on.endswith(post))
    check("L34c the seeded prompt starts with the preface",
          p_on.startswith(ltx_movie.SEED_IMAGE_PREFACE))
    check("L34d the postface restates the three-field / two-field contract",
          "Panel 1 has exactly three fields -- Image:, Motion:, Narration: --" in post
          and "Every later panel has exactly two fields -- Motion:, Narration: --" in post)
    check("L34e the postface ends with the template's own terminator",
          post.endswith("Do not verify the file with run_python or any other tool. "
                        "Emit no other text."))
    check("L34f the template's two-field rule appears BEFORE the postface restates it",
          p_on.index("Every later panel has exactly two fields, in this order")
          < p_on.index(post))
    check("L34g neither the preface nor the postface mentions Style: or FAR BAND",
          "Style:" not in post and "FAR BAND" not in post
          and "Style:" not in ltx_movie.SEED_IMAGE_PREFACE
          and "FAR BAND" not in ltx_movie.SEED_IMAGE_PREFACE)


# ---------------------------------------------------------------------------
# L48-L50: derived geometry guards in main()
# ---------------------------------------------------------------------------

def test_seed_with_explicit_video_dims_rejected():
    for flag in (["--video-width", "704"], ["--video-height", "448"]):
        r = subprocess.run([sys.executable, _SCRIPT_PATH, "n", "--story-id", "unittest-seed-dims",
                            "--seed-image", "/nonexistent/x.png"] + flag + ["--dry-run"],
                           capture_output=True, text=True, cwd=WS)
        check("L48a %s with --seed-image exits 2" % flag[0], r.returncode == 2,
              "rc=%r stderr=%r" % (r.returncode, r.stderr))
        check("L48b %s: stderr says the geometry is derived from --seed-image" % flag[0],
              "derived from --seed-image" in r.stderr, "stderr=%r" % r.stderr)


def test_video_dims_must_be_64_multiples():
    def _run(extra):
        return subprocess.run([sys.executable, _SCRIPT_PATH, "n", "--story-id",
                               "unittest-dims64"] + extra + ["--dry-run"],
                              capture_output=True, text=True, cwd=WS)
    r = _run(["--video-width", "736"])
    check("L49a --video-width 736 exits 2 naming 'multiples of 64' and the size",
          r.returncode == 2 and "multiples of 64" in r.stderr and "736x448" in r.stderr,
          "rc=%r stderr=%r" % (r.returncode, r.stderr))
    check("L49b --video-height 480 exits 2", _run(["--video-height", "480"]).returncode == 2)
    check("L49c --video-width 0 exits 2", _run(["--video-width", "0"]).returncode == 2)
    ok = _run(["--video-width", "512", "--video-height", "512"])
    check("L49d a 512x512 request is accepted and reaches the render flags",
          ok.returncode == 0 and "--width 512 --height 512" in ok.stdout,
          "rc=%r stderr=%r" % (ok.returncode, ok.stderr))


def test_out_of_range_seed_fails_before_phase1():
    from PIL import Image
    calls = []
    story_id = "_test_out_of_range_%d" % os.getpid()
    saved = (ltx_movie.phase1_story, ltx_movie._check_sudo_and_start_keepalive)
    try:
        with tempfile.TemporaryDirectory() as tmp:
            seed = os.path.join(tmp, "wide.png")
            Image.new("RGB", (3001, 1000), (9, 9, 9)).save(seed, format="PNG")
            ltx_movie.phase1_story = lambda args: (calls.append(args.story_id) or 0)
            ltx_movie._check_sudo_and_start_keepalive = lambda: None
            err, out = io.StringIO(), io.StringIO()
            with contextlib.redirect_stderr(err), contextlib.redirect_stdout(out):
                rc = ltx_movie.main(["a narrative", "--story-id", story_id,
                                     "--seed-image", seed, "--no-review"])
            check("L50a main() returns 2 for a 3001x1000 seed", rc == 2, "rc=%r" % rc)
            check("L50b phase1_story was never called", calls == [], "calls=%r" % calls)
            check("L50c stderr names the 1:3 to 3:1 bound", "1:3 to 3:1" in err.getvalue(),
                  "stderr=%r" % err.getvalue())
            check("L50d no story-model copy was written",
                  not os.path.exists(ltx_movie._story_paths(story_id)["seed_downscaled"]))
    finally:
        ltx_movie.phase1_story, ltx_movie._check_sudo_and_start_keepalive = saved
        shutil.rmtree(ltx_movie._story_dir(story_id), ignore_errors=True)


def test_phase4_flags_policy_by_mode():
    def _flags(extra):
        args = ltx_movie.build_parser().parse_args(["n", "--story-id", "x"] + extra)
        args.video_width, args.video_height = 704, 448
        return ltx_movie._phase4_flags(args)

    stills, nostills = _flags([]), _flags(["--no-stills"])
    check("L51a stills (chained) mode passes --on-panel-failure stop",
          stills[stills.index("--on-panel-failure") + 1] == "stop", "got %r" % stills)
    check("L51b --no-stills passes --on-panel-failure skip",
          nostills[nostills.index("--on-panel-failure") + 1] == "skip", "got %r" % nostills)
    for label, flags in (("stills", stills), ("no-stills", nostills)):
        joined = " ".join(flags)
        check("L51c %s keeps one retry, a 120 s idle and the 3-failure breaker" % label,
              "--retry-failed 1 --retry-idle 120 --max-consecutive-failures 3" in joined,
              "got %r" % joined)
        check("L51d %s carries no removed backend flag" % label,
              ("--video-" + "backend") not in flags)


# ---------------------------------------------------------------------------
# L40-L47: --story-server-stop-after-story (bin/story-server lifecycle tool)
# ---------------------------------------------------------------------------

class _StoryServerArgs(object):
    def __init__(self, no_stills=False, story_server_stop_after_story=False,
                 seed_image=None, min_avail_gib=25.0, avail_timeout=1800):
        self.no_stills = no_stills
        self.story_server_stop_after_story = story_server_stop_after_story
        self.seed_image = seed_image
        self.min_avail_gib = min_avail_gib
        self.avail_timeout = avail_timeout


def _phase_names(phases):
    return tuple(p.__name__ for p in phases)


def test_story_server_flag_default():
    parser = ltx_movie.build_parser()
    args_default = parser.parse_args(["a narrative", "--story-id", "l40"])
    check("L40a --story-server-stop-after-story defaults to True",
          args_default.story_server_stop_after_story is True,
          "got %r" % (args_default.story_server_stop_after_story,))
    args_on = parser.parse_args(["a narrative", "--story-id", "l40",
                                  "--story-server-stop-after-story"])
    check("L40b --story-server-stop-after-story (redundant) still sets True",
          args_on.story_server_stop_after_story is True,
          "got %r" % (args_on.story_server_stop_after_story,))
    args_off = parser.parse_args(["a narrative", "--story-id", "l40",
                                   "--no-story-server-stop-after-story"])
    check("L40b2 --no-story-server-stop-after-story sets False",
          args_off.story_server_stop_after_story is False,
          "got %r" % (args_off.story_server_stop_after_story,))
    check("L40c the flag's dest is exactly story_server_stop_after_story",
          any(getattr(a, "dest", None) == "story_server_stop_after_story"
              for a in parser._actions),
          "no action with that dest")


def test_phase_sequence_ordering():
    cases = [
        (dict(no_stills=False, story_server_stop_after_story=False, seed_image=None),
         ("phase1_story", "phase2_stills", "phase3_manifest", "phase4_render")),
        (dict(no_stills=False, story_server_stop_after_story=True, seed_image=None),
         ("phase1_story", "phase_release_story_server", "phase2_stills",
          "phase3_manifest", "phase4_render")),
        (dict(no_stills=True, story_server_stop_after_story=False, seed_image=None),
         ("phase1_story", "phase3_manifest", "phase4_render")),
        (dict(no_stills=True, story_server_stop_after_story=True, seed_image=None),
         ("phase1_story", "phase_release_story_server", "phase3_manifest", "phase4_render")),
        (dict(no_stills=False, story_server_stop_after_story=False, seed_image="x.png"),
         ("phase0_seed", "phase1_story", "phase2_stills", "phase3_manifest", "phase4_render")),
        (dict(no_stills=False, story_server_stop_after_story=True, seed_image="x.png"),
         ("phase0_seed", "phase1_story", "phase_release_story_server", "phase2_stills",
          "phase3_manifest", "phase4_render")),
        # (F8) no_stills + seed_image: _phase_sequence is pure and does not enforce
        # main()'s mutual exclusion between --no-stills and --seed-image.
        (dict(no_stills=True, story_server_stop_after_story=False, seed_image="x.png"),
         ("phase0_seed", "phase1_story", "phase3_manifest", "phase4_render")),
        (dict(no_stills=True, story_server_stop_after_story=True, seed_image="x.png"),
         ("phase0_seed", "phase1_story", "phase_release_story_server",
          "phase3_manifest", "phase4_render")),
    ]
    for i, (kwargs, expected) in enumerate(cases, 1):
        args = _StoryServerArgs(**kwargs)
        got = _phase_names(ltx_movie._phase_sequence(args))
        check("L41.%d phase order %r" % (i, kwargs), got == expected,
              "got %r expected %r" % (got, expected))


def test_phase_release_story_server():
    orig_run = ltx_movie.subprocess.run
    orig_wait = ltx_movie._wait_for_avail
    try:
        class _Rc(object):
            def __init__(self, returncode):
                self.returncode = returncode

        recorded = {}

        def fake_run_ok(cmd, cwd=None):
            recorded["cmd"] = cmd
            recorded["cwd"] = cwd
            return _Rc(0)

        def fake_run_fail(cmd, cwd=None):
            return _Rc(3)

        wait_calls_a = []

        def fake_wait_true(min_avail_gib, avail_timeout):
            wait_calls_a.append((min_avail_gib, avail_timeout))
            return True

        args = _StoryServerArgs()

        ltx_movie.subprocess.run = fake_run_ok
        ltx_movie._wait_for_avail = fake_wait_true
        rc_a = ltx_movie.phase_release_story_server(args)
        expected_cmd = [os.path.join(ltx_movie.WS, "bin", "story-server"), "stop"]
        check("L42a rc 0 + avail True returns 0", rc_a == 0, "got %r" % rc_a)
        check("L42a argv is exactly [story-server, stop]",
              recorded.get("cmd") == expected_cmd, "got %r" % (recorded.get("cmd"),))
        check("L42a cwd=WS", recorded.get("cwd") == ltx_movie.WS,
              "got %r" % (recorded.get("cwd"),))
        check("L42a _wait_for_avail called exactly once", len(wait_calls_a) == 1,
              "got %r" % wait_calls_a)

        wait_calls_b = []

        def fake_wait_track(min_avail_gib, avail_timeout):
            wait_calls_b.append((min_avail_gib, avail_timeout))
            return True

        ltx_movie.subprocess.run = fake_run_fail
        ltx_movie._wait_for_avail = fake_wait_track
        rc_b = ltx_movie.phase_release_story_server(args)
        check("L42b story-server rc 3 returns 1", rc_b == 1, "got %r" % rc_b)
        check("L42b _wait_for_avail is never called", len(wait_calls_b) == 0,
              "got %r" % wait_calls_b)

        def fake_wait_false(min_avail_gib, avail_timeout):
            return False

        ltx_movie.subprocess.run = fake_run_ok
        ltx_movie._wait_for_avail = fake_wait_false
        rc_c = ltx_movie.phase_release_story_server(args)
        check("L42c rc 0 but avail False returns 1", rc_c == 1, "got %r" % rc_c)
    finally:
        ltx_movie.subprocess.run = orig_run
        ltx_movie._wait_for_avail = orig_wait


def test_dry_run_story_server_block_ordering():
    result = subprocess.run(
        [sys.executable, _SCRIPT_PATH, "a narrative", "--story-id", "unittest-storyserver-l43",
         "--panels", "6", "--story-server-stop-after-story", "--dry-run"],
        capture_output=True, text=True, cwd=WS,
    )
    out = result.stdout
    check("L43 exits 0", result.returncode == 0,
          "rc=%r stderr=%r" % (result.returncode, result.stderr))
    i_1 = out.find("--- Phase 1: story ---")
    i_1b = out.find("--- Phase 1b:")
    i_2 = out.find("--- Phase 2: stills ---")
    check("L43 Phase 1b sits after Phase 1 and before Phase 2",
          i_1 != -1 and i_1b != -1 and i_2 != -1 and i_1 < i_1b < i_2,
          "i_1=%r i_1b=%r i_2=%r" % (i_1, i_1b, i_2))


def test_dry_run_no_story_server_block_with_opt_out():
    result = subprocess.run(
        [sys.executable, _SCRIPT_PATH, "a narrative", "--story-id", "unittest-storyserver-l44",
         "--panels", "6", "--no-story-server-stop-after-story", "--dry-run"],
        capture_output=True, text=True, cwd=WS,
    )
    out = result.stdout
    check("L44a exits 0", result.returncode == 0, "rc=%r" % result.returncode)
    check("L44b no Phase 1b block with the opt-out flag", "Phase 1b" not in out, "got %r" % out)
    check("L44c no story-server mention with the opt-out flag", "story-server" not in out,
          "got %r" % out)


def test_dry_run_story_server_block_with_no_stills():
    result = subprocess.run(
        [sys.executable, _SCRIPT_PATH, "a narrative", "--story-id", "unittest-storyserver-l45",
         "--no-stills", "--panels", "6", "--story-server-stop-after-story", "--dry-run"],
        capture_output=True, text=True, cwd=WS,
    )
    out = result.stdout
    check("L45a exits 0", result.returncode == 0, "rc=%r" % result.returncode)
    i_1 = out.find("--- Phase 1: story ---")
    i_1b = out.find("--- Phase 1b:")
    i_skip = out.find("--- Phase 2: stills --- SKIPPED")
    i_3 = out.find("--- Phase 3:")
    check("L45b Phase 1b sits after Phase 1 and before the SKIPPED banner and Phase 3",
          i_1 != -1 and i_1b != -1 and i_skip != -1 and i_3 != -1
          and i_1 < i_1b < i_skip < i_3,
          "i_1=%r i_1b=%r i_skip=%r i_3=%r" % (i_1, i_1b, i_skip, i_3))


def test_story_server_source_guards():
    story_server_path = os.path.join(WS, "bin", "story-server")
    check("L46a bin/story-server exists", os.path.isfile(story_server_path))
    check("L46b bin/story-server is executable", os.access(story_server_path, os.X_OK))
    with open(story_server_path) as f:
        first_line = f.readline()
    check("L46c bin/story-server's first line is #!/bin/bash", first_line == "#!/bin/bash\n",
          "got %r" % first_line)
    with open(_SCRIPT_PATH) as f:
        text = f.read()
    check("L46d bin/ltx-movie references story-server exactly twice",
          text.count('os.path.join(WS, "bin", "story-server")') == 2,
          "got %r" % text.count('os.path.join(WS, "bin", "story-server")'))
    check("L46e _render_flags(args) count is unchanged at 4",
          text.count("_render_flags(args)") == 4,
          "got %r occurrences" % text.count("_render_flags(args)"))
    check("L46f ltx-mlx-render path count is unchanged at 4",
          text.count('os.path.join(WS, "bin", "ltx-mlx-render")') == 4,
          "got %r" % text.count('os.path.join(WS, "bin", "ltx-mlx-render")'))


def _is_main_guard(test_node):
    return (isinstance(test_node, ast.Compare)
            and isinstance(test_node.left, ast.Name) and test_node.left.id == "__name__"
            and len(test_node.ops) == 1 and isinstance(test_node.ops[0], ast.Eq)
            and len(test_node.comparators) == 1
            and isinstance(test_node.comparators[0], ast.Constant)
            and test_node.comparators[0].value == "__main__")


def test_main_block_completeness():
    with open(__file__) as f:
        self_text = f.read()
    tree = ast.parse(self_text)

    top_level_tests = set(
        node.name for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name.startswith("test_")
    )

    main_calls = set()
    for node in tree.body:
        if isinstance(node, ast.If) and _is_main_guard(node.test):
            for stmt in node.body:
                for call in ast.walk(stmt):
                    if (isinstance(call, ast.Call) and isinstance(call.func, ast.Name)
                            and call.func.id.startswith("test_")):
                        main_calls.add(call.func.id)

    check("L47 every top-level test_* function is called from __main__",
          top_level_tests == main_calls,
          "diff: %r" % sorted(top_level_tests ^ main_calls))


if __name__ == "__main__":
    test_parser_defaults()
    test_render_flags_gemma_lora()
    test_stills_lora_reaches_phase2()
    test_story_model_reaches_phase1()
    test_story_context_window_reaches_phase1()
    test_removed_flags_rejected()
    test_dry_run_prints_phases_and_prompt()
    test_ast_guard_no_toplevel_heavy_imports()
    test_sudo_n_not_sudo_s()
    test_story_prompt_template()
    test_lock_state()
    test_validate_story_md_missing_motion()
    test_resolve_length_math()
    test_length_conflicts()
    test_length_too_short()
    test_length_100_panels_and_tokens()
    test_phase1_scaling()
    test_phase1_nonzero_rc_checks_story_md_before_failing()
    test_no_stills_default()
    test_no_stills_orthogonal_to_length()
    test_no_stills_story_prompt_template()
    test_validate_story_md_no_stills()
    test_no_stills_phase_sequencing_source()
    test_no_stills_dry_run_plan()
    test_default_dry_run_plan_unchanged()
    test_phase1_qwen_agent_gets_workspace_flag()
    test_top5_rss_skips_none_memory_info()
    test_dry_run_plan_targets_mlx_render()
    test_seed_prompt_preface()
    test_phase0_seed_image()
    test_seed_dry_run_plan()
    test_seed_no_stills_conflict()
    test_seed_source_guards()
    test_seed_postface_overrides_last()
    test_story_server_flag_default()
    test_phase_sequence_ordering()
    test_phase_release_story_server()
    test_dry_run_story_server_block_ordering()
    test_dry_run_no_story_server_block_with_opt_out()
    test_dry_run_story_server_block_with_no_stills()
    test_story_server_source_guards()
    test_seed_with_explicit_video_dims_rejected()
    test_video_dims_must_be_64_multiples()
    test_out_of_range_seed_fails_before_phase1()
    test_phase4_flags_policy_by_mode()
    test_main_block_completeness()

    print("OK %d/%d" % (TOTAL - FAILED, TOTAL))
    sys.exit(0 if FAILED == 0 else 1)
