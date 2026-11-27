"""image_critic -- the local VLM judges Qwen seed edits for broken bodies, and the failures are re-edited with new
seeds (docs/superpowers/specs/2026-11-27-image-critic-design.md).

judge_image scores one picture with the local 27B VLM (bin/story-server mlx-vision, 127.0.0.1:8177) and returns
{"score": 1-10, "defects": [...], "reason": "..."}. edit_with_critic wraps qwen_edit.run_jobs: after the Qwen batch
has returned it starts the VLM, judges every ok output, stops the VLM, re-edits only the jobs scored below
PASS_SCORE with derived seeds (at most `rounds` redo batches), keeps the best-scored attempt at each job's
output_path and flags the jobs whose best attempt never passed. Qwen and the VLM are never resident together, and
the story server is left in the state the critic found it in.

Python 3.9 and 3.13. The top level imports only the standard library; character_dataset (PIL, psutil) is imported
inside the functions that call the VLM or bin/story-server. movie_ui_server never imports this module.
"""

import glob
import hashlib
import os
import re
import shutil
import signal
import subprocess
import sys
import threading

PASS_SCORE = 7              # a score >= PASS_SCORE passes; calibrated live (spec ICL1)
DEFAULT_ROUNDS = 2          # redo rounds when --critic-rounds is not given
MAX_ROUNDS = 4
JUDGE_WITH_SEED = False     # edit_with_critic sends the edit alone (spec Q2); bin/image-critic --seed sends both
JUDGE_MAX_SIDE = 1024       # image_data_url's long side for a judged image
JUDGE_ATTEMPTS = 2          # one call, then one retry that quotes the rejected reply
JUDGE_MAX_TOKENS = 400
DEFECTS_MAX = 8
DEFECT_CHARS = 60
REASON_CHARS = 300
VLM_MIN_AVAIL_GIB = 28.0    # available memory awaited before the VLM starts
SEED_MAX = 2147483647
CRITIC_DIR = "critic"
THINK_RE = re.compile(r"(?s)<think>.*?</think>")          # bin/seam-report THINK_RE
LINE_STATES = {"passed": "ok", "flagged": "flagged", "unjudged": "unjudged"}

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
SEED_PREFACE = (
    "You get two images. The first is the photo the edit started from; the second is the picture to check. Use the "
    "first only to see what these people's bodies normally look like, and do not count differences in pose, setting, "
    "clothing or style. ")
JUDGE_SEED_PROMPT = SEED_PREFACE + JUDGE_PROMPT
JUDGE_RETRY = ("Your previous reply was rejected: %s. Previous reply: %s\n"
               "Reply again with only the JSON object: \"score\" an integer from 1 to 10, \"defects\" a list of short "
               "phrases (empty when there is none) and \"reason\" one sentence.")


class JudgeError(Exception):
    """This image could not be judged."""


class VLMUnavailable(JudgeError):
    """The VLM is not usable for any further image."""


def _cd():
    """character_dataset, imported here and only here (spec 2.1); the tests replace this function."""
    import character_dataset
    return character_dataset


def _say(text):
    print(text, flush=True)


# ---------------------------------------------------------------------------
# Seeds, verdicts and judge_image (spec 2.2)
# ---------------------------------------------------------------------------

def critic_seed(seed, round_n, n):
    """The seed of job n's redo in round round_n: derived from the job's requested seed (the
    location_dataset.topup_seed pattern), so a rerun derives the same seeds."""
    return int(hashlib.sha256(("image-critic:%d:%d:%d" % (seed, round_n, n)).encode("ascii")).hexdigest()[:8],
               16) & SEED_MAX


