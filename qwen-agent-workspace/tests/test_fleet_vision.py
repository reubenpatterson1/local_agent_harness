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
