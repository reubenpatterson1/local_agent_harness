"""Vision agent tests for bin/qwen-agentd and the real harness (vision spec Section 7.5).

Run from the workspace root: python3 -m pytest tests/test_fleet_vision.py -v
Loopback only. Every daemon runs with --timing-scale 0.1, explicit beacon targets
and HOME=<tmp dir>; in-process daemons get HOME by monkeypatch. The autouse fixture
SIGKILLs every process group a test started and stops every stub server. No test
contacts a real model server or a qwen-agentd running on this machine.
"""

import base64
import hashlib
import http.client
import http.server
import json
import os
import re
import socket
import stat
import subprocess
import sys
import threading
import time

import pytest

WS = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
sys.path.insert(0, WS)
import fleet_lib  # noqa: E402
import fleet_testutil as ftu  # noqa: E402


@pytest.fixture(autouse=True)
def _reap_processes():
    yield
    ftu.kill_all()


def _hook(tmp_path, kind):
    return ftu.write_hook(os.path.join(str(tmp_path), "hook-%s" % kind), kind)


def _run_body(skill, task, request_id="req-v", images=None, **extra):
    req = {"skill": skill, "task": task, "request_id": request_id}
    if images is not None:
        req["images"] = images
    req.update(extra)
    return json.dumps(req).encode("utf-8")


def _signed_run(port, body, timeout=60):
    status, headers, raw, nonce = ftu.signed(ftu.TEST_KEY, "POST", port, "/run", body, timeout=timeout)
    assert ftu.response_ok(ftu.TEST_KEY, status, "POST", "/run", nonce, headers, raw), status
    return status, raw


def _agent_tmp(home, name):
    return os.path.join(str(home), "agents", name, "tmp")


def _sha(data):
    return hashlib.sha256(data).hexdigest()


PNG_WIRE = ftu.wire(ftu.PNG_BYTES, "image/png")
JPEG_WIRE = ftu.wire(ftu.JPEG_BYTES, "image/jpeg")
CANNED = ftu.CANNED_LINE.encode("utf-8")


# --- POST /run: staging, argv, cleanup, errors, stale directories (V16-V19, V21) ---

def test_vt21_run_stages_private_images_and_passes_them_in_order(tmp_path):
    hook = _hook(tmp_path, "imagestat")
    fleet = ftu.Fleet(tmp_path, names=("bravo",), skills={"bravo": ["vision", "researcher"]},
                      extra_args={"bravo": ["--qwen-agent-bin", hook]}).start()
    port = fleet.ports["bravo"]
    assert _signed_run(port, _run_body("vision", "look", images=[PNG_WIRE, JPEG_WIRE])) == (200, CANNED)
    with open(hook + ".json", encoding="utf-8") as f:
        dumped = json.load(f)
    bravo_url = "http://127.0.0.1:%d/v1" % fleet.server_ports["bravo"]
    assert dumped["argv"][1:6] == ["--skill=vision", "--user-prompt=look", "--base-url=%s" % bravo_url,
                                   "--model=bravo-model", "--model-server-type=ollama"]
    tail = dumped["argv"][6:]
    assert len(tail) == 4 and tail[0::2] == ["--image", "--image"], tail
    agent = os.path.realpath(os.path.join(fleet.homes["bravo"], "agents", "bravo"))
    assert re.fullmatch(re.escape(agent) + r"/tmp/images-[^/]+/image-1\.png", tail[1]), tail
    assert tail[3] == os.path.join(os.path.dirname(tail[1]), "image-2.jpg")
    assert dumped["images"] == [
        {"path": tail[1], "mode": 0o600, "dir_mode": 0o700, "sha256": _sha(ftu.PNG_BYTES)},
        {"path": tail[3], "mode": 0o600, "dir_mode": 0o700, "sha256": _sha(ftu.JPEG_BYTES)}]
    assert not os.path.exists(os.path.dirname(tail[1]))
    tmp = _agent_tmp(fleet.homes["bravo"], "bravo")
    assert stat.S_IMODE(os.stat(tmp).st_mode) == 0o700 and os.listdir(tmp) == []
    assert _signed_run(port, _run_body("researcher", "plain", "req-t")) == (200, CANNED)
    with open(hook + ".json", encoding="utf-8") as f:
        dumped = json.load(f)
    assert dumped["argv"][1:] == ["--skill=researcher", "--user-prompt=plain", "--base-url=%s" % bravo_url,
                                  "--model=bravo-model", "--model-server-type=ollama"]
    assert dumped["images"] == []
    log = fleet.daemons["bravo"].log()
    assert "run start skill=vision request_id=req-v task_chars=4 images=2 image_bytes=%d" % (
        len(ftu.PNG_BYTES) + len(ftu.JPEG_BYTES)) in log
    assert "run start skill=researcher request_id=req-t task_chars=5 images=0 image_bytes=0" in log
    assert "run end skill=vision request_id=req-v http=200 status=ok seconds=" in log


