"""movie-ui action (motion LoRA) support: the Compose action_loras field, its --action argv,
the bin/action create/train job argv, and the Actions tab's list parsing and field rules."""

import os

import movie_ui_testutil as mt  # noqa: F401  (puts the workspace on sys.path)
import movie_ui_lib as lib
import movie_ui_server as srv

DESC = "a spinning kick delivered with the rear leg to head height in one motion"


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
