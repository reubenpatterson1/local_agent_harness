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
import subprocess
import sys
import tempfile
import importlib.machinery

WS = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
sys.path.insert(0, WS)

_SCRIPT_PATH = os.path.join(WS, "bin", "ltx-movie")
ltx_movie = importlib.machinery.SourceFileLoader("ltx_movie", _SCRIPT_PATH).load_module()

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
    check("L1 target_seconds == 30.0", args.target_seconds == 30.0, "got %r" % args.target_seconds)
    check("L1 fps == 24", args.fps == 24, "got %r" % args.fps)
    check("L1 min_frames == 25", args.min_frames == 25, "got %r" % args.min_frames)
    check("L1 max_frames == 57", args.max_frames == 57, "got %r" % args.max_frames)
    check("L1 image_width == 1024", args.image_width == 1024, "got %r" % args.image_width)
    check("L1 image_height == 1024", args.image_height == 1024, "got %r" % args.image_height)
    check("L1 image_seed == 0", args.image_seed == 0, "got %r" % args.image_seed)
    check("L1 min_avail_gib == 34.0", args.min_avail_gib == 34.0, "got %r" % args.min_avail_gib)
    check("L1 avail_timeout == 1800", args.avail_timeout == 1800, "got %r" % args.avail_timeout)
    check("L1 no_review is False", args.no_review is False, "got %r" % args.no_review)
    check("L1 force_story is False", args.force_story is False, "got %r" % args.force_story)
    check("L1 force is False", args.force is False, "got %r" % args.force)
    check("L1 dry_run is False", args.dry_run is False, "got %r" % args.dry_run)
    check("L1 length is None", args.length is None, "got %r" % args.length)


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
    check("L5 prompt contains VERBATIM", "VERBATIM" in prompt)
    check("L5 prompt contains 'Do not verify'", "Do not verify" in prompt)
    check("L5 prompt formats panels count (7) in", prompt.count("7") >= 2,
          "prompt=%r" % prompt)


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

def test_resolve_length_60():
    raw_argv = ["narrative text", "--story-id", "x", "--length", "60"]
    args = ltx_movie.build_parser().parse_args(raw_argv)
    ltx_movie._resolve_length(args, raw_argv)
    check("L8 --length 60 -> panels == 30", args.panels == 30, "got %r" % args.panels)
    check("L8 --length 60 -> target_seconds == 60.0", args.target_seconds == 60.0,
          "got %r" % args.target_seconds)


# ---------------------------------------------------------------------------
# L9 (addendum): --length conflicts with --panels / --target-seconds
# ---------------------------------------------------------------------------

def test_length_conflicts():
    result = subprocess.run(
        [sys.executable, _SCRIPT_PATH, "narrative", "--story-id", "x",
         "--length", "60", "--panels", "20", "--dry-run"],
        capture_output=True, text=True, cwd=WS,
    )
    check("L9 --length+--panels exits 2", result.returncode == 2, "rc=%r" % result.returncode)
    check("L9 --length+--panels stderr names --panels", "--panels" in result.stderr,
          "stderr=%r" % result.stderr)

    result = subprocess.run(
        [sys.executable, _SCRIPT_PATH, "narrative", "--story-id", "x",
         "--length", "60", "--target-seconds", "30", "--dry-run"],
        capture_output=True, text=True, cwd=WS,
    )
    check("L9 --length+--target-seconds exits 2", result.returncode == 2, "rc=%r" % result.returncode)
    check("L9 --length+--target-seconds stderr names --target-seconds",
          "--target-seconds" in result.stderr, "stderr=%r" % result.stderr)


# ---------------------------------------------------------------------------
# L10 (addendum): --length too short, and --length exceeding the frame cap
# ---------------------------------------------------------------------------

def test_length_bounds():
    result = subprocess.run(
        [sys.executable, _SCRIPT_PATH, "narrative", "--story-id", "x",
         "--length", "3", "--dry-run"],
        capture_output=True, text=True, cwd=WS,
    )
    check("L10 --length 3 (too short) exits 2", result.returncode == 2,
          "rc=%r stderr=%r" % (result.returncode, result.stderr))

    result = subprocess.run(
        [sys.executable, _SCRIPT_PATH, "narrative", "--story-id", "x",
         "--length", "90", "--dry-run"],
        capture_output=True, text=True, cwd=WS,
    )
    check("L10 --length 90 @ fps 24 (over frame cap) exits 2", result.returncode == 2,
          "rc=%r stderr=%r" % (result.returncode, result.stderr))
    check("L10 --length 90 stderr names the frame cap",
          ("2000-frame" in result.stderr) or ("concat cap" in result.stderr),
          "stderr=%r" % result.stderr)


# ---------------------------------------------------------------------------
# L11 (addendum): --length 40 -> 20 panels requested, --max-tokens >= 7000
# ---------------------------------------------------------------------------

