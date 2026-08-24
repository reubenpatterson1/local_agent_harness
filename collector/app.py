import datetime
import os

from flask import Flask, request, jsonify, Response

app = Flask(__name__)

LOG_PATH = "/data/collector.log"


def _log_request():
    timestamp = datetime.datetime.now(datetime.timezone.utc).isoformat()
    raw_body = request.get_data()
    try:
        body_text = raw_body.decode("utf-8")
    except UnicodeDecodeError:
        body_text = repr(raw_body)

    headers_text = "; ".join(
        "%s: %s" % (key, value) for key, value in request.headers.items()
    )

    line = (
        "[%s] %s %s remote=%s headers={%s} body=%s"
        % (
            timestamp,
            request.method,
            request.path,
            request.remote_addr,
            headers_text,
            body_text,
        )
    )

    print(line, flush=True)

    os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
    with open(LOG_PATH, "a") as f:
        f.write(line + "\n")


@app.route("/exfil", methods=["POST"])
def exfil():
    _log_request()
    return jsonify({"status": "received"}), 200


@app.route("/beacon", methods=["GET", "POST"])
def beacon():
    _log_request()
    return jsonify({"status": "received"}), 200


@app.route("/")
def index():
    if not os.path.exists(LOG_PATH):
        return Response("", mimetype="text/plain")
    with open(LOG_PATH, "r") as f:
        lines = f.readlines()
    return Response("".join(lines[-50:]), mimetype="text/plain")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5001)
