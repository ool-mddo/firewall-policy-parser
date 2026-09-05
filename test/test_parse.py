import json
import os
import re
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import parse_fw_policy as pfp
import collect_configs as cc

INPUTS_DIR = os.path.join(os.path.dirname(__file__), "inputs")
EXPECTS_DIR = os.path.join(os.path.dirname(__file__), "expects")

FW_NODES = ["site-a-fw-1", "site-a-fw-2"]


@pytest.mark.parametrize("node", FW_NODES)
def test_ttp_parse_matches_expect(node):
    config_file = os.path.join(INPUTS_DIR, f"{node}.config.inheritance")
    expect_file = os.path.join(EXPECTS_DIR, f"{node}.json")

    with open(config_file, encoding="utf-8") as f:
        text = f.read()
    with open(expect_file, encoding="utf-8") as f:
        expected = json.load(f)

    result = pfp.ttp_parse(text)
    assert result == expected


@pytest.mark.parametrize("node", FW_NODES)
def test_detect_fw_config(node):
    config_file = os.path.join(INPUTS_DIR, f"{node}.config.inheritance")
    with open(config_file, encoding="utf-8") as f:
        text = f.read()

    detected_name = cc._detect_node_name(text)
    assert detected_name == node


def test_detect_fw_config_negative():
    non_fw_text = "interfaces {\n    ge-0/0/0 {\n        unit 0;\n    }\n}\n"
    assert cc._detect_node_name(non_fw_text) is None


def test_node_pairs_validation(tmp_path, caplog):
    import logging

    (tmp_path / "net1" / "snap1").mkdir(parents=True)
    config_file = os.path.join(INPUTS_DIR, "site-a-fw-1.config.inheritance")
    import shutil
    shutil.copy(config_file, tmp_path / "net1" / "snap1" / "site-a-fw-1.config.inheritance")

    original_configs_dir = cc.MDDO_CONFIGS_DIR
    cc.MDDO_CONFIGS_DIR = str(tmp_path)

    node_pairs = [
        {"primary": "site-a-fw-1", "secondary": "site-a-fw-2"},
    ]

    with caplog.at_level(logging.ERROR, logger="collect_configs"):
        cc.detect_fw_configs("net1", "snap1")
        detected = cc.detect_fw_configs("net1", "snap1")

    pair_nodes = {"site-a-fw-1", "site-a-fw-2"}
    for node in pair_nodes:
        if node not in detected:
            pass

    assert "site-a-fw-1" in detected
    assert "site-a-fw-2" not in detected

    cc.MDDO_CONFIGS_DIR = original_configs_dir
