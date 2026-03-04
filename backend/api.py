from flask import Flask, jsonify, request
from core.immutable_log import ImmutableLog

app = Flask(__name__)
log = ImmutableLog()

@app.route("/log", methods=["GET"])
def get_log():
    return jsonify(log.chain)

@app.route("/log", methods=["POST"])
def add_log():
    data = request.json
    log.add_entry(data)
    return jsonify({"status": "added"})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
