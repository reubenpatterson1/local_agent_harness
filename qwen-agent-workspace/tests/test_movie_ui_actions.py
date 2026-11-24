"""movie-ui action (motion LoRA) support: the Compose action_loras field, its --action argv,
the bin/action create/train job argv, and the Actions tab's list parsing and field rules.

Bulk action clips (docs/superpowers/specs/2026-11-23-bulk-action-clips-design.md, Section 6.2:
BKT13-BKT18, plus the plan's Review Focus 3-5): the folder field, POST /api/actions/preview, the
natural clip order and the page. The HTTP tests run an in-test movie-ui server on 127.0.0.1 under a
temporary HOME with a stub workspace; the real bin/action and action_lib.py are copied into it
where a test needs them, and no job is ever dispatched.
"""

import os
import re
import shutil
import subprocess
import sys

import pytest

import movie_ui_testutil as mt  # noqa: F401  (puts the workspace on sys.path)
import action_lib as al
import movie_ui_lib as lib
import movie_ui_server as srv

DESC = "a spinning kick delivered with the rear leg to head height in one motion"
TRIGGER = "performs a fight combo"
VIDEO_REASON = "not a video (.mp4, .mov, .m4v, .webm, .mkv)"
MOTION_MESSAGE = "trigger must be a Motion: phrase of 1-40 letters, digits, spaces, _ ' or -"
PREVIEW_ROUTE = ("POST", r"/api/actions/preview", "h_action_preview", "/api/actions/preview")


@pytest.fixture
def env(monkeypatch, tmp_path):
    monkeypatch.setenv("ACTION_LIBRARY_DIR", str(tmp_path / "actions"))
    state = mt.set_home(monkeypatch, tmp_path)
    ws = mt.make_stub_workspace(tmp_path)
    running = mt.Running(state)
    yield {"state": state, "ws": ws, "tmp": os.path.realpath(str(tmp_path)), "srv": running}
    running.close()
    mt.kill_everything(state)


def _real_action_tool(ws):
    """The real bin/action and action_lib.py in the stub workspace (scan and show run for real)."""
    shutil.copy2(os.path.join(mt.WS, "bin", "action"), os.path.join(ws, "bin", "action"))
    shutil.copy2(os.path.join(mt.WS, "action_lib.py"), os.path.join(ws, "action_lib.py"))


def _folder(tmp, names):
    """<tmp>/clips holding a zero-byte file for each name."""
    d = os.path.join(tmp, "clips")
    os.makedirs(d)
    for name in names:
        open(os.path.join(d, name), "wb").close()
    return d


def _job(state, payload):
    return lib.read_job(lib.job_dir(state, payload["job"]["id"]))


def _write_action(tmp, name, sources, clips):
    """<tmp>/actions/<name>/action.json (status dataset) and `clips` empty dataset clip files."""
    adir = os.path.join(tmp, "actions", name)
    clips_dir = os.path.join(adir, "dataset", "clips")
    os.makedirs(clips_dir)
    data = al.new_action(name, "performs a roundhouse kick", DESC, sources)
    data["dataset"] = {"clips": clips, "performers": 3, "width": 768, "height": 768, "frames": 97, "fps": 24,
                       "contact_sheet": os.path.join(adir, "dataset", "contact_sheet.jpg")}
    al.write_action(data)
    for i in range(clips):
        open(os.path.join(clips_dir, "clip_%02d.mp4" % i), "wb").close()
    return clips_dir


