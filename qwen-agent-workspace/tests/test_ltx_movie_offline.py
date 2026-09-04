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

    print("OK %d/%d" % (TOTAL - FAILED, TOTAL))
    sys.exit(0 if FAILED == 0 else 1)