def test_length_40_panels_and_tokens():
    result = subprocess.run(
        [sys.executable, _SCRIPT_PATH, "narrative", "--story-id", "x",
         "--length", "40", "--dry-run"],
        capture_output=True, text=True, cwd=WS,
    )
    check("L11 --length 40 exits 0", result.returncode == 0,
          "rc=%r stderr=%r" % (result.returncode, result.stderr))
    check("L11 story prompt requests EXACTLY 20 panels", "EXACTLY 20" in result.stdout,
          "stdout=%r" % result.stdout[:2000])
    m = re.search(r"--max-tokens\s+(\d+)", result.stdout)
    check("L11 --max-tokens present in dry-run output", m is not None,
          "stdout=%r" % result.stdout[:2000])
    if m:
        check("L11 --max-tokens >= 7000", int(m.group(1)) >= 7000, "got %s" % m.group(1))


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
# L13: --no-stills / --reanchor-every defaults and validation
# ---------------------------------------------------------------------------

def test_no_stills_defaults_and_validation():
    args = ltx_movie.build_parser().parse_args(["narrative", "--story-id", "x"])
    check("L13a --no-stills default is False", args.no_stills is False,
          "got %r" % args.no_stills)
    check("L13b --reanchor-every default is 5", args.reanchor_every == 5,
          "got %r" % args.reanchor_every)

    result = subprocess.run(
        [sys.executable, _SCRIPT_PATH, "narrative", "--story-id", "x",
         "--reanchor-every", "3", "--dry-run"],
        capture_output=True, text=True, cwd=WS,
    )
    check("L13c --reanchor-every without --no-stills exits 2", result.returncode == 2,
          "rc=%r" % result.returncode)
    check("L13d message is the spec's verbatim text",
          "Error: --reanchor-every requires --no-stills (it only applies to the "
          "chain engine)" in result.stderr, "stderr=%r" % result.stderr)

    result = subprocess.run(
        [sys.executable, _SCRIPT_PATH, "narrative", "--story-id", "x",
         "--no-stills", "--reanchor-every", "0", "--dry-run"],
        capture_output=True, text=True, cwd=WS,
    )
    check("L13e --reanchor-every 0 exits 2", result.returncode == 2,
          "rc=%r" % result.returncode)
    check("L13f message names the >= 1 rule",
          "Error: --reanchor-every must be >= 1, got 0" in result.stderr,
          "stderr=%r" % result.stderr)


# ---------------------------------------------------------------------------
# L14: --no-stills is orthogonal to --length (spec 9.1 item 6)
# ---------------------------------------------------------------------------

def test_no_stills_orthogonal_to_length():
    def _resolve(argv):
        args = ltx_movie.build_parser().parse_args(argv)
        ltx_movie._resolve_length(args, argv)
        return args.panels, args.target_seconds

    plain = _resolve(["narrative", "--story-id", "x", "--length", "30"])
    with_flag = _resolve(["narrative", "--story-id", "x", "--no-stills", "--length", "30"])
    check("L14a --no-stills does not change --length resolution", plain == with_flag,
          "got %r vs %r" % (plain, with_flag))
    check("L14b --length 30 still resolves to (15, 30.0)", plain == (15, 30.0),
          "got %r" % (plain,))


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
    check("L15h word band is 85-130", "85-130 words" in p)
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
    check("L17d phase 3/4 thread --engine chain",
          text.count('"--engine", "chain", "--reanchor-every", str(args.reanchor_every)') >= 4,
          "got %r occurrences" % text.count(
              '"--engine", "chain", "--reanchor-every", str(args.reanchor_every)'))


# ---------------------------------------------------------------------------
# L18: --no-stills --dry-run plan (spec 9.1 item 5, criterion 2)
# ---------------------------------------------------------------------------

