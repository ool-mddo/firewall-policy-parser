import logging
import os

import requests
from flask import Flask, jsonify, request
from flask.logging import create_logger

import collect_configs as cc
import parse_fw_policy as pfp

app = Flask(__name__)
app_logger = create_logger(app)
logging.basicConfig(level=logging.DEBUG)

MODEL_CONDUCTOR_HOST = os.environ.get("MODEL_CONDUCTOR_HOST", "model-conductor:9292")


@app.route("/fw_policy/<network>/<snapshot>/parsed_result", methods=["POST"])
def post_parsed_result(network: str, snapshot: str):
    app_logger.info("POST parsed_result start: network=%s, snapshot=%s", network, snapshot)

    body = request.get_json(silent=True) or {}
    node_pairs = body.get("node_pairs", [])

    cc.cleanup_snapshot_dir(network, snapshot)
    copy_targets = cc.collect_configs(network, snapshot, node_pairs)
    parsed_nodes = pfp.parse_fw_configs(network, snapshot, copy_targets)

    app_logger.info("POST parsed_result end: network=%s, snapshot=%s, parsed=%s", network, snapshot, parsed_nodes)
    return jsonify({"parsed": parsed_nodes})


@app.route("/fw_policy/<network>/<snapshot>/topology", methods=["POST"])
def post_topology(network: str, snapshot: str):
    app_logger.info("POST topology start: network=%s, snapshot=%s", network, snapshot)

    node_fw_attributes = pfp.collect_node_fw_attributes(network, snapshot)
    if not node_fw_attributes["node"]:
        app_logger.info("POST topology end: network=%s, snapshot=%s, no parsed results found", network, snapshot)
        return jsonify({"error": "No parsed results found"}), 404

    url = f"http://{MODEL_CONDUCTOR_HOST}/conduct/{network}/{snapshot}/topology/layer3/policies"
    resp = requests.post(url, json=node_fw_attributes)

    app_logger.info("POST topology end: network=%s, snapshot=%s, status=%d", network, snapshot, resp.status_code)
    return jsonify(resp.json()), resp.status_code


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
