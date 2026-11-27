"""Tests for image_critic.py and bin/image-critic (docs/superpowers/specs/2026-11-27-image-critic-design.md,
Section 6.1: ICT1-ICT13): the derived seeds, the verdict parser, judge_image, the VLM lifecycle around the judge
phases, edit_with_critic's redo loop, records and log lines, the interrupt cleanup, the calibration CLI and the
import hygiene.

Run from the workspace root: python3 -m pytest -q -p no:cacheprovider tests/test_image_critic.py

Rules (spec 6.1): image_critic is a plain import. ic._cd is replaced by FakeCD, which records every call in order in
a shared log (FakeQE writes to the same log, so the order of Qwen and VLM work is visible); its extract_json is the
real character_dataset.extract_json and its image_data_url returns "data:" + path, so replies are scripted per file
and per call. ic.subprocess is replaced by a namespace whose Popen only records. No test contacts a server, starts a
process other than the importtime child of ICT13, or touches port 8177 or 8178. Stdlib and pytest.
"""

import glob
import hashlib
import importlib.machinery
import importlib.util
import json
import os
import random
import re
import signal
import subprocess
import sys
import time
import types

import pytest

import movie_ui_testutil as mt  # noqa: F401  (puts the workspace on sys.path)
import character_dataset
import image_critic as ic

WS = mt.WS
MODELS_URL = "http://127.0.0.1:8177/v1/models"
JUDGE_PROMPT = (
    "The picture to check was made by an AI image editor. Check only the bodies of the people and animals in it for "
    "anatomy errors. Defects to look for: extra, missing or fused arms, legs, hands or fingers; melted, stretched, "
    "twisted or warped bodies or limbs; a distorted, doubled or smeared face; malformed hands; a body merging into "
    "the background, an object or another person. Ignore the art style, lighting, composition, framing, clothing, "
    "setting, image quality, and whether the picture matches any description; a dynamic or unusual pose is not a "
    "defect when the body is anatomically possible. Reply with only a JSON object with three keys. \"score\": an "
    "integer from 1 to 10 for how anatomically correct every body is, where 10 means every body is natural and "
    "complete, 7 means only small flaws a viewer would not notice at a glance, and 4 or less means an obvious "
    "defect; a picture with no people or animals scores 10. \"defects\": a list of at most 8 short phrases, one per "
    "defect you see, such as \"fused left hand\" (an empty list when there is none). \"reason\": one sentence.")
SEED_PREFACE = ("You get two images. The first is the photo the edit started from; the second is the picture to "
                "check. Use the first only to see what these people's bodies normally look like, and do not count "
                "differences in pose, setting, clothing or style. ")
START = "critic: starting the VLM (bin/story-server-restore mlx-vision --wait)"
STOP_END = "critic: stopping the VLM (it was stopped before the critic started)"
STOP_REDO = "critic: stopping the VLM for the Qwen redo"
HANDS_OFF = "the story server is SERVING text; the image critic needs it stopped or serving mlx-vision"


def verdict(score, defects=(), reason="r"):
    """A well-formed VLM reply."""
    return json.dumps({"score": score, "defects": list(defects), "reason": reason})


class FakeCD(object):
    """ic._cd's stand-in (spec 6.1). replies maps a judged file's path to its replies, one per vlm_call; a reply is a
    str, an exception (raised) or a callable (called, and its value used). The story server's state follows the
    calls: a successful stop makes vlm_ready False, a successful restore makes it True."""
    STORY_SERVER = "/fake-ws/bin/story-server"
    VLM_SERVE_MODE = "mlx-vision"
    VLM_WAIT_S = 600
    AVAIL_WAIT_S = 600
    MODELS_URL = MODELS_URL
    extract_json = staticmethod(character_dataset.extract_json)

    def __init__(self, log, state="STOPPED"):
        self.log = log
        self.state = state
        self.up = state.startswith("SERVING")
        self.replies, self.calls, self.parts, self.max_tokens = {}, {}, [], []
        self.avail, self.restore_rc, self.stop_rc, self.wait_ok = True, 0, 0, True
        self.unreadable = set()

    def story_server_state(self):
        self.log.append(("story_server_state",))
        return self.state

    def restore_story_server(self, wait=False):
        self.log.append(("restore_story_server", wait))
        if self.restore_rc == 0:
            self.up = True
        return self.restore_rc

    def story_server(self, cmd):
        self.log.append(("story_server", cmd))
        if cmd == "stop" and self.stop_rc == 0:
            self.up = False
        return self.stop_rc

    def wait_for_vlm(self, timeout_s):
        self.log.append(("wait_for_vlm", timeout_s))
        return self.wait_ok

    def wait_for_avail(self, min_gib, timeout_s):
        self.log.append(("wait_for_avail", min_gib, timeout_s))
        return self.avail

    def vlm_ready(self):
        self.log.append(("vlm_ready",))
        return self.up

    def image_data_url(self, path, max_side=768):
        self.log.append(("image_data_url", path, max_side))
        if path in self.unreadable:
            raise OSError("gone")
        return "data:" + path

    def vlm_call(self, parts, max_tokens=600):
        path = [p["image_url"]["url"] for p in parts if p["type"] == "image_url"][-1][len("data:"):]
        self.log.append(("vlm_call", path))
        self.parts.append(parts)
        self.max_tokens.append(max_tokens)
        i = self.calls.get(path, 0)
        self.calls[path] = i + 1
        reply = self.replies[path][i]
        if callable(reply):
            reply = reply()
        if isinstance(reply, BaseException):
            raise reply
        return reply


