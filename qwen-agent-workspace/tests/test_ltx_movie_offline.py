"""Plain-python (no pytest) offline tests for bin/ltx-movie.

Run: python3 tests/test_ltx_movie_offline.py
Prints PASS/FAIL per case, then "OK n/n" and exits 0, or exits 1 on any
failure. Offline only -- no sudo, no network, no calls into the real phase
tools except --dry-run-safe invocations of bin/ltx-movie itself (which
never shells out to the wrapped tools under --dry-run).
"""

import ast
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
    check("L1 frames == 241", args.frames == 241, "got %r" % args.frames)
    check("L1 fps == 24", args.fps == 24, "got %r" % args.fps)
    check("L1 image_width == 1280", args.image_width == 1280, "got %r" % args.image_width)
    check("L1 image_height == 704", args.image_height == 704, "got %r" % args.image_height)
    check("L1 video_width == 704", args.video_width == 704, "got %r" % args.video_width)
    check("L1 video_height == 448", args.video_height == 448, "got %r" % args.video_height)
    check("L1 image_seed == 0", args.image_seed == 0, "got %r" % args.image_seed)
    check("L1 panel_timeout == 7200", args.panel_timeout == 7200, "got %r" % args.panel_timeout)
    check("L1 model is the pack id",
          args.model == "MLXBits/ltx-2.3-10eros-v1.2-dmd-mlx-q8", "got %r" % args.model)
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