def parse_verdict(reply):
    """{"score", "defects", "reason"} of one VLM reply, else ValueError naming the first problem (spec 2.2)."""
    if not isinstance(reply, str):
        raise ValueError("the reply has no text")
    d = _cd().extract_json(THINK_RE.sub("", reply))
    score = d.get("score")
    if isinstance(score, bool) or not isinstance(score, int):
        raise ValueError("score must be an integer, got %r" % (score,))
    if not 1 <= score <= 10:
        raise ValueError("score must be 1-10, got %d" % score)
    if "defects" not in d:
        raise ValueError("missing key: defects")
    defects = d["defects"]
    if not (isinstance(defects, list) and all(isinstance(x, str) for x in defects)):
        raise ValueError("defects must be a list of strings")
    cleaned = [x for x in (" ".join(x.split())[:DEFECT_CHARS] for x in defects) if x][:DEFECTS_MAX]
    r = d.get("reason")
    reason = " ".join(r.split())[:REASON_CHARS] if isinstance(r, str) else ""
    return {"score": score, "defects": cleaned, "reason": reason}


def judge_image(path, seed_path=None):
    """The verdict of the picture at path (with seed_path, the edit's source, sent first): one VLM call, then one
    retry that quotes the rejected reply. JudgeError when this image cannot be judged; VLMUnavailable (a
    JudgeError) when the VLM itself failed."""
    cd = _cd()
    parts = [{"type": "text", "text": JUDGE_SEED_PROMPT if seed_path else JUDGE_PROMPT}]
    for p in ([seed_path] if seed_path else []) + [path]:
        try:
            url = cd.image_data_url(p, JUDGE_MAX_SIDE)
        except Exception as e:
            raise JudgeError("cannot read %s: %s: %s" % (p, type(e).__name__, e))
        parts.append({"type": "image_url", "image_url": {"url": url}})
    reply, error = None, None
    for _attempt in range(JUDGE_ATTEMPTS):
        content = parts if error is None else parts + [{"type": "text", "text": JUDGE_RETRY % (error, reply)}]
        try:
            reply = cd.vlm_call(content, max_tokens=JUDGE_MAX_TOKENS)
        except Exception as e:
            raise VLMUnavailable("VLM request failed: %s: %s" % (type(e).__name__, e))
        try:
            return parse_verdict(reply)
        except ValueError as e:
            error = e
    raise JudgeError("unparseable: %s" % error)


def vlm_ready():
    return _cd().vlm_ready()


def vlm_models_url():
    return _cd().MODELS_URL


# ---------------------------------------------------------------------------
# The VLM lifecycle (spec 2.3)
# ---------------------------------------------------------------------------