class FakeQE(object):
    """The qwen_edit stand-in (spec 6.1): run_jobs with the real signature handles the jobs in order by
    outcomes.get((n, seed), "ok"): "ok" writes b"img:<n>:<seed>" to output_path, "blocked" and "failed" write
    nothing, and an exception is raised after writing the job's stage file. failure maps a call index to the failure
    that call returns."""

    class Unavailable(Exception):
        pass

    def __init__(self, log):
        self.log = log
        self.outcomes, self.failure, self.calls, self.returns = {}, {}, [], []
        self.wait_error = None

    def run_jobs(self, model_id, loras, jobs, width, height, skill, work_dir, log_path=None, on_result=None,
                 noun="job"):
        index = len(self.calls)
        self.calls.append({"jobs": [dict(j) for j in jobs], "on_result": on_result is not None, "noun": noun,
                           "work_dir": work_dir})
        self.log.append(("run_jobs", [j["n"] for j in jobs]))
        results = []
        for job in jobs:
            outcome = self.outcomes.get((job["n"], job["seed"]), "ok")
            if isinstance(outcome, BaseException):
                with open(job["stage_path"], "wb") as f:
                    f.write(b"pending")
                raise outcome
            if outcome == "ok":
                with open(job["output_path"], "wb") as f:
                    f.write(b"img:%d:%d" % (job["n"], job["seed"]))
            result = {"n": job["n"], "output_path": job["output_path"], "status": outcome,
                      "seconds": None if outcome == "failed" else 1.0}
            if on_result is not None and outcome != "failed":
                on_result(dict(result))
            results.append(result)
        got = (results, self.failure.get(index))
        self.returns.append(got)
        return got

    def wait_for_memory(self, floor, label, tag="seed-edit"):
        self.log.append(("wait_for_memory", floor, label, tag))
        if self.wait_error is not None:
            raise self.wait_error

    def memory_floor(self, model_id, references=1):
        return 20.0

    def label(self, model_id):
        return "Fake"


class Env(object):
    """One test's fakes, its jobs and its recorders."""

    def __init__(self, tmp):
        self.tmp = tmp
        self.log = []
        self.cd = FakeCD(self.log)
        self.qe = FakeQE(self.log)
        self.popens = []
        self.verdicts = []
        self.bests = []
        self.results = []

    def jobs(self, count, sub="run"):
        """count bin/seed-edit-shaped jobs under <tmp>/<sub>: seeds 11, 12, ...; work dir <tmp>/<sub>/work."""
        run_dir = os.path.join(self.tmp, sub)
        self.work = os.path.join(run_dir, "work")
        os.makedirs(self.work)
        return [{"n": n, "seed": 10 + n, "prompt": "make it night", "source": os.path.join(self.work, "source.png"),
                 "stage_path": os.path.join(self.work, "cand_%02d.pending.png" % n),
                 "output_path": os.path.join(run_dir, "cand_%02d.png" % n)} for n in range(1, count + 1)]

    def attempt(self, job, k):
        return os.path.join(os.path.dirname(job["stage_path"]), "critic", "cand_%02d.r%d.png" % (job["n"], k))

    def run(self, jobs, **kw):
        kw.setdefault("on_verdict", lambda n, block: self.verdicts.append((n, block)))
        kw.setdefault("on_best", lambda n, path: self.bests.append((n, path)))
        kw.setdefault("on_result", lambda r: self.results.append(r))
        return ic.edit_with_critic(self.qe, "qwen21-q4", [], jobs, 64, 64, "seed_edit", self.work, **kw)

    def block(self, n):
        """The newest block on_verdict got for job n."""
        return [b for m, b in self.verdicts if m == n][-1]

    def lifecycle(self):
        return [e for e in self.log if e[0] != "image_data_url"]


@pytest.fixture
def env(monkeypatch, tmp_path):
    e = Env(os.path.realpath(str(tmp_path)))
    monkeypatch.setattr(ic, "_cd", lambda: e.cd)
    monkeypatch.setattr(ic, "subprocess", types.SimpleNamespace(
        Popen=lambda argv, **kw: e.popens.append((argv, kw)), DEVNULL=subprocess.DEVNULL))
    return e


def _read(path):
    with open(path, "rb") as f:
        return f.read()


def _lines(capsys):
    return capsys.readouterr().out.splitlines()


def _att(round_n, seed, score, defects=(), note=None):
    return {"round": round_n, "seed": seed, "score": score, "defects": list(defects), "note": note}


# --- ICT1: constants, prompts and seeds ----------------------------------------------------------------------

