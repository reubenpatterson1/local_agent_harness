#!/usr/bin/env python3
"""tests/mutate_deploy_pkg.py -- mutation harness for scripts/deploy (spec 15.3).

For each of the 12 mutations: copy scripts/deploy/{build_pkg.py, install_pkg.py,
credential_allowlist.json} and tests/test_deploy_pkg.py into a fresh temp dir with
the same relative layout, apply the (old, new) edits (every old must occur exactly
once and the mutated file must compile, else "ANCHOR <id>" and exit 2), run the
suite with pytest -x, and record caught (rc != 0) or SURVIVED. A no-edit control
must pass. Exit 0 iff 12/12 are caught and the control is ok.

    /Library/Frameworks/Python.framework/Versions/3.13/bin/python3 tests/mutate_deploy_pkg.py
"""
import os
import shutil
import subprocess
import sys
import tempfile

WS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BUILD = "scripts/deploy/build_pkg.py"
INSTALL = "scripts/deploy/install_pkg.py"
FILES = (BUILD, INSTALL, "scripts/deploy/credential_allowlist.json", "tests/test_deploy_pkg.py")
TIMEOUT = 600

MUTATIONS = (
    ("M1", BUILD, (('["token", "stored_tokens",', '["stored_tokens",'),)),
    ("M2", BUILD, (('self.tail = window[-self.keep:] if self.keep else b""', 'self.tail = b""'),)),
    ("M3", BUILD, (("    l4_rescan(ctx)", "    pass"),)),
    ("M4", BUILD, (("    results.append(check_offline_gates(ctx))\n", ""),
                   ("    copy_payload(ctx)\n", "    copy_payload(ctx)\n    check_offline_gates(ctx)\n"))),
    ("M5", INSTALL, (('    return CheckResult("I03", memsize >= MIN_MEMSIZE_BYTES, message, True)',
                      '    return CheckResult("I03", memsize >= MIN_MEMSIZE_BYTES, message, False)'),)),
    ("M6", BUILD, (("    if before_key != after_key:", "    if False:"),)),
    ("M7", INSTALL, (('    if digest != entry["h"]:', "    if False:"),)),
    ("M8", INSTALL, (("            collisions.append((target, reason))", "            pass"),)),
    ("M9", BUILD, (("    return (component, relpath, sha256, pattern_id) in allow",
                    "    return any(a[0] == component and a[1] == relpath and a[3] == pattern_id for a in allow)"),)),
    ("M10", INSTALL, (('glob.glob(os.path.join(VOLUMES_ROOT, "*", "hf_home"))', "[]"),)),
    ("M11", INSTALL, (("    if not args.apply:", "    if False:"),)),
    ("M12", INSTALL, (("    if fatal_failures:  # refuse --apply", "    if False:  # refuse --apply"),)),
)


def framework_py():
    return "/Library/Frameworks/Python.framework/Versions/3.13/bin/python3"


def make_copy():
    root = tempfile.mkdtemp(prefix="mutate-deploy-")
    for rel in FILES:
        dst = os.path.join(root, rel)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy2(os.path.join(WS, rel), dst)
    return root


def apply_edits(root, rel, edits):
    path = os.path.join(root, rel)
    with open(path, "r", encoding="utf-8") as fh:
        text = fh.read()
    for old, new in edits:
        if text.count(old) != 1:
            return False
        text = text.replace(old, new, 1)
    try:
        compile(text, path, "exec")
    except SyntaxError:
        return False
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)
    return True


def run_suite(root):
    env = dict(os.environ)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    argv = [framework_py(), "-m", "pytest", "-q", "-x", "-p", "no:cacheprovider",
            os.path.join(root, "tests", "test_deploy_pkg.py")]
    try:
        proc = subprocess.run(argv, cwd=root, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=TIMEOUT)
    except subprocess.TimeoutExpired:
        return 124
    return proc.returncode


def main():
    control_root = make_copy()
    try:
        control_ok = run_suite(control_root) == 0
    finally:
        shutil.rmtree(control_root, True)
    caught = 0
    for mutation_id, rel, edits in MUTATIONS:
        root = make_copy()
        try:
            if not apply_edits(root, rel, edits):
                print("ANCHOR %s" % mutation_id)
                return 2
            rc = run_suite(root)
        finally:
            shutil.rmtree(root, True)
        if rc != 0:
            caught += 1
            print("MUTATION %s caught" % mutation_id)
        else:
            print("MUTATION %s SURVIVED" % mutation_id)
        sys.stdout.flush()
    print("MUTANTS %d/%d CONTROL %s" % (caught, len(MUTATIONS), "ok" if control_ok else "FAIL"))
    return 0 if caught == len(MUTATIONS) and control_ok else 1


if __name__ == "__main__":
    sys.exit(main())