def test_removed_flags_rejected():
    for flag, value in (("--min-frames", "25"), ("--max-frames", "57"),
                        ("--target-seconds", "30"), ("--keep-down", None),
                        ("--reanchor-every", "3")):
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
    check("L2 stdout contains rendered 'Do not verify the file with run_python'",
          "Do not verify the file with run_python" in result.stdout,
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
    prompt = ltx_movie.build_story_prompt("some narrative", "some_id", 7)
    check("L5a prompt contains VERBATIM", "VERBATIM" in prompt)
    check("L5b prompt contains 'Do not verify'", "Do not verify" in prompt)
    check("L5c prompt formats panels count (7) in", prompt.count("7") >= 2)
    check("L5d Motion: line asks for 110-160 words", "110-160 words" in prompt,
          "got %r" % prompt)
    check("L5e Motion: line asks for a 7-10 sentence chronological paragraph",
          "one flowing paragraph of 7-10 sentences in strict chronological order" in prompt,
          "got %r" % prompt)
    check("L5f Motion: line forbids cuts and new plot info",
          "no cuts, no new plot information" in prompt, "got %r" % prompt)
    check("L5g Image: line is unchanged (70-90 words)", "70-90 words" in prompt)
    check("L5h Narration: line is unchanged",
          "Narration: <one sentence of voice-over narration; vary the sentence length "
          "across panels rather than repeating a similar length every time>" in prompt)
    check("L5i Motion: line demands enough beats to fill the ten seconds",
          "fill the full ten seconds instead of rushing the action" in prompt,
          "got %r" % prompt)
    check("L5j Motion: line no longer carries the old single-take framing",
          "ONE CONTINUOUS TEN-SECOND TAKE" not in prompt, "got %r" % prompt)
    check("L5k a style line bans abstract mood words",
          'never "she looks sad" or any other mood word' in prompt, "got %r" % prompt)
    check("L5l a style line bans scene-opener phrasing",
          'never open with "The scene opens with", "We see" or "There is"' in prompt,
          "got %r" % prompt)
    check("L5m Motion: bans restating appearance/wardrobe/setting/lighting from Image:",
          "Keep the setting, lighting and wardrobe consistent with the Image: field" not in prompt
          and "must not be described again in Motion:" in prompt, "got %r" % prompt)
    check("L5n Motion: line names the temporal connectors",
          '"initially", "as", "then", "while", "simultaneously", "a moment later"' in prompt,
          "got %r" % prompt)
    check("L5o Motion: line and style line both demand the present tense",
          prompt.count("in the present tense") >= 2, "got %r" % prompt)
    check("L5p Motion: line prescribes the LTX shot-type vocabulary",
          "extreme wide shot, wide shot, medium shot, medium close-up, close-up, "
          "extreme close-up" in prompt, "got %r" % prompt)
    check("L5q Motion: line prescribes the LTX camera-viewpoint vocabulary",
          "front-facing, back-facing, side view, over-the-shoulder, top-down, "
          "low-angle or high-angle" in prompt, "got %r" % prompt)
    check("L5r Motion: line always states camera motion",
          "if the camera holds, say that it remains static" in prompt, "got %r" % prompt)
    check("L5s a style line requires a soundscape and forbids dialogue",
          "Sound is part of the shot" in prompt
          and "write no spoken dialogue" in prompt, "got %r" % prompt)
    check("L5t the style paragraph comes last, after the VERBATIM paragraph",
          "Write the Motion: field in the present tense" in prompt and "VERBATIM" in prompt
          and prompt.index("Write the Motion: field in the present tense")
              > prompt.index("VERBATIM"), "got %r" % prompt)


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
        md_path = os.path.join(td, "story.md")
        with open(md_path, "w") as f:
            f.write(
                "# Story\n\n"
                "## Panel 1 — First\n"
                "Image: a scene one\n"
                "Motion: camera pans\n"
                "Narration: narration one\n\n"
                "## Panel 2 — Second\n"
                "Image: a scene two\n"
                "Narration: narration two\n"
            )
        violations = ltx_movie._validate_story_md(md_path, 2)
        check("L7 violations non-empty", len(violations) > 0, "got %r" % violations)
        found = any("panel 2" in v.lower() and "motion" in v.lower() for v in violations)
        check("L7 a violation names panel 2's missing Motion field", found,
              "violations=%r" % violations)


# ---------------------------------------------------------------------------
# L8 (addendum): --length 60 resolves to panels=30, target_seconds=60.0
# ---------------------------------------------------------------------------

def test_resolve_length_math():
    def _resolve(argv):
        args = ltx_movie.build_parser().parse_args(argv)
        ltx_movie._resolve_length(args, argv)
        return args.panels

    check("L8a --length 100 -> 10 panels (round(9.958))",
          _resolve(["n", "--story-id", "x", "--length", "100"]) == 10,
          "got %r" % _resolve(["n", "--story-id", "x", "--length", "100"]))
    check("L8b --length 20 -> 2 panels (round(1.992))",
          _resolve(["n", "--story-id", "x", "--length", "20"]) == 2,
          "got %r" % _resolve(["n", "--story-id", "x", "--length", "20"]))
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
         "--length", "15", "--dry-run"],
        capture_output=True, text=True, cwd=WS)
    check("L10a --length 15 exits 2", result.returncode == 2,
          "rc=%r stderr=%r" % (result.returncode, result.stderr))
    check("L10b the message names 10.04s per panel", "10.04s per panel" in result.stderr,
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
    check("L11b story prompt requests EXACTLY 10 panels", "EXACTLY 10" in result.stdout,
          "stdout=%r" % result.stdout[:2000])
    m = re.search(r"--max-tokens\s+(\d+)", result.stdout)
    check("L11c --max-tokens present", m is not None)
    if m:
        check("L11d --max-tokens is max(4096, 10*550) == 5500", int(m.group(1)) == 5500,
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
    check("L14b --length 100 resolves to 10 panels", plain == 10, "got %r" % plain)


# ---------------------------------------------------------------------------
# L15: the --no-stills story template (spec 9.1 item 3)
# ---------------------------------------------------------------------------

def test_no_stills_story_prompt_template():
    p = ltx_movie.build_story_prompt("some narrative", "some_id", 7, no_stills=True)
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
    check("L15m Prompt: line demands enough beats to fill the ten seconds",
          "fill the full ten seconds instead of rushing the action" in p, "got %r" % p[:900])
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
    check("L15y the style paragraph comes after the trailing Rules: block",
          "Write the Prompt: field in the present tense" in p
          and "Motion should focus on the actions" in p
          and p.index("Write the Prompt: field in the present tense")
              > p.rindex("Motion should focus on the actions"), "got %r" % p[:2400])
    check("L15r a style line bans scene-opener phrasing",
          'never open with "The scene opens with", "We see" or "There is"' in p,
          "got %r" % p[:900])
    check("L15i formats narrative/story_id/panels",
          "some narrative" in p and "some_id" in p and "EXACTLY 7 panel sections" in p)

    d = ltx_movie.build_story_prompt("some narrative", "some_id", 7)
    check("L15j the three-argument call is unchanged from today's template",
          d == ltx_movie.STORY_PROMPT_TEMPLATE.format(
              narrative="some narrative", story_id="some_id", panels=7))
    check("L15k no_stills=False is the same as the three-argument call",
          ltx_movie.build_story_prompt("some narrative", "some_id", 7, no_stills=False) == d)


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
    check("L17c phase 3 swaps --glob/--images-dir for --no-images",
          '"--no-images"' in text and '"--glob", "panel_*.png"' in text)
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
    check("L18l default plan carries the rewritten Motion: line",
          "Motion: <110-160 words in the present tense" in out
          and "ONE CONTINUOUS TEN-SECOND TAKE" not in out, "got %r" % out)


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
    check("L24d Phase 3 pins the manifest allocator to a flat 241 frames",
          "--min-frames 241 --max-frames 241" in out, "got %r" % out)
    check("L24e --target-seconds is computed as panels*frames/fps",
          "--target-seconds 30.125" in out, "got %r" % out)

    def _val(line, flag):
        t = line.split()
        return t[t.index(flag) + 1] if flag in t else None

    render_lines = [l for l in out.splitlines() if "ltx-mlx-render" in l]
    check("L24f exactly two ltx-mlx-render commands appear (Phase 3 probe, Phase 4 render)",
          len(render_lines) == 2, "got %r" % render_lines)
    for line in render_lines:
        for flag, want in (("--frames", "241"), ("--width", "704"), ("--height", "448"),
                           ("--frame-rate", "24"), ("--tile-frames", "1"),
                           ("--tile-spatial", "1")):
            check("L24f %r has %s %s" % (line.split()[0:2], flag, want),
                  _val(line, flag) == want,
                  "got %r in %r" % (_val(line, flag), line))
    check("L24g --resume is always passed", out.count("--resume") == 2, "got %r" % out)
    check("L24h --no-low-ram is absent by default", "--no-low-ram" not in out, "got %r" % out)
    check("L24i Phase 4 carries the failure policy",
          "--on-panel-failure skip" in out and "--retry-failed 1" in out
          and "--retry-idle 120" in out and "--max-consecutive-failures 3" in out
          and "--panel-timeout 7200" in out, "got %r" % out)
    check("L24j Phase 2 uses the new still resolution",
          "--width 1280" in out and "--height 704" in out, "got %r" % out)

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
    p_off = ltx_movie.build_story_prompt("n", "sid", 5)
    p_on = ltx_movie.build_story_prompt("n", "sid", 5, False, True)

    check("L25a unseeded (4-arg-equivalent) prompt is byte-identical to today's template",
          p_off == ltx_movie.STORY_PROMPT_TEMPLATE.format(narrative="n", story_id="sid", panels=5),
          "got %r" % p_off[:400])
    check("L25b preface sentence present only when seeded",
          "An image is attached to this message." in p_on
          and "An image is attached to this message." not in p_off)
    check("L25c seeded prompt starts with SEED_IMAGE_PREFACE",
          p_on.startswith(ltx_movie.SEED_IMAGE_PREFACE))
    check("L25d seeded prompt ends with the unseeded template appended intact",
          p_on.endswith(p_off))
    for phrase in (
        "Panel 1's still will NOT be rendered from your text",
        "faithful, literal description of that attached image",
        "not a generative prompt",
        "must stay visually consistent with what you actually observed",
    ):
        check("L25e preface contains %r" % phrase, phrase in p_on)
    check("L25f --no-stills wins over --seed-image",
          ltx_movie.build_story_prompt("n", "sid", 5, True, True)
          == ltx_movie.build_story_prompt("n", "sid", 5, True, False))


# ---------------------------------------------------------------------------
# L26: Phase 0 -- _downscale_seed_image and phase0_seed
# ---------------------------------------------------------------------------

def test_phase0_seed_image():
    from PIL import Image

    # Real tool defaults (--image-width/--image-height), used as target_width/
    # target_height in every _downscale_seed_image call below.
    tw, th = 1280, 704
    # Crop-to-fill always produces exactly tw x th first, so the subsequent long-edge
    # downscale (tw > SEED_DOWNSCALE_MAX_EDGE) always scales by the same factor,
    # regardless of the source's own size/aspect -- the whole point of the fix.
    _scale = ltx_movie.SEED_DOWNSCALE_MAX_EDGE / float(max(tw, th))
    expected_w = int(round(tw * _scale))
    expected_h = int(round(th * _scale))

    with tempfile.TemporaryDirectory() as tmp:
        out_path = os.path.join(tmp, "out.png")

        missing = os.path.join(tmp, "missing.png")
        v = ltx_movie._downscale_seed_image(missing, out_path, tw, th)
        check("L26a missing file -> violation names 'not found'",
              any("not found" in s for s in v), "got %r" % v)
        check("L26a missing file -> output not created", not os.path.exists(out_path))

        junk = os.path.join(tmp, "junk.png")
        with open(junk, "w") as f:
            f.write("not a real image xx")
        v = ltx_movie._downscale_seed_image(junk, out_path, tw, th)
        check("L26b unreadable file -> violation names 'not a readable image'",
              any("not a readable image" in s for s in v), "got %r" % v)

        tiny = os.path.join(tmp, "tiny.png")
        Image.new("RGB", (32, 32), (1, 2, 3)).save(tiny, format="PNG")
        v = ltx_movie._downscale_seed_image(tiny, out_path, tw, th)
        check("L26c 32x32 -> violation names 'degenerate' and '32x32'",
              any("degenerate" in s and "32x32" in s for s in v), "got %r" % v)

        big = os.path.join(tmp, "big.png")
        Image.new("RGB", (4000, 3000), (4, 5, 6)).save(big, format="PNG")
        v = ltx_movie._downscale_seed_image(big, out_path, tw, th)
        check("L26d 4000x3000 -> no violations", v == [], "got %r" % v)
        with Image.open(out_path) as img:
            w, h = img.size
            check("L26d output long edge == SEED_DOWNSCALE_MAX_EDGE",
                  max(w, h) == ltx_movie.SEED_DOWNSCALE_MAX_EDGE, "got %r" % (img.size,))
            check("L26d output aspect matches target (crop-to-fill, not source 4:3)",
                  abs(w / h - tw / float(th)) < 0.01, "got %r" % (img.size,))
            check("L26d output format is PNG", img.format == "PNG", "got %r" % img.format)

        under_cap = os.path.join(tmp, "under.png")
        Image.new("RGB", (800, 600), (7, 8, 9)).save(under_cap, format="PNG")
        v = ltx_movie._downscale_seed_image(under_cap, out_path, tw, th)
        check("L26e 800x600 (under the cap) -> no violations", v == [], "got %r" % v)
        with Image.open(out_path) as img:
            check("L26e size is crop-to-fill then downscale, not source size unchanged",
                  img.size == (expected_w, expected_h), "got %r" % (img.size,))

        at_cap = os.path.join(tmp, "at_cap.png")
        Image.new("RGB", (1024, 1024), (10, 11, 12)).save(at_cap, format="PNG")
        v = ltx_movie._downscale_seed_image(at_cap, out_path, tw, th)
        check("L26f 1024x1024 (exactly at the cap) -> no violations", v == [], "got %r" % v)
        with Image.open(out_path) as img:
            check("L26f size is crop-to-fill then downscale, not the source's 1024x1024",
                  img.size == (expected_w, expected_h), "got %r" % (img.size,))

        rgba = os.path.join(tmp, "rgba.png")
        Image.new("RGBA", (200, 200), (1, 2, 3, 128)).save(rgba, format="PNG")
        v = ltx_movie._downscale_seed_image(rgba, out_path, tw, th)
        check("L26g RGBA input -> no violations", v == [], "got %r" % v)
        with Image.open(out_path) as img:
            check("L26g output mode is RGB", img.mode == "RGB", "got %r" % img.mode)

        # L26j: bin/ltx-movie's _crop_to_fill and bin/ltx-story-images's
        # _resize_center_crop must produce pixel-identical output for the same source
        # and target size -- Phase 1 must see exactly the framing that becomes
        # panel_01.png. Marker-image technique mirrors
        # tests/test_ltx_story_images.py's test_resize_center_crop_geometry.
        marker_src = Image.new("RGB", (900, 600), (255, 0, 0))
        from PIL import ImageDraw
        draw = ImageDraw.Draw(marker_src)
        cx, cy, half = 900 / 2.0, 600 / 2.0, 60 / 2.0
        left = int(round(cx - half))
        top = int(round(cy - half))
        draw.rectangle([left, top, left + 60 - 1, top + 60 - 1], fill=(0, 0, 0))
        movie_out = ltx_movie._crop_to_fill(marker_src, tw, th)
        images_out = ltx_story_images._resize_center_crop(marker_src, tw, th)
        check("L26j crop-to-fill output sizes match", movie_out.size == images_out.size,
              "got %r vs %r" % (movie_out.size, images_out.size))
        check("L26j bin/ltx-movie and bin/ltx-story-images crop pixel-identically",
              list(movie_out.getdata()) == list(images_out.getdata()))

    # phase0_seed end-to-end, with a throwaway story-id, cleaned up in a finally block.
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
            check("L26h phase0_seed returns 0 for a valid seed", rc == 0, "got %r" % rc)
            check("L26h args.seed_downscaled_path is set to the expected path",
                  getattr(args, "seed_downscaled_path", None) == expected_path,
                  "got %r" % getattr(args, "seed_downscaled_path", None))

            missing_seed = os.path.join(tmp, "does_not_exist.png")
            args2 = ltx_movie.build_parser().parse_args(
                ["n", "--story-id", story_id, "--seed-image", missing_seed])
            rc2 = ltx_movie.phase0_seed(args2)
            check("L26i phase0_seed returns 2 for a missing seed", rc2 == 2, "got %r" % rc2)
    finally:
        shutil.rmtree(story_dir, ignore_errors=True)


# ---------------------------------------------------------------------------
# L27: --seed-image --dry-run plan
# ---------------------------------------------------------------------------

def test_seed_dry_run_plan():
    missing = "/nonexistent/seed_for_test.png"
    result = subprocess.run(
        [sys.executable, _SCRIPT_PATH, "a narrative", "--story-id", "unittest-seed",
         "--panels", "3", "--seed-image", missing, "--dry-run"],
        capture_output=True, text=True, cwd=WS)
    out = result.stdout
    check("L27a exits 0 (dry-run never opens the seed file itself)",
          result.returncode == 0, "rc=%r stderr=%r" % (result.returncode, result.stderr))
    check("L27b stdout contains a Phase 0 block", "--- Phase 0: seed image ---" in out,
          "got %r" % out[:1500])

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
        check("L27d phase-2 command carries --seed-image with the ORIGINAL path",
              ("--seed-image " + missing) in phase2_lines[0], "got %r" % phase2_lines[0])
        check("L27d phase-2 command does not carry the downscaled path",
              "seed_downscaled" not in phase2_lines[0], "got %r" % phase2_lines[0])
        check("L27f --seed-image appears exactly once in the ltx-story-images command line",
              phase2_lines[0].count("--seed-image") == 1, "got %r" % phase2_lines[0])

    check("L27e rendered prompt preview contains the preface sentence",
          "An image is attached to this message." in out, "got %r" % out[-2000:])

    plain = subprocess.run(
        [sys.executable, _SCRIPT_PATH, "a narrative", "--story-id", "unittest-seed-off",
         "--panels", "3", "--dry-run"],
        capture_output=True, text=True, cwd=WS)
    check("L27g non-seeded dry-run prints no Phase 0", "Phase 0" not in plain.stdout,
          "got %r" % plain.stdout[:800])
    check("L27h non-seeded dry-run has no --image flag", "--image " not in plain.stdout,
          "got %r" % plain.stdout)
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

    pil_in_func = False
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for sub in ast.walk(node):
                if isinstance(sub, ast.ImportFrom) and sub.module == "PIL":
                    pil_in_func = True
    check("L29b PIL is imported, but only inside a function body (mirrors the "
          "existing psutil guard pattern)", pil_in_func)

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


if __name__ == "__main__":
    test_parser_defaults()
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

    print("OK %d/%d" % (TOTAL - FAILED, TOTAL))
    sys.exit(0 if FAILED == 0 else 1)