def test_ict1_constants_prompts_and_seeds():
    assert (ic.PASS_SCORE, ic.DEFAULT_ROUNDS, ic.MAX_ROUNDS) == (7, 2, 4)
    assert ic.JUDGE_WITH_SEED is False
    assert (ic.JUDGE_MAX_SIDE, ic.JUDGE_ATTEMPTS, ic.JUDGE_MAX_TOKENS) == (1024, 2, 400)
    assert (ic.DEFECTS_MAX, ic.DEFECT_CHARS, ic.REASON_CHARS) == (8, 60, 300)
    assert (ic.VLM_MIN_AVAIL_GIB, ic.SEED_MAX, ic.CRITIC_DIR) == (28.0, 2147483647, "critic")
    assert ic.LINE_STATES == {"passed": "ok", "flagged": "flagged", "unjudged": "unjudged"}
    assert ic.JUDGE_PROMPT == JUDGE_PROMPT
    assert ic.SEED_PREFACE == SEED_PREFACE and ic.JUDGE_SEED_PROMPT == SEED_PREFACE + JUDGE_PROMPT
    assert ic.JUDGE_RETRY == ('Your previous reply was rejected: %s. Previous reply: %s\n'
                              'Reply again with only the JSON object: "score" an integer from 1 to 10, "defects" a '
                              'list of short phrases (empty when there is none) and "reason" one sentence.')
    expected = int(hashlib.sha256(b"image-critic:7:1:2").hexdigest()[:8], 16) & 2147483647
    assert ic.critic_seed(7, 1, 2) == expected
    assert ic.critic_seed(7, 2, 2) != expected and ic.critic_seed(7, 1, 3) != expected
    rng = random.Random(27)
    for _ in range(100):
        seed = ic.critic_seed(rng.randrange(0, 2 ** 31), rng.randrange(1, 5), rng.randrange(1, 16))
        assert 0 <= seed <= ic.SEED_MAX


# --- ICT2: parse_verdict --------------------------------------------------------------------------------------

def test_ict2_parse_verdict(env):
    good = '{"score": 8, "defects": ["fused left hand"], "reason": "One hand is fused."}'
    want = {"score": 8, "defects": ["fused left hand"], "reason": "One hand is fused."}
    assert ic.parse_verdict(good) == want
    assert ic.parse_verdict("```json\n" + good + "\n```") == want
    assert ic.parse_verdict('<think>{"score": 1}</think>' + good) == want
    for score, message in ((True, "score must be an integer, got True"), (8.0, "score must be an integer, got 8.0"),
                           ("8", "score must be an integer, got '8'"), (None, "score must be an integer, got None"),
                           (0, "score must be 1-10, got 0"), (11, "score must be 1-10, got 11")):
        with pytest.raises(ValueError) as e:
            ic.parse_verdict(json.dumps({"score": score, "defects": [], "reason": "r"}))
        assert str(e.value) == message, score
    for reply, message in (('{"score": 8, "reason": "r"}', "missing key: defects"),
                           ('{"score": 8, "defects": "x"}', "defects must be a list of strings"),
                           ('{"score": 8, "defects": ["a", 2]}', "defects must be a list of strings"),
                           ("no json", "no JSON object found in text")):
        with pytest.raises(ValueError) as e:
            ic.parse_verdict(reply)
        assert str(e.value) == message, reply
    with pytest.raises(ValueError) as e:
        ic.parse_verdict(None)
    assert str(e.value) == "the reply has no text"
    messy = ["  fused \n left   hand ", "", "   ", "x" * 80] + ["d%d" % i for i in range(10)]
    got = ic.parse_verdict(json.dumps({"score": 5, "defects": messy}))
    assert got == {"score": 5, "defects": ["fused left hand", "x" * 60, "d0", "d1", "d2", "d3", "d4", "d5"],
                   "reason": ""}
    assert ic.parse_verdict('{"score": 5, "defects": [], "reason": 7}')["reason"] == ""
    assert ic.parse_verdict(json.dumps({"score": 5, "defects": [], "reason": " a \n b " + "c" * 400}))["reason"] == (
        "a b " + "c" * 296)


# --- ICT3: judge_image ----------------------------------------------------------------------------------------

def test_ict3_judge_image(env):
    cd = env.cd
    img, seed = os.path.join(env.tmp, "edit.png"), os.path.join(env.tmp, "seed.png")
    cd.replies[img] = ["no json here", verdict(8, ["fused hand"])]
    assert ic.judge_image(img) == {"score": 8, "defects": ["fused hand"], "reason": "r"}
    first, second = cd.parts
    assert first == [{"type": "text", "text": JUDGE_PROMPT}, {"type": "image_url", "image_url": {"url": "data:" + img}}]
    assert second[:-1] == first
    assert second[-1] == {"type": "text", "text": ic.JUDGE_RETRY % ("no JSON object found in text", "no json here")}
    assert cd.max_tokens == [400, 400]
    assert [e[2] for e in env.log if e[0] == "image_data_url"] == [1024]
    cd.replies[img] = ["a", "b", "c", "d"]
    cd.calls = {}
    with pytest.raises(ic.JudgeError) as e:
        ic.judge_image(img)
    assert type(e.value) is ic.JudgeError and str(e.value) == "unparseable: no JSON object found in text"
    for error, text in ((RuntimeError("HTTP 500"), "VLM request failed: RuntimeError: HTTP 500"),
                        (OSError("connection refused"), "VLM request failed: OSError: connection refused")):
        cd.replies[img], cd.calls = [error], {}
        with pytest.raises(ic.VLMUnavailable) as e:
            ic.judge_image(img)
        assert str(e.value) == text
    del cd.parts[:]
    cd.replies[img], cd.calls = [verdict(9)], {}
    assert ic.judge_image(img, seed)["score"] == 9
    assert cd.parts[-1] == [{"type": "text", "text": SEED_PREFACE + JUDGE_PROMPT},
                            {"type": "image_url", "image_url": {"url": "data:" + seed}},
                            {"type": "image_url", "image_url": {"url": "data:" + img}}]
    cd.unreadable.add(seed)
    with pytest.raises(ic.JudgeError) as e:
        ic.judge_image(img, seed)
    assert type(e.value) is ic.JudgeError and str(e.value) == "cannot read %s: OSError: gone" % seed


