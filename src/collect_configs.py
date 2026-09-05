import os
import re
import shutil
from logging import getLogger
from typing import Dict, List, Optional

logger = getLogger(__name__)

MDDO_CONFIGS_DIR = os.environ.get("MDDO_CONFIGS_DIR", "./configs")

_PARSER_DIR = os.environ.get("MDDO_FIREWALL_POLICY_PARSER_DIR", ".")
CONFIGS_INPUT_DIR = os.environ.get(
    "MDDO_FIREWALL_POLICY_PARSER_CONFIGS_DIR",
    os.path.join(_PARSER_DIR, "ttp_input"),
)
OUTPUTS_DIR = os.environ.get(
    "MDDO_FIREWALL_POLICY_PARSER_OUTPUTS_DIR",
    os.path.join(_PARSER_DIR, "ttp_output"),
)

_INHERIT_PATTERN = re.compile(r"'(.+?)' was inherited from group 'node[01]'")
_HOSTNAME_PATTERN = re.compile(r"^\s+host-name\s+(\S+);", re.MULTILINE)


def _detect_node_name(text: str) -> Optional[str]:
    """FW inherited config であれば host-name を返す。そうでなければ None。"""
    if not _INHERIT_PATTERN.search(text):
        return None
    match = _HOSTNAME_PATTERN.search(text)
    return match.group(1) if match else None


def detect_fw_configs(network: str, snapshot: str) -> Dict[str, str]:
    """configs dir を走査して FW コンフィグを検出する。{nodename: filepath} を返す。"""
    scan_dir = os.path.join(MDDO_CONFIGS_DIR, network, snapshot)
    detected: Dict[str, str] = {}

    if not os.path.isdir(scan_dir):
        logger.error(f"configs dir not found: {scan_dir}")
        return detected

    for dirpath, _, filenames in os.walk(scan_dir):
        for filename in filenames:
            filepath = os.path.join(dirpath, filename)
            try:
                with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
                    text = f.read()
            except OSError as e:
                logger.warning(f"Cannot read {filepath}: {e}")
                continue

            node_name = _detect_node_name(text)
            if node_name:
                logger.info(f"Detected FW config: {filepath} (node={node_name})")
                detected[node_name] = filepath

    return detected


def cleanup_snapshot_dir(network: str, snapshot: str) -> None:
    """ttp_input / ttp_output の該当スナップショットディレクトリを削除する。"""
    for base_dir in [CONFIGS_INPUT_DIR, OUTPUTS_DIR]:
        target = os.path.join(base_dir, network, snapshot)
        if os.path.isdir(target):
            shutil.rmtree(target)
            logger.info(f"Cleaned up: {target}")


def collect_configs(network: str, snapshot: str, node_pairs: List[Dict]) -> Dict:
    """FW コンフィグを検出・照合して ttp_input にコピーし、コピー対象情報を返す。"""
    detected = detect_fw_configs(network, snapshot)

    pair_nodes: Dict[str, Dict] = {}
    for pair in node_pairs:
        for role in ("primary", "secondary"):
            node = pair.get(role)
            if node:
                pair_nodes[node] = pair

    for node in pair_nodes:
        if node not in detected:
            logger.error(
                f"node '{node}' is specified in node_pairs but config not found"
            )

    for node in detected:
        if node not in pair_nodes:
            logger.warning(
                f"config found for '{node}' but not specified in node_pairs"
            )

    copy_targets: Dict = {}
    for node in pair_nodes:
        if node not in detected:
            continue
        dst_dir = os.path.join(CONFIGS_INPUT_DIR, network, snapshot)
        os.makedirs(dst_dir, exist_ok=True)
        src_file = detected[node]
        dst_file = os.path.join(dst_dir, os.path.basename(src_file))
        shutil.copy(src_file, dst_file)
        logger.info(f"Copied: {src_file} -> {dst_file}")
        copy_targets[node] = {"dst_file": dst_file, "pair": pair_nodes[node]}

    return copy_targets