def test_action_loras_argv_and_rules(tmp_path):
    fields = lib.compose_fields({"narrative": "A kick.", "story_id": "x", "action_loras": [
        {"name": "roundhouse-kick", "strength": 0.55}, {"name": "straight-punch", "strength": None}]})
    argv = lib.build_argv(fields, "/ws", str(tmp_path), py="py")
    i = argv.index("--action")
    assert argv[i:i + 4] == ["--action", "roundhouse-kick:0.55", "--action", "straight-punch"]
    assert "--action" not in lib.build_argv(lib.compose_fields({"narrative": "A", "story_id": "x"}),
                                            "/ws", str(tmp_path), py="py")
    assert lib._rule_actions(fields) == []
    assert lib._rule_actions({"action_loras": [{"name": "Bad Name"}]}) == [
        "action 1: name must match [a-z][a-z0-9-]{1,31}"]
    assert lib._rule_actions({"action_loras": [{"name": "kick", "strength": 3}]}) == [
        "action kick: strength must satisfy 0 < s <= 2"]
    assert lib._rule_actions({"action_loras": [{"name": "kick"}, {"name": "kick"}]}) == [
        "actions must be distinct"]
    assert lib._rule_actions({"action_loras": "kick"}) == ["action_loras must be a list of at most 8 actions"]


def test_action_job_argv():
    fields = {"name": "roundhouse-kick", "trigger": "performs a roundhouse kick", "descriptor": DESC,
              "clips": ["/c/a.mp4", "/c/b.mp4"], "performers": 3, "force": False, "regenerate": True}
    assert lib.action_argv("action-create", fields, "/ws", py="py") == [
        "py", "/ws/bin/action", "create", "roundhouse-kick", "--trigger", "performs a roundhouse kick",
        "--descriptor", DESC, "--clip", "/c/a.mp4", "--clip", "/c/b.mp4", "--performers", "3", "--regenerate"]
    assert lib.action_argv("action-train", {"name": "roundhouse-kick"}, "/ws", py="py") == [
        "/ws/bin/action-train-vlm", "py", "roundhouse-kick"]


def test_parse_action_list():
    out = ("name                     status     clips  trigger\n"
           "roundhouse-kick          trained    12     performs a roundhouse kick\n"
           "jab                      dataset    -      throws a jab\n"
           "broken                   INVALID: action.json: bad key\n")
    assert srv.parse_action_list(out) == [
        {"name": "roundhouse-kick", "status": "trained", "clips": 12, "trigger": "performs a roundhouse kick",
         "invalid": None},
        {"name": "jab", "status": "dataset", "clips": None, "trigger": "throws a jab", "invalid": None},
        {"name": "broken", "invalid": "action.json: bad key"}]
    assert srv.parse_action_list("(no actions)\n") == []


def test_action_create_errors(tmp_path):
    clip = tmp_path / "kick_01.mp4"
    clip.write_bytes(b"x")
    good = {"name": "roundhouse-kick", "trigger": "performs a roundhouse kick", "descriptor": DESC,
            "clips": [str(clip)], "performers": 3}
    assert srv.action_create_errors(good) == []
    bad = dict(good, name="X", trigger="-", descriptor="too short", performers=-1, force="yes",
               clips=[str(tmp_path / "missing.mp4"), "rel.mp4", str(tmp_path / "notes.txt")])
    assert srv.action_create_errors(bad) == [
        "action name must match [a-z][a-z0-9-]{1,31}",
        "trigger must be a Motion: phrase of 1-40 letters, digits, spaces, _ ' or -",
        "descriptor must be 8 to 60 words",
        "clip %s not found" % os.path.join(str(tmp_path), "missing.mp4"),
        "clip rel.mp4 must be an absolute path",
        "clip %s is not a video (.mp4, .mov, .m4v, .webm, .mkv)" % os.path.join(str(tmp_path), "notes.txt"),
        "performers must be an integer >= 0",
        "force must be true or false"]
    assert srv.action_create_errors(dict(good, clips=[])) == ["give 1 to 64 clip paths"]


# --- BKT13-BKT18: bulk action clips ------------------------------------------------------------