def test_vt22a_run_image_errors_are_signed_and_never_start_a_run(tmp_path):
    hook = _hook(tmp_path, "canned")
    fleet = ftu.Fleet(tmp_path, names=("bravo",), skills={"bravo": ["vision"]},
                      extra_args={"bravo": ["--qwen-agent-bin", hook]}).start()
    port = fleet.ports["bravo"]
    gif = {"media_type": "image/gif", "data": PNG_WIRE["data"]}
    cases = (
        (_run_body("researcher", "t", images=[PNG_WIRE]), b'{"error":"images are only accepted for skill vision"}'),
        (_run_body("vision", "t"), b'{"error":"skill vision requires 1 to 4 images"}'),
        (_run_body("vision", "t", images=[]), b'{"error":"skill vision requires 1 to 4 images"}'),
        (_run_body("vision", "t", images=[gif]), b'{"error":"images[0].media_type must be image/png or image/jpeg"}'),
        (_run_body("vision", "t", images=[PNG_WIRE], x=1), b'{"error":"bad request"}'),
        (_run_body("vision", 5, images=[PNG_WIRE]), b'{"error":"bad request"}'),
    )
    for body, expected in cases:
        assert _signed_run(port, body) == (400, expected), body[:80]
    assert "run start" not in fleet.daemons["bravo"].log()