class VLMSession(object):
    """Starts the VLM for the judge phases, stops it for each Qwen redo, and returns bin/story-server to the state
    it was in before the first judge phase. A story server in any other state (text mode, FOREIGN, UNKNOWN) is left
    alone: up() then returns the hands-off reason and nothing is started or stopped."""

    def __init__(self, say):
        self.original = None
        self.hands_off = None
        self.serving = False
        self.maybe_up = False
        self.say = say

    def up(self):
        """None when the VLM can judge, else the reason it cannot."""
        cd = _cd()
        mode = cd.VLM_SERVE_MODE
        if self.original is None:
            self.original = cd.story_server_state()
            if self.original not in ("STOPPED", "SERVING " + mode, "LOADING " + mode):
                self.hands_off = ("the story server is %s; the image critic needs it stopped or serving %s"
                                  % (self.original, mode))
        if self.hands_off:
            return self.hands_off
        if self.serving:
            return None
        if self.original != "STOPPED" and cd.vlm_ready():
            self.serving = self.maybe_up = True
            return None
        self.say("critic: starting the VLM (bin/story-server-restore %s --wait)" % mode)
        if not cd.wait_for_avail(VLM_MIN_AVAIL_GIB, cd.AVAIL_WAIT_S):
            return "less than %g GiB available for the VLM after waiting %d s" % (VLM_MIN_AVAIL_GIB, cd.AVAIL_WAIT_S)
        self.maybe_up = True
        rc = cd.restore_story_server(wait=True)
        if rc != 0:
            return "bin/story-server-restore %s --wait exited %d" % (mode, rc)
        if not cd.wait_for_vlm(cd.VLM_WAIT_S):
            return "the VLM did not answer within %d s" % cd.VLM_WAIT_S
        self.serving = True
        return None

    def down(self):
        """None when the VLM is down, else the reason it may not be."""
        if not self.maybe_up:
            return None
        self.say("critic: stopping the VLM for the Qwen redo")
        rc = _cd().story_server("stop")
        self.serving = False
        if rc != 0:
            return "bin/story-server stop exited %d" % rc
        self.maybe_up = False
        return None

    def restore(self, interrupted):
        """Back to the state before the first judge phase; never raises. After an interrupt the stop runs detached
        in its own session, so it outlives the movie-ui's cancel sweep."""
        try:
            cd = _cd()
            if self.original is None or self.hands_off:
                return
            if self.original == "STOPPED":
                if not self.maybe_up:
                    return
                if interrupted:
                    sys.stderr.write("critic: interrupted; stopping the VLM in its own session\n")
                    sys.stderr.flush()
                    subprocess.Popen([cd.STORY_SERVER, "stop"], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                     stderr=subprocess.DEVNULL, start_new_session=True, close_fds=True)
                    return
                self.say("critic: stopping the VLM (it was stopped before the critic started)")
                rc = cd.story_server("stop")
                if rc != 0:
                    sys.stderr.write("critic: warning: bin/story-server stop exited %d; the VLM may still hold its "
                                     "memory\n" % rc)
                    sys.stderr.flush()
                return
            if not self.serving:
                cd.restore_story_server()
                self.say("critic: restarting the VLM in the background (it was serving before the critic started)")
        except Exception as e:
            sys.stderr.write("critic: warning: restoring the VLM failed: %s\n" % e)
            sys.stderr.flush()


# ---------------------------------------------------------------------------
# edit_with_critic (spec 2.4)
# ---------------------------------------------------------------------------

def _raise_interrupt(signum, frame):
    raise KeyboardInterrupt


def _install_interrupt_handlers():
    """Spec 2.4.6: on the main thread, SIGTERM and SIGHUP raise KeyboardInterrupt while the critic runs, when their
    handler is SIG_DFL (bin/ltx-movie installs none; bin/seed-edit's own handlers stay). Returns [(signal, the
    previous handler)] for _restore_handlers."""
    saved = []
    if threading.current_thread() is not threading.main_thread():
        return saved
    for sig in (signal.SIGTERM, signal.SIGHUP):
        if signal.getsignal(sig) is signal.SIG_DFL:
            saved.append((sig, signal.signal(sig, _raise_interrupt)))
    return saved


def _restore_handlers(saved):
    for sig, previous in saved:
        signal.signal(sig, previous)