# --- ICT4 (K5): every image passes ----------------------------------------------------------------------------

def test_ict4_all_pass_one_start_one_stop(env, capsys):
    jobs = env.jobs(3)
    for job in jobs:
        env.cd.replies[job["output_path"]] = [verdict(8)]
    got = env.run(jobs)
    assert got[0] is env.qe.returns[0][0] and got[1] is None
    assert len(env.qe.calls) == 1 and env.qe.calls[0]["on_result"] is True
    assert env.lifecycle() == [("run_jobs", [1, 2, 3]), ("story_server_state",), ("wait_for_avail", 28.0, 600),
                               ("restore_story_server", True), ("wait_for_vlm", 600)] + [
        ("vlm_call", job["output_path"]) for job in jobs] + [("story_server", "stop")]
    for job in jobs:
        assert env.block(job["n"]) == {"status": "passed", "score": 8, "defects": [], "reason": "r",
                                       "seed_used": job["seed"], "pass_score": 7,
                                       "attempts": [_att(0, job["seed"], 8)]}
    assert [n for n, _b in env.verdicts] == [1, 2, 3, 1, 2, 3]
    assert glob.glob(os.path.join(env.work, "critic", "*.png")) == [] and env.bests == []
    assert [r["n"] for r in env.results] == [1, 2, 3]
    assert _lines(capsys) == ["critic: judging 3 jobs with the VLM (round 0)", START,
                              "critic 1/3: ok (score 8, attempt 1)", "critic 2/3: ok (score 8, attempt 1)",
                              "critic 3/3: ok (score 8, attempt 1)",
                              "critic: done: 3 passed, 0 flagged, 0 unjudged; 0 redo round(s) run", STOP_END]


# --- ICT5 (K2, K3): only the failed job is redone, and the VLM and Qwen take turns ----------------------------

def test_ict5_only_the_failed_job_is_redone_in_order(env, capsys):
    jobs = env.jobs(3)
    two = jobs[1]
    seed = ic.critic_seed(12, 1, 2)
    env.cd.replies.update({jobs[0]["output_path"]: [verdict(8)], two["output_path"]: [verdict(3, ["fused left hand"])],
                           jobs[2]["output_path"]: [verdict(8)], env.attempt(two, 1): [verdict(8, [], "fixed")]})
    assert env.run(jobs, total=3)[1] is None
    (_first, redo) = env.qe.calls
    critic = os.path.join(env.work, "critic")
    assert redo["jobs"] == [dict(two, seed=seed, stage_path=os.path.join(critic, "cand_02.r1.pending.png"),
                                 output_path=os.path.join(critic, "cand_02.r1.png"))]
    assert redo["on_result"] is False and redo["noun"] == "job" and redo["work_dir"] == env.work
    assert env.lifecycle() == [
        ("run_jobs", [1, 2, 3]), ("story_server_state",), ("wait_for_avail", 28.0, 600),
        ("restore_story_server", True), ("wait_for_vlm", 600)] + [("vlm_call", j["output_path"]) for j in jobs] + [
        ("story_server", "stop"), ("wait_for_memory", 20.0, "Fake", "seed-edit"), ("run_jobs", [2]),
        ("wait_for_avail", 28.0, 600), ("restore_story_server", True), ("wait_for_vlm", 600),
        ("vlm_call", env.attempt(two, 1)), ("story_server", "stop")]
    assert _read(two["output_path"]) == b"img:2:%d" % seed
    assert _read(env.attempt(two, 0)) == b"img:2:12"
    assert sorted(os.listdir(critic)) == ["cand_02.r0.png", "cand_02.r1.png"]
    assert env.bests == [(2, two["output_path"])]
    assert env.block(2) == {"status": "passed", "score": 8, "defects": [], "reason": "fixed", "seed_used": seed,
                            "pass_score": 7, "attempts": [_att(0, 12, 3, ["fused left hand"]), _att(1, seed, 8)]}
    assert env.block(1)["attempts"] == [_att(0, 11, 8)]
    assert two["seed"] == 12 and "critic" not in two
    out = _lines(capsys)
    assert [line for line in out if line.startswith("critic 2/3")] == [
        "critic 2/3: redo (score 3: fused left hand)", "critic 2/3: ok (score 8, attempt 2)"]
    assert out[5:9] == [STOP_REDO, "critic: redo round 1 of 2: job 2 with new seeds",
                        "critic: judging 1 job with the VLM (round 1)", START]
    assert out[-2:] == ["critic: done: 3 passed, 0 flagged, 0 unjudged; 1 redo round(s) run", STOP_END]