def test_vt25a_spawn_run_always_removes_the_image_directory(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    agentd = ftu.load_script("qwen_agentd_vision_spawn", ftu.AGENTD)
    d = agentd.Daemon.__new__(agentd.Daemon)
    d.host_id = "bravo"
    d.entry = {"model_server": {"type": "vllm", "url": "http://127.0.0.1:9/v1"}, "model": "m"}
    d.loopback_url = "http://127.0.0.1:9"
    os.makedirs(fleet_lib.log_dir("bravo"))
    tmp = _agent_tmp(home, "bravo")
    images = [("image/png", ftu.PNG_BYTES)]

    d.qwen_agent_bin = _hook(tmp_path, "canned")
    assert d.spawn_run("vision", "t", images) == (200, "ok", CANNED)
    assert os.listdir(tmp) == []
    d.qwen_agent_bin = _hook(tmp_path, "slow")
    assert d.spawn_run("vision", "garbage", images)[0] == 502
    assert os.listdir(tmp) == []
    d.qwen_agent_bin = _hook(tmp_path, "hang")
    monkeypatch.setattr(agentd.fleet_lib, "RUN_TIMEOUT", 2)
    started = time.monotonic()
    assert d.spawn_run("vision", "t", images)[0] == 504
    assert time.monotonic() - started < 10
    assert os.listdir(tmp) == []

    def no_mkdtemp(*args, **kwargs):
        raise OSError("no space")
    monkeypatch.setattr(agentd.tempfile, "mkdtemp", no_mkdtemp)
    assert d.spawn_run("vision", "t", images) == (500, "-", b'{"error":"cannot stage images: OSError"}')
    assert os.listdir(tmp) == []


def test_vt25b_startup_removes_stale_image_directories_only(tmp_path):
    hook = _hook(tmp_path, "canned")
    fleet = ftu.Fleet(tmp_path, names=("bravo",), skills={"bravo": ["vision"]},
                      extra_args={"bravo": ["--qwen-agent-bin", hook]})
    tmp = _agent_tmp(fleet.homes["bravo"], "bravo")
    os.makedirs(os.path.join(tmp, "images-stale"))
    with open(os.path.join(tmp, "images-stale", "image-1.png"), "wb") as f:
        f.write(ftu.PNG_BYTES)
    with open(os.path.join(tmp, "keep.txt"), "w") as f:
        f.write("keep")
    fleet.start()
    assert sorted(os.listdir(tmp)) == ["keep.txt"]
    assert "removed 1 stale image dir(s) from %s" % tmp in fleet.daemons["bravo"].log()


def test_vision_focus_4_loose_agent_tmp_is_tightened_before_staging(tmp_path, monkeypatch):
    """Review Focus 4: A(<id>)/tmp already exists with mode 0755 (made by hand or by a
    restored backup). Expected: the run makes it 0700 before any image is written, the
    image directory is 0700 and its files 0600, and everything is removed afterwards."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    agentd = ftu.load_script("qwen_agentd_vision_focus4", ftu.AGENTD)
    d = agentd.Daemon.__new__(agentd.Daemon)
    d.host_id = "bravo"
    d.entry = {"model_server": {"type": "vllm", "url": "http://127.0.0.1:9/v1"}, "model": "m"}
    d.loopback_url = "http://127.0.0.1:9"
    os.makedirs(fleet_lib.log_dir("bravo"))
    tmp = _agent_tmp(home, "bravo")
    os.makedirs(tmp)
    os.chmod(tmp, 0o755)
    d.qwen_agent_bin = _hook(tmp_path, "imagestat")
    assert d.spawn_run("vision", "t", [("image/jpeg", ftu.JPEG_BYTES)]) == (200, "ok", CANNED)
    with open(d.qwen_agent_bin + ".json", encoding="utf-8") as f:
        dumped = json.load(f)
    assert [(i["mode"], i["dir_mode"]) for i in dumped["images"]] == [(0o600, 0o700)]
    assert dumped["images"][0]["path"].endswith("/image-1.jpg")
    assert stat.S_IMODE(os.stat(tmp).st_mode) == 0o700
    assert os.listdir(tmp) == []


def test_vision_focus_5_second_vision_run_while_one_runs(tmp_path):
    """Review Focus 5: a second image request arrives while a vision run is in progress.
    Expected: a signed 409 busy that stages nothing; the first run's directory is the
    only one present while it runs, and none is left after it ends."""
    hook = _hook(tmp_path, "slow")
    fleet = ftu.Fleet(tmp_path, names=("bravo",), skills={"bravo": ["vision"]},
                      extra_args={"bravo": ["--qwen-agent-bin", hook]}).start()
    port = fleet.ports["bravo"]
    tmp = _agent_tmp(fleet.homes["bravo"], "bravo")
    result = {}
    first = threading.Thread(target=lambda: result.update(
        first=_signed_run(port, _run_body("vision", "one", "req-1", images=[PNG_WIRE]))))
    first.start()
    ftu.wait_until(lambda: os.path.isdir(tmp) and len(os.listdir(tmp)) == 1, 10)
    assert _signed_run(port, _run_body("vision", "two", "req-2", images=[JPEG_WIRE])) == \
        (409, b'{"error":"busy"}')
    assert len(os.listdir(tmp)) == 1
    ftu.release_hook(hook, "one")
    first.join(30)
    assert result["first"] == (200, CANNED)
    assert os.listdir(tmp) == []
    assert "request_id=req-2" not in fleet.daemons["bravo"].log()


# --- request handling order: route caps, prefilter, large-body slots (V11-V13) ---

LARGE = 20971520   # a POST /run Content-Length over MAX_BODY and under MAX_IMAGE_BODY


def _head_only(port, method, path, headers):
    """Send a request head and no body bytes -> (status, response headers, body, seconds)."""
    started = time.monotonic()
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    try:
        conn.putrequest(method, path, skip_accept_encoding=True)
        for name, value in headers.items():
            conn.putheader(name, value)
        conn.endheaders()
        resp = conn.getresponse()
        return resp.status, resp.headers, resp.read(), time.monotonic() - started
    finally:
        conn.close()


def _prefilter_headers(ts=None, nonce=None, sig=None, length=LARGE):
    """Headers that pass prefilter_request (fresh nonce, current ts, any 64-hex sig) unless overridden."""
    return {"Content-Length": str(length), "Content-Type": "application/json",
            "X-Fleet-Ts": str(int(time.time()) if ts is None else ts),
            "X-Fleet-Nonce": nonce or os.urandom(16).hex(),
            "X-Fleet-Sig": sig or os.urandom(32).hex()}


def _sized_wire(magic, size, media_type):
    return ftu.wire(magic + b"\x00" * (size - len(magic)), media_type)


def _two_mib_vision_body(request_id):
    """A vision /run body of about 2.7 MB: two 1,000,000-byte images (over MAX_BODY)."""
    body = _run_body("vision", "look", request_id, images=[
        _sized_wire(b"\x89PNG\r\n\x1a\n", 1000000, "image/png"),
        _sized_wire(b"\xff\xd8\xff", 1000000, "image/jpeg")])
    assert fleet_lib.MAX_BODY < len(body) < fleet_lib.MAX_IMAGE_BODY
    return body


def _bravo_vision(tmp_path):
    hook = _hook(tmp_path, "canned")
    return ftu.Fleet(tmp_path, names=("bravo",), skills={"bravo": ["vision"]},
                     extra_args={"bravo": ["--qwen-agent-bin", hook]}).start()


def test_vt22b_route_body_caps_and_the_decoded_cap(tmp_path):
    fleet = _bravo_vision(tmp_path)
    port = fleet.ports["bravo"]
    for method, path, length in (("POST", "/run", fleet_lib.MAX_IMAGE_BODY + 1),
                                 ("POST", "/delegate", fleet_lib.MAX_IMAGE_BODY + 1),
                                 ("GET", "/health", fleet_lib.MAX_BODY + 1),
                                 ("POST", "/nowhere", fleet_lib.MAX_BODY + 1)):
        status, headers, body, _seconds = _head_only(port, method, path, {"Content-Length": str(length)})
        assert (status, body) == (413, b""), (method, path)
        assert headers.get("X-Fleet-Sig") is None
    half = fleet_lib.MAX_IMAGE_BYTES // 2
    body = _run_body("vision", "t", images=[_sized_wire(b"\x89PNG\r\n\x1a\n", half, "image/png"),
                                            _sized_wire(b"\xff\xd8\xff", half + 1, "image/jpeg")])
    assert fleet_lib.MAX_BODY < len(body) <= fleet_lib.MAX_IMAGE_BODY
    assert _signed_run(port, body, timeout=120) == (413, b'{"error":"images exceed 16777216 bytes in total"}')
    assert "run start" not in fleet.daemons["bravo"].log()


def test_vt23_large_run_is_refused_from_its_headers_alone(tmp_path):
    fleet = _bravo_vision(tmp_path)
    port = fleet.ports["bravo"]
    nonce = os.urandom(16).hex()
    used = fleet_lib.sign_request(ftu.TEST_KEY, "POST", "/run", b"[]", int(time.time()), nonce)
    status, headers, raw = ftu._request(port, "POST", "/run", b"[]",
                                        dict(used, **{"Content-Type": "application/json"}))
    assert (status, raw) == (400, b'{"error":"bad request"}')
    assert ftu.response_ok(ftu.TEST_KEY, status, "POST", "/run", nonce, headers, raw)
    before = fleet.daemons["bravo"].log()
    cases = (
        {"Content-Length": str(LARGE), "Content-Type": "application/json"},
        _prefilter_headers(ts=int(time.time()) - 120),
        _prefilter_headers(sig="zz"),
        dict(used, **{"Content-Length": str(LARGE), "Content-Type": "application/json"}),
    )
    for case in cases:
        status, headers, body, seconds = _head_only(port, "POST", "/run", case)
        assert (status, body) == (401, b""), case
        assert headers.get("X-Fleet-Sig") is None and seconds < 2.0
    assert fleet.daemons["bravo"].log() == before
    assert _signed_run(port, _two_mib_vision_body("req-big")) == (200, CANNED)


def test_vt24_two_large_body_slots_then_503(tmp_path):
    fleet = _bravo_vision(tmp_path)
    port = fleet.ports["bravo"]
    stalled = []
    try:
        for _ in range(2):
            sock = socket.create_connection(("127.0.0.1", port), timeout=10)
            head = "POST /run HTTP/1.0\r\nHost: 127.0.0.1:%d\r\n" % port
            head += "".join("%s: %s\r\n" % item for item in _prefilter_headers().items()) + "\r\n"
            sock.sendall(head.encode("ascii") + b"{")
            stalled.append(sock)
        time.sleep(0.5)
        status, headers, body, seconds = _head_only(port, "POST", "/run", _prefilter_headers())
        assert (status, body) == (503, b"")
        assert headers.get("X-Fleet-Sig") is None and seconds < 2.0
    finally:
        for sock in stalled:
            sock.close()
    deadline = time.monotonic() + 10
    while True:
        status, headers, raw, nonce = ftu.signed(ftu.TEST_KEY, "POST", port, "/run",
                                                 _two_mib_vision_body(os.urandom(4).hex()), timeout=60)
        if status != 503 or time.monotonic() > deadline:
            break
        time.sleep(0.2)
    assert (status, raw) == (200, CANNED)
    assert ftu.response_ok(ftu.TEST_KEY, status, "POST", "/run", nonce, headers, raw)
    assert "http handler error" not in fleet.daemons["bravo"].log()


# --- POST /delegate with images, and a peer's unsigned pre-body answers (V14, V15) ---

def _post_delegate(port, obj):
    status, _headers, raw = ftu._request(port, "POST", "/delegate", json.dumps(obj).encode("utf-8"),
                                         {"Content-Type": "application/json"})
    return status, json.loads(raw)


def test_vt22c_delegate_validates_images_then_forwards_them(tmp_path):
    hook = _hook(tmp_path, "canned")
    fleet = ftu.Fleet(tmp_path, names=("alpha", "bravo"), skills={"bravo": ["vision"]},
                      extra_args={"bravo": ["--qwen-agent-bin", hook]}).start()
    alpha = fleet.ports["alpha"]
    ftu.wait_until(lambda: "bravo" in fleet.peer_ids("alpha"), 4.5)
    assert _post_delegate(alpha, {"skill": "researcher", "task": "t", "host_id": "bravo", "images": []}) == \
        (400, {"error": "images are only accepted for skill vision"})
    assert _post_delegate(alpha, {"skill": "vision", "task": "t", "host_id": "bravo"}) == \
        (400, {"error": "skill vision requires 1 to 4 images"})
    assert _post_delegate(alpha, {"skill": "vision", "task": "t", "host_id": "bravo",
                                  "images": [PNG_WIRE], "x": 1}) == (400, {"error": "bad request"})
    assert _post_delegate(alpha, {"skill": "vision", "task": "t", "host_id": "bravo",
                                  "images": [{"media_type": "image/png", "data": JPEG_WIRE["data"]}]}) == \
        (400, {"error": "images[0] does not match its media_type image/png"})
    assert ftu.delegate(alpha, "vision", "t", "alpha", images=[PNG_WIRE]) == \
        (200, {"outcome": "not_live", "envelope": None, "detail": ""})
    assert "run start" not in fleet.daemons["bravo"].log()
    status, result = ftu.delegate(alpha, "vision", "look", "bravo", images=[PNG_WIRE, JPEG_WIRE])
    assert status == 200 and result["outcome"] == "ok" and result["envelope"]["answer"] == "CANNED"
    assert "images=2 image_bytes=%d" % (len(ftu.PNG_BYTES) + len(ftu.JPEG_BYTES)) in fleet.daemons["bravo"].log()
    assert "delegate skill=vision host=bravo request_id=" in fleet.daemons["alpha"].log()


class _FakeVisionPeer(object):
    """An in-process registered peer 'delta' serving vision. Its signed /health and /skills
    bind it; its /run answers unsigned with an empty body: 503 in mode "slots", 413 in
    mode "cap" (what a real daemon sends before reading a body, vision spec V11)."""

    def __init__(self, port):
        self.mode = "slots"
        self.run_bodies = []
        outer = self

        class Handler(http.server.BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.0"

            def log_message(self, *args):
                pass

            def _reply(self, status, obj):
                raw = fleet_lib.canonical_json(obj)
                headers = fleet_lib.sign_response(ftu.TEST_KEY, status, self.command, self.path,
                                                  self.headers.get("X-Fleet-Nonce"), raw,
                                                  int(time.time()), os.urandom(16).hex())
                self.send_response(status)
                self.send_header("Content-Length", str(len(raw)))
                for name, value in headers.items():
                    self.send_header(name, value)
                self.end_headers()
                self.wfile.write(raw)

            def do_GET(self):
                if self.path == "/health":
                    self._reply(200, {"host_id": "delta", "role": "agent", "version": "dev",
                                      "proto": 1, "discovery": "beacon"})
                else:
                    self._reply(200, {"host_id": "delta", "skills": [
                        {"skill": "vision", "model": "delta-model", "verified": True, "busy": False}]})

            def do_POST(self):
                outer.run_bodies.append(json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0))))
                self.send_response(503 if outer.mode == "slots" else 413)
                self.send_header("Content-Length", "0")
                self.end_headers()

        self.httpd = http.server.ThreadingHTTPServer(("127.0.0.1", port), Handler)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


def test_vt27_unsigned_peer_503_is_busy_and_413_is_peer_error(tmp_path):
    delta_port = ftu.free_port()
    fleet = ftu.Fleet(tmp_path, names=("alpha",), extra_hosts={"delta": {
        "port": delta_port, "model_server": {"type": "vllm", "url": "http://127.0.0.1:9/v1"},
        "model": "delta-model", "skills": ["vision"]}})
    delta = _FakeVisionPeer(delta_port)
    try:
        fleet.start()
        alpha = fleet.ports["alpha"]
        ftu.send_beacon(ftu.TEST_KEY, delta_port, fleet.beacon_ports["alpha"])
        ftu.wait_until(lambda: "delta" in fleet.peer_ids("alpha"), 3.0)
        assert ftu.delegate(alpha, "vision", "t", "delta", images=[PNG_WIRE]) == \
            (200, {"outcome": "busy", "envelope": None, "detail": ""})
        delta.mode = "cap"
        assert ftu.delegate(alpha, "vision", "t", "delta", images=[PNG_WIRE]) == \
            (200, {"outcome": "peer_error", "envelope": None, "detail": "http 413"})
        assert [b["images"] for b in delta.run_bodies] == [[PNG_WIRE], [PNG_WIRE]]
        assert all(set(b) == {"skill", "task", "request_id", "images"} for b in delta.run_bodies)
    finally:
        delta.close()


# --- the real harness round trip, and what reaches logs (V5-V34 end to end, V22, VK5) ---

def _vision_round_trip(tmp_path):
    """alpha (no skills) and bravo (vision, the real bin/qwen-agent child); the real
    harness on alpha's stub delegates a.png and b.jpg to vision -> (fleet, proc)."""
    fleet = ftu.Fleet(tmp_path, names=("alpha", "bravo"), skills={"bravo": ["vision"]},
                      stub_kwargs={"alpha": {"delegate_skill": "vision",
                                             "delegate_images": ["a.png", "b.jpg"]}}).start()
    ftu.wait_until(lambda: fleet_lib.route_candidates("vision", fleet.view("alpha")) == ["bravo"], 4.5)
    caller = tmp_path / "caller"
    ws = caller / "ws"
    ws.mkdir(parents=True)
    (ws / "a.png").write_bytes(ftu.PNG_BYTES)
    (ws / "b.jpg").write_bytes(ftu.JPEG_BYTES)
    env = ftu.clean_env(caller, QWEN_AGENT_DAEMON_URL=fleet.daemons["alpha"].url)
    proc = subprocess.run([sys.executable, ftu.QWEN_AGENT, "--user-prompt=go", "--workspace=%s" % ws,
                           "--base-url=%s" % fleet.stubs["alpha"].url, "--model=alpha-model"],
                          env=env, capture_output=True, text=True, timeout=120)
    return fleet, proc


def _image_parts(request):
    """The content list of the request's user message when it carries images, else None."""
    for message in request.get("messages") or []:
        if message.get("role") == "user" and isinstance(message.get("content"), list):
            return message["content"]
    return None


def test_vt20_harness_delegates_images_to_the_vision_peer(tmp_path):
    fleet, proc = _vision_round_trip(tmp_path)
    assert proc.returncode == 0, proc.stderr
    envelope = json.loads(proc.stdout.strip().splitlines()[-1])
    assert envelope["status"] == "ok" and "BRAVO-ANSWER" in envelope["answer"]
    assert "[delegating to vision on bravo, up to 900s...]" in proc.stderr
    with_images = [r for r in fleet.stubs["bravo"].requests if _image_parts(r) is not None]
    assert len(with_images) == 1
    parts = _image_parts(with_images[0])
    assert [p["type"] for p in parts] == ["text", "image_url", "image_url"]
    urls = [p["image_url"]["url"] for p in parts[1:]]
    assert urls[0].startswith("data:image/png;base64,") and urls[1].startswith("data:image/jpeg;base64,")
    assert base64.b64decode(urls[0].split(",", 1)[1]) == ftu.PNG_BYTES
    assert base64.b64decode(urls[1].split(",", 1)[1]) == ftu.JPEG_BYTES
    assert "tools" not in with_images[0] and "tool_choice" not in with_images[0]
    assert not any("image_url" in json.dumps(r) for r in fleet.stubs["alpha"].requests)
    bravo_log = fleet.daemons["bravo"].log()
    assert re.search(r"run start skill=vision request_id=[0-9a-f]+ task_chars=9 images=2 image_bytes=%d\n"
                     % (len(ftu.PNG_BYTES) + len(ftu.JPEG_BYTES)), bravo_log), bravo_log
    assert re.search(r"run end skill=vision request_id=[0-9a-f]+ http=200 status=ok seconds=", bravo_log)
    assert os.listdir(_agent_tmp(fleet.homes["bravo"], "bravo")) == []


def test_vt26_no_image_bytes_task_text_or_secret_reaches_any_log(tmp_path):
    fleet, proc = _vision_round_trip(tmp_path)
    assert proc.returncode == 0, proc.stderr
    status, delegated = ftu.delegate(fleet.ports["alpha"], "vision", "stub task", "bravo",
                                     images=[PNG_WIRE, JPEG_WIRE])
    assert status == 200 and delegated["outcome"] == "ok", delegated
    blobs = [json.dumps(fleet.view("alpha")).encode(), json.dumps(delegated).encode()]
    for name in fleet.names:
        log_dir = ftu.daemon_log_dir(fleet.homes[name], name)
        for entry in os.listdir(log_dir):
            with open(os.path.join(log_dir, entry), "rb") as f:
                blobs.append(f.read())
    assert os.path.exists(os.path.join(ftu.daemon_log_dir(fleet.homes["bravo"], "bravo"), "last-run.stderr"))
    needles = [ftu.PNG_BYTES, ftu.JPEG_BYTES, b"stub task", ftu.TEST_TOKEN.encode("ascii"), ftu.TEST_KEY,
               fleet_lib.make_join_string(ftu.TEST_FLEET_ID, ftu.TEST_TOKEN).encode("ascii")]
    for wire_image in (PNG_WIRE, JPEG_WIRE):
        needles += [wire_image["data"].encode("ascii"), wire_image["data"][:40].encode("ascii")]
    for blob in blobs:
        for needle in needles:
            assert needle not in blob, needle[:40]
    image_bytes = len(ftu.PNG_BYTES) + len(ftu.JPEG_BYTES)
    assert any(b"images=2 image_bytes=%d" % image_bytes in blob for blob in blobs)
    assert os.listdir(_agent_tmp(fleet.homes["bravo"], "bravo")) == []