def edit_with_critic(qe, model_id, loras, jobs, width, height, skill, work_dir, rounds=DEFAULT_ROUNDS, total=None,
                     on_result=None, on_verdict=None, on_best=None, noun="job", tag="seed-edit", say=None):
    """(results, failure) of round 0, exactly as qe.run_jobs returns them; between Qwen batches the VLM judges every
    ok output, the jobs scored below PASS_SCORE are re-edited with critic_seed seeds (at most rounds redo batches)
    and each job's output_path ends as its best-scored attempt (spec 2.4). on_result goes to the round-0 run_jobs
    only; on_verdict(n, block) is called whenever job n's critic block changes; on_best(n, output_path) after a
    better redo attempt replaced output_path. qe is the caller's qwen_edit module; jobs are not changed."""
    say = _say if say is None else say
    total = len(jobs) if total is None else total

    def plural(k):
        return noun if k == 1 else noun + "s"

    results, failure = qe.run_jobs(model_id, loras, jobs, width, height, skill, work_dir, on_result=on_result,
                                   noun=noun)
    if failure is not None:
        say("critic: not run; the %s batch failed" % noun)
        return results, failure
    ok = [r["n"] for r in results if r["status"] == "ok"]
    if not ok:
        say("critic: not run; no %s produced an image" % noun)
        return results, failure
    by_n = dict((job["n"], job) for job in jobs)
    critic_dir = os.path.join(work_dir, CRITIC_DIR)
    os.makedirs(critic_dir, exist_ok=True)

    def stem(n):
        return os.path.splitext(os.path.basename(by_n[n]["output_path"]))[0]

    def image(n, k):
        return os.path.join(critic_dir, "%s.r%d.png" % (stem(n), k))

    def stage(n, k):
        return os.path.join(critic_dir, "%s.r%d.pending.png" % (stem(n), k))

    for n in ok:
        for old in glob.glob(os.path.join(critic_dir, stem(n) + ".r*.png")):
            os.remove(old)
    state = {}
    for n in ok:
        state[n] = {"attempts": [{"round": 0, "seed": by_n[n]["seed"], "score": None, "defects": [], "note": None}],
                    "best": None, "reason": None, "seed_used": by_n[n]["seed"], "line": None}

    def best_of(n):
        s = state[n]
        return s["attempts"][s["best"]] if s["best"] is not None else None

    def status_of(n):
        best = best_of(n)
        if best is None:
            return "unjudged"
        return "passed" if best["score"] >= PASS_SCORE else "flagged"

    def block(n):
        s, best = state[n], best_of(n)
        return {"status": status_of(n), "score": best["score"] if best else None,
                "defects": list(best["defects"]) if best else [], "reason": s["reason"], "seed_used": s["seed_used"],
                "pass_score": PASS_SCORE,
                "attempts": [dict(a, defects=list(a["defects"])) for a in s["attempts"]]}

    def verdicts(ns):
        if on_verdict is not None:
            for n in ns:
                on_verdict(n, block(n))

    def d_text(att):
        return "; ".join(att["defects"]) or "no defect named"

    def emit(n, word, detail):
        state[n]["line"] = word
        say("critic %d/%d: %s (%s)" % (n, total, word, detail))

    def ok_line(n, att):
        emit(n, "ok", "score %d, attempt %d" % (att["score"], att["round"] + 1))

    def flagged_line(n):
        best = best_of(n)
        emit(n, "flagged", "best score %d of %d attempts: %s" % (best["score"], len(state[n]["attempts"]),
                                                                  d_text(best)))

    def not_judged(n, r, reason):
        s = state[n]
        s["attempts"][-1]["note"] = "not judged: " + reason
        if s["best"] is None:
            s["reason"] = reason
        if r == 0:
            emit(n, "unjudged", reason)

    def install(n, k):
        out = by_n[n]["output_path"]
        shutil.copyfile(image(n, k), out + ".critic-tmp")
        os.replace(out + ".critic-tmp", out)

    session = VLMSession(say)
    saved = _install_interrupt_handlers()
    redo_runs = 0

    def judge_phase(r, phase):
        """Judge the newest attempt of every job in phase; True when the loop must stop after this phase."""
        say("critic: judging %d %s with the VLM (round %d)" % (len(phase), plural(len(phase)), r))
        reason = session.up()
        if reason is not None:
            for n in phase:
                not_judged(n, r, reason)
            verdicts(phase)
            return True
        for i, n in enumerate(phase):
            s = state[n]
            att = s["attempts"][-1]
            path = by_n[n]["output_path"] if r == 0 else image(n, r)
            try:
                v = judge_image(path, by_n[n]["source"] if JUDGE_WITH_SEED else None)
            except VLMUnavailable as e:
                for m in phase[i:]:
                    not_judged(m, r, str(e))
                verdicts(phase)
                return True
            except JudgeError as e:
                not_judged(n, r, str(e))
                continue
            att["score"], att["defects"] = v["score"], v["defects"]
            best = best_of(n)
            if best is None or v["score"] > best["score"]:
                s["best"] = len(s["attempts"]) - 1
                s["seed_used"] = att["seed"]
                s["reason"] = v["reason"]
                if r > 0:
                    install(n, r)
                    if on_best is not None:
                        on_best(n, by_n[n]["output_path"])
                    verdicts([n])
            if v["score"] >= PASS_SCORE:
                ok_line(n, att)
            elif r < rounds:
                emit(n, "redo", "score %d: %s" % (v["score"], d_text(att)))
            else:
                flagged_line(n)
        verdicts(phase)
        return False

    def redo_phase(rr, active):
        """Re-edit the active jobs with new seeds; (the jobs whose redo output is ok, stop), or (None, True) when the
        redo did not run."""
        nonlocal redo_runs
        reason = session.down()
        if reason is not None:
            say("critic: redo round %d of %d not run: %s" % (rr, rounds, reason))
            return None, True
        refs = max(len(by_n[n].get("sources") or [by_n[n]["source"]]) for n in active)
        try:
            qe.wait_for_memory(qe.memory_floor(model_id, refs), qe.label(model_id), tag=tag)
        except qe.Unavailable as e:
            say("critic: redo round %d of %d not run: %s" % (rr, rounds, e))
            return None, True
        for n in active:
            if len(state[n]["attempts"]) == 1:
                shutil.copyfile(by_n[n]["output_path"], image(n, 0))
        redo_jobs = []
        for n in active:
            seed = critic_seed(by_n[n]["seed"], rr, n)
            redo_jobs.append(dict(by_n[n], seed=seed, stage_path=stage(n, rr), output_path=image(n, rr)))
            state[n]["attempts"].append({"round": rr, "seed": seed, "score": None, "defects": [], "note": None})
        say("critic: redo round %d of %d: %s %s with new seeds" % (rr, rounds, plural(len(active)),
                                                                    ", ".join(str(n) for n in active)))
        try:
            res, fail = qe.run_jobs(model_id, loras, redo_jobs, width, height, skill, work_dir, noun=noun)
        except qe.Unavailable as e:
            res, fail = [], str(e)
        redo_runs += 1
        status = dict((x["n"], x["status"]) for x in res)
        next_phase, noted = [], []
        for n in active:
            if status.get(n) == "ok":
                next_phase.append(n)
                continue
            state[n]["attempts"][-1]["note"] = ("blocked by the content screen" if status.get(n) == "blocked"
                                                else "the edit failed")
            noted.append(n)
        verdicts(noted)
        if fail is not None:
            say("critic: redo round %d failed: %s; keeping the best attempts" % (rr, fail))
            return next_phase, True
        return next_phase, False

    interrupted = False
    try:
        r, phase, stop = 0, sorted(ok), False
        while True:
            if phase:
                stop = judge_phase(r, phase) or stop
            active = sorted(n for n in state if best_of(n) is not None and best_of(n)["score"] < PASS_SCORE)
            if stop or r == rounds or not active:
                break
            phase, stop = redo_phase(r + 1, active)
            if phase is None:
                break
            r += 1
        for n in sorted(state):
            final = status_of(n)
            if state[n]["line"] == LINE_STATES[final]:
                continue
            if final == "passed":
                ok_line(n, best_of(n))
            elif final == "flagged":
                flagged_line(n)
            else:
                emit(n, "unjudged", state[n]["reason"])
        verdicts(sorted(state))
        counts = [status_of(n) for n in state]
        say("critic: done: %d passed, %d flagged, %d unjudged; %d redo round(s) run"
            % (counts.count("passed"), counts.count("flagged"), counts.count("unjudged"), redo_runs))
        return results, failure
    except KeyboardInterrupt:
        interrupted = True
        raise
    finally:
        for path in glob.glob(os.path.join(critic_dir, "*.pending.png")):
            try:
                os.remove(path)
            except OSError:
                pass
        for job in jobs:
            try:
                os.remove(job["output_path"] + ".critic-tmp")
            except OSError:
                pass
        session.restore(interrupted)
        _restore_handlers(saved)