# --- ICT6: flagged on exhaustion, the best attempt kept ---------------------------------------------------------

def test_ict6_flagged_on_exhaustion_keeps_the_best(env, capsys):
    (job,) = env.jobs(1, "a")
    env.cd.replies.update({job["output_path"]: [verdict(5, ["melted arm"])], env.attempt(job, 1): [verdict(3, ["x"])],
                           env.attempt(job, 2): [verdict(4, ["y"])]})
    assert env.run([job], rounds=2)[1] is None
    assert [len(c["jobs"]) for c in env.qe.calls] == [1, 1, 1]
    assert _read(job["output_path"]) == b"img:1:11" and env.bests == []
    block = env.block(1)
    assert (block["status"], block["score"], block["defects"], block["seed_used"]) == ("flagged", 5, ["melted arm"], 11)
    assert [a["score"] for a in block["attempts"]] == [5, 3, 4]
    assert [a["seed"] for a in block["attempts"]] == [11, ic.critic_seed(11, 1, 1), ic.critic_seed(11, 2, 1)]
    assert [line for line in _lines(capsys) if line.startswith("critic 1/1")] == [
        "critic 1/1: redo (score 5: melted arm)", "critic 1/1: redo (score 3: x)",
        "critic 1/1: flagged (best score 5 of 3 attempts: melted arm)"]
    (tie,) = env.jobs(1, "b")
    env.cd.replies.update({tie["output_path"]: [verdict(5, ["a"])], env.attempt(tie, 1): [verdict(5, ["b"])],
                           env.attempt(tie, 2): [verdict(2, ["c"])]})
    env.run([tie])
    assert _read(tie["output_path"]) == b"img:1:11"
    assert (env.block(1)["seed_used"], env.block(1)["defects"]) == (11, ["a"])
    capsys.readouterr()
    (once,) = env.jobs(1, "c")
    env.cd.replies[once["output_path"]] = [verdict(5, ["melted arm"])]
    calls = len(env.qe.calls)
    env.run([once], rounds=0)
    assert len(env.qe.calls) == calls + 1
    assert env.block(1)["status"] == "flagged" and len(env.block(1)["attempts"]) == 1
    assert [line for line in _lines(capsys) if line.startswith("critic 1/1")] == [
        "critic 1/1: flagged (best score 5 of 1 attempts: melted arm)"]


# --- ICT7: unjudged when the VLM is down or the reply is unusable -----------------------------------------------

def test_ict7a_the_vlm_does_not_start(env, capsys):
    jobs = env.jobs(2)
    env.cd.restore_rc = 1
    env.run(jobs)
    reason = "bin/story-server-restore mlx-vision --wait exited 1"
    for job in jobs:
        assert env.block(job["n"]) == {"status": "unjudged", "score": None, "defects": [], "reason": reason,
                                       "seed_used": job["seed"], "pass_score": 7,
                                       "attempts": [_att(0, job["seed"], None, note="not judged: " + reason)]}
    assert len(env.qe.calls) == 1
    assert env.lifecycle()[-2:] == [("restore_story_server", True), ("story_server", "stop")]
    out = _lines(capsys)
    assert "critic 1/2: unjudged (%s)" % reason in out and "critic 2/2: unjudged (%s)" % reason in out
    assert "critic: done: 0 passed, 0 flagged, 2 unjudged; 0 redo round(s) run" in out


def test_ict7b_a_transport_error_ends_the_phase(env, capsys):
    jobs = env.jobs(3)
    env.cd.replies.update({jobs[0]["output_path"]: [verdict(3)],
                           jobs[1]["output_path"]: [OSError("connection refused")],
                           jobs[2]["output_path"]: [verdict(9)]})
    env.run(jobs)
    assert jobs[2]["output_path"] not in env.cd.calls
    assert len(env.qe.calls) == 1
    reason = "VLM request failed: OSError: connection refused"
    assert [env.block(n)["status"] for n in (1, 2, 3)] == ["flagged", "unjudged", "unjudged"]
    assert env.block(3)["reason"] == reason and env.block(3)["attempts"][0]["note"] == "not judged: " + reason
    assert [line for line in _lines(capsys) if line.startswith("critic ")] == [
        "critic 1/3: redo (score 3: no defect named)", "critic 2/3: unjudged (%s)" % reason,
        "critic 3/3: unjudged (%s)" % reason, "critic 1/3: flagged (best score 3 of 1 attempts: no defect named)"]


