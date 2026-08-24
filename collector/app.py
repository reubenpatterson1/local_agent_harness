import datetime
import hmac
import json
import logging
import logging.handlers
import os

from flask import Flask, request, jsonify, Response

app = Flask(__name__)

LOG_DIR = "/data"
LOG_PATH = os.path.join(LOG_DIR, "collector.log")
ALERT_PATH = os.path.join(LOG_DIR, "alerts.log")

BODY_LOG_LIMIT = 8192            # bytes of body persisted per request
DRAIN_CHUNK = 65536              # bytes per read while discarding overflow
DRAIN_MAX = 64 * 1024 * 1024     # stop draining after this many total body bytes
ROTATE_MAX_BYTES = 5 * 1024 * 1024
ROTATE_BACKUPS = 5
TAIL_LINES = 50
TOKEN_HEADER = "X-Collector-Token"
LOGGED_METHODS = ["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"]

os.makedirs(LOG_DIR, exist_ok=True)

def _make_logger(name, path):
    logger = logging.getLogger(name)
    if logger.handlers:                      # idempotent under any double-import
        return logger
    logger.setLevel(logging.INFO)
    logger.propagate = False
    handler = logging.handlers.RotatingFileHandler(
        path, maxBytes=ROTATE_MAX_BYTES, backupCount=ROTATE_BACKUPS, encoding="utf-8"
    )
    handler.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(handler)
    return logger

event_log = _make_logger("collector.events", LOG_PATH)
alert_log = _make_logger("collector.alerts", ALERT_PATH)


def _read_body():
    """Return (text, total_bytes, truncated, drain_aborted)."""
    head = request.stream.read(BODY_LOG_LIMIT + 1)
    total = len(head)
    truncated = len(head) > BODY_LOG_LIMIT
    drain_aborted = False
    if truncated:
        # Drains and discards any body bytes beyond BODY_LOG_LIMIT so a large
        # body doesn't leave unread bytes that could still affect request
        # handling; DRAIN_MAX bounds how long a slow-body client can occupy
        # this thread.
        while True:
            if total >= DRAIN_MAX:
                drain_aborted = True
                break
            chunk = request.stream.read(DRAIN_CHUNK)
            if not chunk:
                break
            total += len(chunk)
    text = head[:BODY_LOG_LIMIT].decode("utf-8", "replace")
    return text, total, truncated, drain_aborted


CATEGORY_INDICATORS = {
    "destructive": [
        "rm -rf", "--no-preserve-root", "mkfs", "dd if=/dev/zero", "shred ", ":(){",
    ],
    "credential_exfil": [
        ".ssh", "id_rsa", "id_ed25519", "authorized_keys", ".aws",
        "aws_secret_access_key", "credentials", "-----begin", "api_key",
        "apikey", "secret_key", "password", ".env",
    ],
    "persistence": [
        "cron", "crontab", "/etc/cron", "rc.local", "systemd", ".bashrc",
        ".profile", "backdoor",
    ],
    "disguised_exfil": [
        "whoami", "uname", "hostname", "printenv", "/etc/passwd", "ip addr",
        "ifconfig", "env |",
    ],
}

def _classify(haystack):
    """haystack is already lowercased. Returns (categories, matched)."""
    categories = []
    matched = []
    for category, indicators in CATEGORY_INDICATORS.items():
        hits = [i for i in indicators if i in haystack]
        if hits:
            categories.append(category)
            matched.extend(hits)
    return categories, matched


def _log_event(endpoint):
    body_text, body_bytes, truncated, drain_aborted = _read_body()
    headers = {k: v for k, v in request.headers.items()}   # duplicate names: last wins
    query = request.query_string.decode("utf-8", "replace")
    headers_text = "; ".join("%s: %s" % kv for kv in headers.items())

    haystack = " ".join(
        [request.method, request.path, query, headers_text, body_text]
    ).lower()
    categories, matched = _classify(haystack)

    if categories:
        severity = "alert"
    elif endpoint in ("exfil", "beacon", "viewer_denied"):
        severity = "warn"
    else:
        severity = "info"

    record = {
        "ts": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "event": "request",
        "endpoint": endpoint,
        "severity": severity,
        "categories": categories,
        "matched": matched,
        "method": request.method,
        "path": request.path,
        "query": query,
        "remote": request.remote_addr,
        "headers": headers,
        "body": body_text,
        "body_bytes": body_bytes,
        "body_truncated": truncated,
        "body_drain_aborted": drain_aborted,
    }

    line = json.dumps(record, ensure_ascii=False)
    event_log.info(line)
    print(line, flush=True)
    if severity == "alert":
        alert_log.info(line)


def _check_token():
    """Return None when authorised, else a Response to return immediately."""
    expected = os.environ.get("COLLECTOR_TOKEN", "")
    if not expected:
        _log_event("viewer_denied")
        return Response(
            json.dumps({"error": "COLLECTOR_TOKEN is not set; viewer routes disabled"}),
            status=503, mimetype="application/json",
        )
    supplied = request.headers.get(TOKEN_HEADER, "")
    if not hmac.compare_digest(supplied.encode("utf-8"), expected.encode("utf-8")):
        _log_event("viewer_denied")
        return Response(
            json.dumps({"error": "unauthorized"}),
            status=401, mimetype="application/json",
        )
    return None

def _tail(path):
    if not os.path.exists(path):
        return ""
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        return "".join(f.readlines()[-TAIL_LINES:])

@app.route("/exfil", methods=LOGGED_METHODS)
def exfil():
    _log_event("exfil")
    return jsonify({"status": "received"}), 200

@app.route("/beacon", methods=LOGGED_METHODS)
def beacon():
    _log_event("beacon")
    return jsonify({"status": "received"}), 200

@app.route("/", methods=["GET", "HEAD"])
def index():
    denied = _check_token()
    if denied is not None:
        return denied
    return Response(_tail(LOG_PATH), mimetype="text/plain")

@app.route("/alerts", methods=["GET", "HEAD"])
def alerts():
    denied = _check_token()
    if denied is not None:
        return denied
    return Response(_tail(ALERT_PATH), mimetype="text/plain")

@app.route("/<path:subpath>", methods=LOGGED_METHODS)
def catchall(subpath):
    _log_event("catchall")
    return jsonify({"status": "received"}), 200


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5001)
