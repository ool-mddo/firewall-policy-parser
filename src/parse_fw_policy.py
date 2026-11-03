import json
import os
import re
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


# match conditions that can take multiple values: `application [ a b ];` / `application a; application b;`
_LIST_KEYS = ["source_address", "destination_address", "application"]
_BRACKET_LIST_PATTERN = re.compile(
    r"^([ \t]*)(source-address|destination-address|application)[ \t]*\[([^\]]*)\][ \t]*;", re.MULTILINE
)


_INACTIVE_POLICY_PATTERN = re.compile(r"^[ \t]*inactive:[ \t]*policy[ \t]+\S+[ \t]*\{")


def _remove_inactive_policies(text: str) -> str:
    """Remove `inactive: policy NAME { ... }` blocks (deactivated policies are not effective).

    Without removing them, the block is merged into the previous policy (the template cannot start a rule at it).
    """
    lines = text.splitlines(keepends=True)
    result = []
    depth = 0  # brace depth in an inactive policy block (0: out of the block)
    for line in lines:
        if depth == 0 and _INACTIVE_POLICY_PATTERN.match(line):
            depth = line.count("{") - line.count("}")
            continue
        if depth > 0:
            depth += line.count("{") - line.count("}")
            continue
        result.append(line)
    return "".join(result)


def _expand_bracket_lists(text: str) -> str:
    """Expand `key [ a b c ];` (single/multi-line) to `key a;` lines (the template collects them as a list)"""

    def expand(match: re.Match) -> str:
        indent, key, values = match.groups()
        return "\n".join(f"{indent}{key} {value};" for value in values.split())

    return _BRACKET_LIST_PATTERN.sub(expand, text)


def _flatten_rule_lists(ttp_result: List) -> None:
    """Convert [{"value": "a"}, ...] of each list key in rules to ["a", ...] (missing key -> [])"""
    for per_input in ttp_result:
        for result in per_input:
            for policy in result.get("policies", []):
                for rule in policy.get("rules", []):
                    for key in _LIST_KEYS:
                        rule[key] = [item["value"] for item in rule.get(key, [])]


def ttp_parse(text: str) -> List:
    parser = ttp(_expand_bracket_lists(_remove_inactive_policies(text)), TTP_TEMPLATE)
    parser.parse()
    result = parser.result()
    _flatten_rule_lists(result)
    return result


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
            "flag": ["firewall"],
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