def test_ict7c_an_unparseable_image_is_never_redone(env):
    jobs = env.jobs(2)
    env.cd.replies.update({jobs[0]["output_path"]: ["nope", "still nope"], jobs[1]["output_path"]: [verdict(3)],
                           env.attempt(jobs[1], 1): [verdict(8)]})
    env.run(jobs)
    assert [[j["n"] for j in call["jobs"]] for call in env.qe.calls] == [[1, 2], [2]]
    assert env.block(1)["status"] == "unjudged"
    assert env.block(1)["reason"] == "unparseable: no JSON object found in text"
    assert env.block(2)["status"] == "passed"


def test_ict7d_a_foreign_story_server_is_left_alone(env, capsys):
    jobs = env.jobs(2)
    env.cd.state = "SERVING text"
    env.run(jobs)
    assert env.lifecycle() == [("run_jobs", [1, 2]), ("story_server_state",)]
    assert [env.block(n)["reason"] for n in (1, 2)] == [HANDS_OFF, HANDS_OFF]
    assert [env.block(n)["status"] for n in (1, 2)] == ["unjudged", "unjudged"]
    assert "critic 1/2: unjudged (%s)" % HANDS_OFF in _lines(capsys)


# --- ICT8 (K4): the VLM is restored on an exception and on a signal ---------------------------------------------

def test_ict8a_an_exception_restores_synchronously(env, capsys):
    jobs = env.jobs(1)
    env.cd.replies[jobs[0]["output_path"]] = [verdict(8)]

    def broken(n, block):
        raise RuntimeError("record write failed")

    with pytest.raises(RuntimeError, match="^record write failed$"):
        env.run(jobs, on_verdict=broken)
    assert env.lifecycle()[-1] == ("story_server", "stop") and env.popens == []
    assert _lines(capsys)[-1] == STOP_END


def test_ict8b_an_interrupted_redo_and_its_judge_phase(env, capsys):
    jobs = env.jobs(2, "a")
    two = jobs[1]
    seed = ic.critic_seed(12, 1, 2)
    env.cd.replies.update({jobs[0]["output_path"]: [verdict(8)], two["output_path"]: [verdict(3)]})
    env.qe.outcomes[(2, seed)] = KeyboardInterrupt()
    with pytest.raises(KeyboardInterrupt):
        env.run(jobs)
    assert glob.glob(os.path.join(env.work, "critic", "*.pending.png")) == []
    assert _read(two["output_path"]) == b"img:2:12"
    assert env.lifecycle()[-3:] == [("story_server", "stop"), ("wait_for_memory", 20.0, "Fake", "seed-edit"),
                                    ("run_jobs", [2])]
    assert env.popens == []
    capsys.readouterr()
    jobs = env.jobs(2, "b")
    two = jobs[1]
    del env.qe.outcomes[(2, seed)]
    env.cd.replies.update({jobs[0]["output_path"]: [verdict(8)], two["output_path"]: [verdict(3)],
                           env.attempt(two, 1): [KeyboardInterrupt()]})
    del env.log[:]
    with pytest.raises(KeyboardInterrupt):
        env.run(jobs)
    assert env.popens == [([FakeCD.STORY_SERVER, "stop"], {
        "stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL,
        "start_new_session": True, "close_fds": True})]
    assert [e for e in env.log if e == ("story_server", "stop")] == [("story_server", "stop")]
    assert env.lifecycle()[-1] == ("vlm_call", env.attempt(two, 1))
    assert _read(two["output_path"]) == b"img:2:12"
    assert capsys.readouterr().err == "critic: interrupted; stopping the VLM in its own session\n"


def test_ict8c_sigterm_during_judging(env, monkeypatch):
    previous = signal.signal(signal.SIGTERM, signal.SIG_DFL)
    hup = signal.getsignal(signal.SIGHUP)
    try:
        jobs = env.jobs(1)

        def terminate():
            assert signal.getsignal(signal.SIGTERM) is not signal.SIG_DFL, "no SIGTERM handler: not sending it"
            os.kill(os.getpid(), signal.SIGTERM)
            time.sleep(2)
            return verdict(8)

        env.cd.replies[jobs[0]["output_path"]] = [terminate]
        with pytest.raises(KeyboardInterrupt):
            env.run(jobs)
        assert [argv for argv, _kw in env.popens] == [[FakeCD.STORY_SERVER, "stop"]]
        assert ("story_server", "stop") not in env.log
        assert signal.getsignal(signal.SIGTERM) is signal.SIG_DFL and signal.getsignal(signal.SIGHUP) is hup
    finally:
        signal.signal(signal.SIGTERM, previous)


