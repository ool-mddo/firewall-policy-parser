import logging
from flask import Flask, jsonify, request
from flask.logging import create_logger

import collect_configs as cc
import parse_fw_policy as pfp

app = Flask(__name__)
app_logger = create_logger(app)
logging.basicConfig(level=logging.DEBUG)


@app.route("/fw_policy/<network>/<snapshot>/parsed_result", methods=["POST"])
def post_parsed_result(network: str, snapshot: str):
    body = request.get_json(silent=True) or {}
    node_pairs = body.get("node_pairs", [])

    cc.cleanup_snapshot_dir(network, snapshot)
    copy_targets = cc.collect_configs(network, snapshot, node_pairs)
    parsed_nodes = pfp.parse_fw_configs(network, snapshot, copy_targets)

    return jsonify({"parsed": parsed_nodes})


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