def test_bkt13_action_argv_with_a_folder():
    fields = {"name": "roundhouse-kick", "trigger": "performs a roundhouse kick", "descriptor": DESC,
              "dir": "/c", "performers": 3, "force": False, "regenerate": False}
    assert lib.action_argv("action-create", fields, "/ws", py="py") == [
        "py", "/ws/bin/action", "create", "roundhouse-kick", "--trigger", "performs a roundhouse kick",
        "--descriptor", DESC, "--dir", "/c", "--performers", "3"]
    assert lib.action_argv("action-create", dict(fields, regenerate=True), "/ws", py="py")[-5:] == [
        "--dir", "/c", "--performers", "3", "--regenerate"]
    assert lib.action_argv("action-create", dict(fields, dir=None, clips=["/c/a.mp4"]), "/ws", py="py")[8:12] == [
        "--clip", "/c/a.mp4", "--performers", "3"]


def test_bkt14_action_create_errors_folder_mode(tmp_path):
    folder = os.path.realpath(str(tmp_path))
    good = {"name": "roundhouse-kick", "trigger": "performs a roundhouse kick", "descriptor": DESC,
            "dir": folder, "performers": 3}
    assert srv.action_create_errors(good) == []
    clip = os.path.join(folder, "kick_01.mp4")
    open(clip, "wb").close()
    assert srv.action_create_errors(dict(good, clips=[clip])) == ["give either clip paths or a folder, not both"]
    assert srv.action_create_errors(dict(good, dir="rel/dir")) == ["folder must be an absolute path"]
    assert srv.action_create_errors(dict(good, dir=5)) == ["folder must be an absolute path"]
    assert srv.action_create_errors(dict(good, dir=folder + "/../x")) == ["folder must not contain '..'"]
    missing = os.path.join(folder, "missing")
    assert srv.action_create_errors(dict(good, dir=missing)) == ["folder %s not found" % missing]
    assert srv.action_create_errors(dict(good, dir=clip)) == ["folder %s not found" % clip]
    locked = os.path.join(folder, "locked")
    os.mkdir(locked)
    os.chmod(locked, 0)
    try:
        if os.geteuid() != 0:
            assert srv.action_create_errors(dict(good, dir=locked)) == ["folder %s is not readable" % locked]
    finally:
        os.chmod(locked, 0o755)
    assert srv.action_create_errors(dict(good, name="X", dir="rel", performers=-1)) == [
        "action name must match [a-z][a-z0-9-]{1,31}", "folder must be an absolute path",
        "performers must be an integer >= 0"]
    assert srv.action_create_errors(dict(good, dir=None, clips=[clip])) == []
    assert srv.action_dir_errors(folder) == []


def test_bkt15_preview_over_http(env):
    s, ws, state = env["srv"], env["ws"], env["state"]
    routes = list(srv.ROUTES)
    i = routes.index(("POST", r"/api/actions", "h_action_create", "/api/actions"))
    assert routes[i + 1] == PREVIEW_ROUTE
    assert srv.MovieUIHandler.h_action_preview is srv._h_action_preview
    _real_action_tool(ws)
    d = _folder(env["tmp"], ["001_00_kick.mp4", "002_00_punch-high_kick.mp4", "notes.txt"])
    status, _h, data = mt.api(s, "POST", "/api/actions/preview", body={"ws": ws, "dir": d, "trigger": TRIGGER})
    assert status == 200, data
    assert data == {"dir": d, "matched": 2, "max": 1000, "clips": [
        {"name": "001_00_kick.mp4", "path": os.path.join(d, "001_00_kick.mp4"), "moves": ["kick"],
         "caption": "performs a fight combo: kick"},
        {"name": "002_00_punch-high_kick.mp4", "path": os.path.join(d, "002_00_punch-high_kick.mp4"),
         "moves": ["punch", "high kick"], "caption": "performs a fight combo: punch, then high kick"}],
        "skipped": [{"name": "notes.txt", "reason": VIDEO_REASON}]}
    status, _h, data = mt.api(s, "POST", "/api/actions/preview", body={"ws": ws, "dir": d})
    assert status == 200 and [c["caption"] for c in data["clips"]] == [None, None]
    assert mt.api(s, "POST", "/api/actions/preview", body={"ws": ws, "dir": "rel"})[::2] == (
        400, {"error": "invalid fields", "errors": ["folder must be an absolute path"]})
    assert mt.api(s, "POST", "/api/actions/preview", body={"ws": ws, "dir": d, "trigger": "bad:x"})[::2] == (
        400, {"error": "invalid fields", "errors": [MOTION_MESSAGE]})
    assert mt.api(s, "POST", "/api/actions/preview", body={"ws": ws, "dir": d, "trigger": 5})[::2] == (
        400, {"error": "invalid fields", "errors": ["trigger must be a string"]})
    assert lib.read_queue(state) == [] and lib.list_job_ids(state) == []
    for token in (None, "wrong-token"):
        assert mt.api(s, "POST", "/api/actions/preview", body={"ws": ws, "dir": d}, token=token)[::2] == (
            401, {"error": "missing or invalid token"})