def test_ict8d_a_serving_vlm_is_left_serving(env):
    env.cd.state, env.cd.up = "SERVING mlx-vision", True
    jobs = env.jobs(2, "a")
    two = jobs[1]
    env.cd.replies.update({jobs[0]["output_path"]: [verdict(8)], two["output_path"]: [verdict(3)],
                           env.attempt(two, 1): [verdict(8)]})
    env.run(jobs)
    assert env.lifecycle() == [
        ("run_jobs", [1, 2]), ("story_server_state",), ("vlm_ready",), ("vlm_call", jobs[0]["output_path"]),
        ("vlm_call", two["output_path"]), ("story_server", "stop"), ("wait_for_memory", 20.0, "Fake", "seed-edit"),
        ("run_jobs", [2]), ("vlm_ready",), ("wait_for_avail", 28.0, 600), ("restore_story_server", True),
        ("wait_for_vlm", 600), ("vlm_call", env.attempt(two, 1))]
    env.cd.state, env.cd.up = "SERVING mlx-vision", True
    jobs = env.jobs(2, "b")
    two = jobs[1]
    env.qe.outcomes[(2, ic.critic_seed(12, 1, 2))] = "blocked"
    env.cd.replies.update({jobs[0]["output_path"]: [verdict(8)], two["output_path"]: [verdict(3)]})
    del env.log[:]
    env.run(jobs, rounds=1)
    assert env.lifecycle()[-4:] == [("story_server", "stop"), ("wait_for_memory", 20.0, "Fake", "seed-edit"),
                                    ("run_jobs", [2]), ("restore_story_server", False)]
    assert env.block(2)["status"] == "flagged"


# --- ICT9: blocked outputs are skipped, not judged ------------------------------------------------------------

def test_ict9_blocked_outputs_are_skipped(env, capsys):
    jobs = env.jobs(3, "a")
    env.qe.outcomes[(2, 12)] = "blocked"
    env.cd.replies.update({jobs[0]["output_path"]: [verdict(8)], jobs[2]["output_path"]: [verdict(9)]})
    env.run(jobs)
    assert ("vlm_call", jobs[1]["output_path"]) not in env.log
    assert sorted(set(n for n, _b in env.verdicts)) == [1, 3]
    assert not [line for line in _lines(capsys) if line.startswith("critic 2/3")]
    env.verdicts[:] = []
    (job,) = env.jobs(1, "b")
    seed = ic.critic_seed(11, 1, 1)
    env.qe.outcomes[(1, seed)] = "blocked"
    env.cd.replies[job["output_path"]] = [verdict(3, ["fused hand"])]
    env.run([job], rounds=1)
    block = env.block(1)
    assert (block["status"], block["score"], block["seed_used"]) == ("flagged", 3, 11)
    assert block["attempts"] == [_att(0, 11, 3, ["fused hand"]),
                                 _att(1, seed, None, note="blocked by the content screen")]
    assert [b["attempts"][-1]["note"] for _n, b in env.verdicts] == [None, "blocked by the content screen",
                                                                      "blocked by the content screen"]
    assert _read(job["output_path"]) == b"img:1:11"
    assert [line for line in _lines(capsys) if line.startswith("critic 1/1")] == [
        "critic 1/1: redo (score 3: fused hand)", "critic 1/1: flagged (best score 3 of 2 attempts: fused hand)"]


# --- Review Focus 2: an unparseable last attempt still ends flagged, with the earlier best kept ---------------------

def test_ic_review_focus_2_an_unparseable_last_attempt_still_flags(env, capsys):
    (job,) = env.jobs(1)
    env.cd.replies.update({job["output_path"]: [verdict(4, ["warped face"])], env.attempt(job, 1): ["nope", "nope"]})
    assert env.run([job], rounds=1)[1] is None
    block = env.block(1)
    assert (block["status"], block["score"], block["seed_used"]) == ("flagged", 4, 11)
    assert block["attempts"][1]["note"] == "not judged: unparseable: no JSON object found in text"
    assert _read(job["output_path"]) == b"img:1:11" and env.bests == []
    assert [line for line in _lines(capsys) if line.startswith("critic 1/1")] == [
        "critic 1/1: redo (score 4: warped face)", "critic 1/1: flagged (best score 4 of 2 attempts: warped face)"]


# --- ICT10: nothing to judge ----------------------------------------------------------------------------------

def test_ict10_nothing_to_judge(env, capsys):
    jobs = env.jobs(2, "a")
    env.qe.failure[0] = "Fake child exited 1: boom"
    assert env.run(jobs) == env.qe.returns[0]
    assert env.lifecycle() == [("run_jobs", [1, 2])] and env.verdicts == []
    assert _lines(capsys) == ["critic: not run; the job batch failed"]
    jobs = env.jobs(2, "b")
    env.qe.outcomes.update({(1, 11): "blocked", (2, 12): "blocked"})
    got = env.run(jobs)
    assert got == env.qe.returns[1] and got[1] is None
    assert env.lifecycle() == [("run_jobs", [1, 2]), ("run_jobs", [1, 2])] and env.verdicts == []
    assert _lines(capsys) == ["critic: not run; no job produced an image"]
    assert not os.path.exists(os.path.join(env.work, "critic"))


# --- ICT11: the redo is not run ---------------------------------------------------------------------------------

def test_ict11_the_redo_is_not_run(env, capsys):
    (job,) = env.jobs(1, "a")
    env.cd.replies[job["output_path"]] = [verdict(3)]
    env.qe.wait_error = FakeQE.Unavailable("x")
    env.run([job])
    assert len(env.qe.calls) == 1 and env.block(1)["status"] == "flagged"
    assert "critic: redo round 1 of 2 not run: x" in _lines(capsys)
    env.qe.wait_error = None
    (job,) = env.jobs(1, "b")
    env.cd.replies[job["output_path"]] = [verdict(3)]
    env.cd.stop_rc = 3
    env.run([job])
    assert len(env.qe.calls) == 2 and env.block(1)["status"] == "flagged"
    captured = capsys.readouterr()
    assert "critic: redo round 1 of 2 not run: bin/story-server stop exited 3" in captured.out.splitlines()
    assert captured.err == "critic: warning: bin/story-server stop exited 3; the VLM may still hold its memory\n"


