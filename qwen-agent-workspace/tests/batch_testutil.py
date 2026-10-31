"""Shared helpers for the batch-forks tests (docs/superpowers/specs/2026-10-30-batch-forks-design.md,
Section 7). Not a test module (pytest does not collect it).

Every helper writes under the stub workspace or the temporary STATE its caller passes in. Nothing
here reads the real HOME, renders, or contacts a server other than the in-test movie-ui server on
127.0.0.1 (movie_ui_testutil.Running); jobs run only the stub workspace's bin/ltx-movie.
"""

import hashlib
import os

import movie_ui_testutil as mt
import movie_ui_lib as lib

STORY_MD = ("## Panel 1 -- Shot 1\nImage: a quiet road.\nMotion: the camera drifts.\n\n"
            "## Panel 2 -- Shot 2\nImage: a dark gate.\nMotion: the camera pushes in.\n")
OTHER_MODEL = "/models/other"
RENDER = {"model": OTHER_MODEL}
OTHER_GEMMA = "/models/gemma-other"


def original(state, ws, story_id, files=None, job_state="done", **overrides):
    """An original story (spec 7 rules): <ws>/generated/stories/<story_id> holding story.md, or
    files ({relpath: bytes}), and a movie job of that story whose fields (movie_ui_testutil.fields
    with action movie and overrides) are its last_fields. job_state is "done" (the default),
    "queued" or "running". Returns (story directory, job ID)."""
    sdir = lib.story_dir(ws, story_id)
    os.makedirs(sdir, exist_ok=True)
    for rel, data in (files if files is not None else {"story.md": STORY_MD.encode("utf-8")}).items():
        path = os.path.join(sdir, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            f.write(data)
    status = {"done": {"state": "done", "exit_code": 0, "ended": lib.utc_now()},
              "running": {"state": "running", "dispatched": lib.utc_now(), "runner_pid": 1, "pgid": None,
                          "started": lib.utc_now()},
              "queued": None}[job_state]
    fields = mt.fields(ws, action="movie", story_id=story_id, **overrides)
    return sdir, mt.make_job(state, ["true"], ws, story_id=story_id, fields=fields, status=status)


def variant(label="v1", settings=None, append="", replace=(), per_story=None):
    """One request variant (spec 3.2); replace is [(find, with)]."""
    return {"label": label, "settings": dict(settings or {}),
            "prompt": {"append": append, "replace": [{"find": f, "with": w} for f, w in replace],
                       "per_story": dict(per_story or {})}}


def body(ws, stories, variants):
    return {"ws": ws, "stories": list(stories), "variants": list(variants)}


def passing_checks(monkeypatch, fail=None, gate=None):
    """Replace lib.run_checks (spec 7 rules): V1 passes, except that a fork ID in fail ({fork_id:
    detail}) gets a failing V6 dry run; a fork ID in gate ({fork_id: threading.Event}) waits for
    its event (30 s at most) first. Returns the list of the fork IDs checked, in call order."""
    calls = []

    def fake(fields, ws_real, state, py=None):
        calls.append(fields["story_id"])
        event = (gate or {}).get(fields["story_id"])
        if event is not None:
            event.wait(30)
        if fields["story_id"] in (fail or {}):
            return [lib.check("V1", "fields", "pass"),
                    lib.check("V6", "dry run", "fail", fail[fields["story_id"]])]
        return [lib.check("V1", "fields", "pass")]
    monkeypatch.setattr(lib, "run_checks", fake)
    return calls


def submit(s, ws, stories, variants):
    """POST /api/batches; asserts 201 and returns the batch ID."""
    status, _h, payload = mt.api(s, "POST", "/api/batches", body=body(ws, stories, variants))
    assert status == 201, payload
    return payload["batch"]["id"]


def wait_status(s, batch_id, statuses=("submitted",), timeout=30):
    """Poll GET /api/batches/<id> until the batch status is one of statuses; returns the payload."""
    def ready():
        status, _h, payload = mt.api(s, "GET", "/api/batches/" + batch_id)
        return payload if status == 200 and payload["batch"]["status"] in statuses else None
    return mt.wait_until(ready, timeout, interval=0.1)


def record(state, batch_id):
    """The batch.json of batch_id as stored."""
    return lib.read_json(os.path.join(state, "batches", batch_id, "batch.json"))


def tree_digests(root):
    """{relpath: sha256 hex digest} of every file under root."""
    out = {}
    for base, _dirs, files in os.walk(root):
        for name in files:
            path = os.path.join(base, name)
            with open(path, "rb") as f:
                out[os.path.relpath(path, root)] = hashlib.sha256(f.read()).hexdigest()
    return out


def run_job(state, job_id, timeout=30):
    """Dispatch one job as dispatch_tick does and wait until it is done (the stub ltx-movie runs)."""
    mt.dispatch(state, job_id)
    mt.wait_until(lambda: mt.status_of(state, job_id).get("state") == "done", timeout)