def test_bkt16_create_with_a_folder_over_http(env):
    s, ws, state = env["srv"], env["ws"], env["state"]
    d = _folder(env["tmp"], ["001_00_kick.mp4"])
    body = {"ws": ws, "name": "combo-set", "trigger": TRIGGER, "descriptor": DESC, "dir": d, "performers": 3}
    status, _h, payload = mt.api(s, "POST", "/api/actions", body=body)
    assert status == 201, payload
    job = _job(state, payload)
    assert job["kind"] == "action-create"
    assert job["argv"] == [sys.executable, os.path.join(ws, "bin", "action"), "create", "combo-set",
                           "--trigger", TRIGGER, "--descriptor", DESC, "--dir", d, "--performers", "3"]
    assert "--clip" not in job["argv"]
    assert list(job["fields"]) == ["ws", "name", "trigger", "descriptor", "dir", "performers", "force",
                                   "regenerate"]
    assert job["fields"]["dir"] == d and "clips" not in job["fields"]
    assert lib.read_queue(state) == [job["id"]] and mt.status_of(state, job["id"]) == {}
    status, _h, payload = mt.api(s, "POST", "/api/actions",
                                 body=dict(body, clips=[os.path.join(d, "001_00_kick.mp4")]))
    assert (status, payload["errors"]) == (400, ["give either clip paths or a folder, not both"])


def test_bkt17_dataset_clips_sort_naturally(env):
    s, ws = env["srv"], env["ws"]
    _real_action_tool(ws)
    clips_dir = _write_action(env["tmp"], "kick-set", ["/abs/ref0.mp4"], 101)
    status, _h, payload = mt.api(s, "GET", "/api/actions/kick-set?ws=" + ws)
    assert status == 200, payload
    assert [os.path.basename(p) for p in payload["clips"]] == ["clip_%02d.mp4" % i for i in range(101)]
    assert payload["clips"][100] == os.path.join(clips_dir, "clip_100.mp4")


def test_bkt18_the_page_folder_preview_and_gallery_cap():
    static = os.path.join(mt.WS, "static", "movie-ui")
    with open(os.path.join(static, "index.html"), encoding="utf-8") as f:
        html = f.read()
    with open(os.path.join(static, "app.js"), encoding="utf-8") as f:
        js = f.read()
    for element in ("a-dir", "a-preview", "a-preview-out", "a-preview-summary", "a-preview-clips",
                    "a-preview-skipped"):
        assert html.count('id="%s"' % element) == 1, element
    assert html.index('id="a-clips"') < html.index('id="a-dir"') < html.index('id="a-performers"')
    assert html.index('id="a-preview"') < html.index('id="a-create"') < html.index('id="a-preview-out"')
    for text in ('"/api/actions/preview"', "function renderActionPreview(data) {", "const ACTION_GALLERY_MAX = 24;",
                 "give either clip paths or a folder, not both", "res.data.clips.slice(0, ACTION_GALLERY_MAX)",
                 "enter a folder path to preview", "(enter a trigger to see the caption)",
                 '" more clips in the dataset"', "if (dir) { body.dir = dir; } else { body.clips = clips; }"):
        assert text in js, text
    assert js.count("res.data.clips.forEach(") == 1   # the Stories gallery's line; the Actions one is capped
    for name, text in (("index.html", html), ("app.js", js)):
        for pattern in (r"https?://", r"\son[a-z]+=", r"style=", r"\bconfirm\(", r"innerHTML"):
            assert not re.search(pattern, text), (name, pattern)
    node = shutil.which("node")
    if node:
        proc = subprocess.run([node, "--check", os.path.join(static, "app.js")], capture_output=True, text=True,
                              timeout=60)
        assert proc.returncode == 0, proc.stderr