# --- ICT12: bin/image-critic ----------------------------------------------------------------------------------

def _cli():
    loader = importlib.machinery.SourceFileLoader("image_critic_cli", os.path.join(WS, "bin", "image-critic"))
    spec = importlib.util.spec_from_loader("image_critic_cli", loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def _files(env, *names):
    paths = []
    for name in names:
        path = os.path.join(env.tmp, name)
        with open(path, "wb") as f:
            f.write(b"png")
        paths.append(path)
    return paths


def test_ict12_the_calibration_cli(env, capsys):
    cli = _cli()
    assert cli.ic is ic
    a, b, c, seed = _files(env, "a.png", "b.png", "c.png", "seed.png")
    env.cd.up = True
    env.cd.replies.update({a: [verdict(8, ["small hand"], "fine")], b: [verdict(4, [], "")], c: ["x", "y"]})
    assert cli.main(["score", a, b]) == 0
    assert capsys.readouterr().out.splitlines() == ["%s: score 8 PASS: small hand -- fine" % a,
                                                    "%s: score 4 FAIL: no defect named -- -" % b,
                                                    "pass score 7: 1 pass, 1 fail, 0 unjudged"]
    env.cd.calls = {}
    assert cli.main(["score", a, b, "--pass-score", "9", "--json"]) == 0
    rows = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert rows == [{"path": a, "score": 8, "verdict": "fail", "defects": ["small hand"], "reason": "fine",
                     "error": None},
                    {"path": b, "score": 4, "verdict": "fail", "defects": [], "reason": "", "error": None}]
    env.cd.calls = {}
    del env.cd.parts[:]
    assert cli.main(["score", a, c, "--seed", seed]) == 1
    assert capsys.readouterr().out.splitlines() == [
        "%s: score 8 PASS: small hand -- fine" % a, "%s: UNJUDGED: unparseable: no JSON object found in text" % c,
        "pass score 7: 1 pass, 0 fail, 1 unjudged"]
    assert env.cd.parts[0][1] == {"type": "image_url", "image_url": {"url": "data:" + seed}}
    env.cd.calls = {}
    env.cd.replies[b] = [OSError("refused")]
    assert cli.main(["score", b, a, "--json"]) == 1
    rows = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert [(r["verdict"], r["score"], r["error"]) for r in rows] == [
        ("unjudged", None, "VLM request failed: OSError: refused")] * 2
    assert a not in env.cd.calls
    del env.log[:]
    missing = os.path.join(env.tmp, "missing.png")
    assert cli.main(["score", a, missing]) == 2
    assert capsys.readouterr().err == "Error: %s is not a file\n" % missing
    assert cli.main(["score", a, "--seed", missing]) == 2
    assert capsys.readouterr().err == "Error: %s is not a file\n" % missing
    assert ("vlm_ready",) not in env.log
    assert cli.main(["score", a, "--pass-score", "11"]) == 2
    assert capsys.readouterr().err == "Error: --pass-score must be an integer from 1 to 10\n"
    env.cd.up = False
    assert cli.main(["score", a]) == 2
    assert capsys.readouterr().err == (
        "Error: the VLM is not serving at %s; start it with bin/story-server mlx-vision\n" % MODELS_URL)
    with pytest.raises(SystemExit) as e:
        cli.main([])
    assert e.value.code == 2


# --- ICT13: import hygiene ------------------------------------------------------------------------------------

def test_ict13_import_hygiene(tmp_path):
    with open(os.path.join(WS, "image_critic.py"), encoding="utf-8") as f:
        source = f.read()
    assert re.findall(r"^(?:import|from)\s+([A-Za-z_][\w.]*)", source, re.M) == [
        "glob", "hashlib", "os", "re", "shutil", "signal", "subprocess", "sys", "threading"]
    proc = subprocess.run([sys.executable, "-B", "-X", "importtime", "-c", "import image_critic"], cwd=WS,
                          capture_output=True, text=True, timeout=60, env=dict(os.environ, HOME=str(tmp_path)))
    assert proc.returncode == 0, proc.stderr
    imported = set(line.rsplit("|", 1)[1].strip().split(".")[0] for line in proc.stderr.splitlines()
                   if line.startswith("import time:") and line.count("|") == 2)
    assert "image_critic" in imported
    assert not imported & {"character_dataset", "PIL", "psutil"}, sorted(imported)
    with open(os.path.join(WS, "bin", "image-critic"), encoding="utf-8") as f:
        cli = f.read()
    assert re.findall(r"^(?:import|from)\s+([A-Za-z_][\w.]*)", cli, re.M) == [
        "argparse", "json", "os", "sys", "image_critic"]
    assert os.stat(os.path.join(WS, "bin", "image-critic")).st_mode & 0o111 == 0o111