def test_no_stills_dry_run_plan():
    result = subprocess.run(
        [sys.executable, _SCRIPT_PATH, "a narrative", "--story-id", "unittest-nostills",
         "--no-stills", "--panels", "6", "--reanchor-every", "3", "--dry-run"],
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
    check("L18f the chain flags appear", "--engine chain" in out
          and "--reanchor-every 3" in out, "got %r" % out)
    check("L18g the rendered prompt is the no-stills template",
          "Prompt: <a single video prompt, 85-130 words" in out
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
# L21: dynamic --min-frames/--max-frames (derived from target seconds/panel,
# snapped to the n=1+8k lattice, clamped against ltx_ceiling.json's
# measured 512x512 entry)
# ---------------------------------------------------------------------------

def test_dynamic_frame_bounds_default_2s_per_panel():
    result = ltx_movie._dynamic_frame_bounds(30.0, 15, 24)
    check("L21a default (2s/panel) result", result == (25, 73, False, 2.0, 48.0),
          "got %r" % (result,))


def test_dynamic_frame_bounds_clamped_by_ceiling():
    result = ltx_movie._dynamic_frame_bounds(30.0, 6, 24)
    check("L21b 5s/panel clamps max to the 512x512 ceiling (73)",
          result == (57, 73, True, 5.0, 120.0), "got %r" % (result,))


def test_dynamic_frame_bounds_tiny_target_floors_at_9():
    result = ltx_movie._dynamic_frame_bounds(6.0, 30, 24)
    min_frames, max_frames, ceiling_clamped, seconds_per_panel, target_frames_per_panel = result
    check("L21c tiny target floors both bounds at 9, no clamp",
          (min_frames, max_frames, ceiling_clamped) == (9, 9, False), "got %r" % (result,))
    check("L21c seconds_per_panel == 0.2",
          abs(seconds_per_panel - 0.2) < 1e-9, "got %r" % (seconds_per_panel,))
    check("L21c target_frames_per_panel ~= 4.8 (float non-associativity, not exact)",
          abs(target_frames_per_panel - 4.8) < 1e-9, "got %r" % (target_frames_per_panel,))


def test_dynamic_frame_bounds_infeasible_clamp_exits():
    try:
        ltx_movie._dynamic_frame_bounds(40.0, 5, 24)
        check("L21d infeasible clamp raises SystemExit", False, "did not raise")
    except SystemExit as e:
        check("L21d infeasible clamp raises SystemExit(2)", e.code == 2, "got code=%r" % e.code)


def test_dynamic_frame_bounds_dry_run_banner():
    result = subprocess.run(
        [sys.executable, _SCRIPT_PATH, "a narrative", "--story-id", "unittest-dynamic",
         "--panels", "6", "--dry-run"],
        capture_output=True, text=True, cwd=WS,
    )
    out = result.stdout
    check("L21e exits 0", result.returncode == 0, "rc=%r stderr=%r" % (result.returncode,
                                                                       result.stderr))
    check("L21f banner printed", "Dynamic frame bounds:" in out, "got %r" % out)
    check("L21g banner shows min=57", "min=57" in out, "got %r" % out)
    check("L21h banner shows max=73", "max=73" in out, "got %r" % out)
    check("L21i banner notes the ceiling clamp",
          "[clamped to measured 512x512 ceiling]" in out, "got %r" % out)
    check("L21j Phase 3 manifest command uses the computed bounds",
          "--min-frames 57" in out and "--max-frames 73" in out, "got %r" % out)


def test_dynamic_frame_bounds_explicit_min_disables_both():
    result = subprocess.run(
        [sys.executable, _SCRIPT_PATH, "a narrative", "--story-id", "unittest-explicit",
         "--panels", "6", "--min-frames", "41", "--dry-run"],
        capture_output=True, text=True, cwd=WS,
    )
    out = result.stdout
    check("L21k exits 0", result.returncode == 0, "rc=%r stderr=%r" % (result.returncode,
                                                                       result.stderr))
    check("L21l no dynamic banner when --min-frames is explicit",
          "Dynamic frame bounds:" not in out, "got %r" % out)
    check("L21m explicit --min-frames 41 passed through unchanged",
          "--min-frames 41" in out, "got %r" % out)
    check("L21n --max-frames falls back to its static default (57), not computed",
          "--max-frames 57" in out, "got %r" % out)


if __name__ == "__main__":
    test_parser_defaults()
    test_dry_run_prints_phases_and_prompt()
    test_ast_guard_no_toplevel_heavy_imports()
    test_sudo_n_not_sudo_s()
    test_story_prompt_template()
    test_lock_state()
    test_validate_story_md_missing_motion()
    test_resolve_length_60()
    test_length_conflicts()
    test_length_bounds()
    test_length_40_panels_and_tokens()
    test_phase1_nonzero_rc_checks_story_md_before_failing()
    test_no_stills_defaults_and_validation()
    test_no_stills_orthogonal_to_length()
    test_no_stills_story_prompt_template()
    test_validate_story_md_no_stills()
    test_no_stills_phase_sequencing_source()
    test_no_stills_dry_run_plan()
    test_default_dry_run_plan_unchanged()
    test_phase1_qwen_agent_gets_workspace_flag()
    test_top5_rss_skips_none_memory_info()
    test_dynamic_frame_bounds_default_2s_per_panel()
    test_dynamic_frame_bounds_clamped_by_ceiling()
    test_dynamic_frame_bounds_tiny_target_floors_at_9()
    test_dynamic_frame_bounds_infeasible_clamp_exits()
    test_dynamic_frame_bounds_dry_run_banner()
    test_dynamic_frame_bounds_explicit_min_disables_both()

    print("OK %d/%d" % (TOTAL - FAILED, TOTAL))
    sys.exit(0 if FAILED == 0 else 1)