# --- Review Focus 3-5 ----------------------------------------------------------------------------

def test_bk_review_focus_3_rebuild_resends_the_folder(env):
    s, ws, state = env["srv"], env["ws"], env["state"]
    _real_action_tool(ws)
    d = _folder(env["tmp"], ["001_00_kick.mp4"])
    body = {"ws": ws, "name": "combo-set", "trigger": TRIGGER, "descriptor": DESC, "dir": d, "performers": 3}
    status, _h, payload = mt.api(s, "POST", "/api/actions", body=body)
    assert status == 201, payload
    first = _job(state, payload)
    _write_action(env["tmp"], "combo-set", [os.path.join(d, "001_00_kick.mp4")], 1)
    status, _h, detail = mt.api(s, "GET", "/api/actions/combo-set?ws=" + ws)
    assert status == 200, detail
    assert detail["last_create_fields"] == first["fields"]
    # app.js Rebuild: Object.assign({}, S.action.last_create_fields, {regenerate: true})
    status, _h, payload = mt.api(s, "POST", "/api/actions", body=dict(detail["last_create_fields"], regenerate=True))
    assert status == 201, payload
    argv = _job(state, payload)["argv"]
    assert argv[-5:] == ["--dir", d, "--performers", "3", "--regenerate"] and "--clip" not in argv
    clip = os.path.join(d, "001_00_kick.mp4")
    status, _h, payload = mt.api(s, "POST", "/api/actions", body=dict(body, name="clip-set", dir=None, clips=[clip]))
    assert status == 201, payload
    job = _job(state, payload)
    assert "--dir" not in job["argv"] and job["argv"][job["argv"].index("--clip") + 1] == clip
    assert "dir" not in job["fields"] and job["fields"]["clips"] == [clip]


def test_bk_review_focus_4_preview_captions_use_the_normalized_trigger(env):
    s, ws, state = env["srv"], env["ws"], env["state"]
    _real_action_tool(ws)
    d = _folder(env["tmp"], ["001_00_kick.mp4"])
    loose = "  performs   a fight combo "
    status, _h, data = mt.api(s, "POST", "/api/actions/preview", body={"ws": ws, "dir": d, "trigger": loose})
    assert status == 200, data
    assert data["clips"][0]["caption"] == "performs a fight combo: kick"
    status, _h, data = mt.api(s, "POST", "/api/actions/preview", body={"ws": ws, "dir": d, "trigger": "   "})
    assert status == 200 and data["clips"][0]["caption"] is None
    status, _h, payload = mt.api(s, "POST", "/api/actions", body={"ws": ws, "name": "combo-set", "trigger": loose,
                                                                  "descriptor": DESC, "dir": d, "performers": 3})
    assert status == 201, payload
    argv = _job(state, payload)["argv"]
    assert argv[argv.index("--trigger") + 1] == TRIGGER


def test_bk_review_focus_5_preview_needs_only_action_lib(env):
    s, ws = env["srv"], env["ws"]
    with open(os.path.join(mt.WS, "movie_ui_server.py"), encoding="utf-8") as f:
        source = f.read()
    assert not re.search(r"^\s*(import|from)\s+action_(lib|dataset)\b", source, re.M)
    _real_action_tool(ws)
    assert not os.path.exists(os.path.join(ws, "action_dataset.py"))
    d = _folder(env["tmp"], [])
    status, _h, data = mt.api(s, "POST", "/api/actions/preview", body={"ws": ws, "dir": d, "trigger": TRIGGER})
    assert (status, data) == (200, {"dir": d, "matched": 0, "max": 1000, "clips": [], "skipped": []})
