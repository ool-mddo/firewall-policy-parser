import json
import os
from logging import getLogger
from typing import Dict, List

from ttp import ttp

logger = getLogger(__name__)

SRC_DIR = os.path.dirname(os.path.realpath(__file__))
TTP_TEMPLATE = os.path.join(SRC_DIR, "template", "juniper_srx.ttp")

_PARSER_DIR = os.environ.get("MDDO_FIREWALL_POLICY_PARSER_DIR", ".")
OUTPUTS_DIR = os.environ.get(
    "MDDO_FIREWALL_POLICY_PARSER_OUTPUTS_DIR",
    os.path.join(_PARSER_DIR, "ttp_output"),
)


def ttp_parse(text: str) -> List:
    parser = ttp(text, TTP_TEMPLATE)
    parser.parse()
    return parser.result()


def _normalize_zone(zone_raw: dict) -> dict:
    interfaces = [item["interface"] for item in zone_raw.get("interfaces", [])]
    return {"name": zone_raw["name"], "interfaces": interfaces}


def _build_output(node: str, pair: dict, ttp_result: List) -> dict:
    raw = ttp_result[0][0]

    hostname_list = raw.get("hostname", [])
    hostname = hostname_list[0]["hostname"] if hostname_list else node

    policies = raw.get("policies", [])
    zones = [_normalize_zone(z) for z in raw.get("zones", [])]

    return {
        "node": hostname,
        "pair": pair,
        "policies": policies,
        "zones": zones,
    }


def collect_node_fw_attributes(network: str, snapshot: str) -> dict:
    save_dir = os.path.join(OUTPUTS_DIR, network, snapshot)
    if not os.path.isdir(save_dir):
        return []

    nodes = []
    for filename in sorted(os.listdir(save_dir)):
        if not filename.endswith(".json"):
            continue
        node_name = filename[: -len(".json")]
        filepath = os.path.join(save_dir, filename)
        with open(filepath, "r", encoding="utf-8") as f:
            fw_data = json.load(f)
        nodes.append({
            "node-id": node_name,
            "mddo-topology:l3-node-attributes": {"firewall": fw_data},
        })

    return {"node": nodes}


def parse_fw_configs(network: str, snapshot: str, copy_targets: Dict) -> List[str]:
    parsed_nodes = []

    for node, info in copy_targets.items():
        logger.info(f"Parsing: {info['dst_file']}")

        with open(info["dst_file"], "r", encoding="utf-8") as f:
            config_text = f.read()

        ttp_result = ttp_parse(config_text)
        output = _build_output(node, info["pair"], ttp_result)

        save_dir = os.path.join(OUTPUTS_DIR, network, snapshot)
        os.makedirs(save_dir, exist_ok=True)
        save_file = os.path.join(save_dir, f"{node}.json")

        with open(save_file, "w", encoding="utf-8") as f:
            json.dump(output, f, indent=2)

        logger.info(f"Saved: {save_file}")
        parsed_nodes.append(node)

    return parsed_nodes
