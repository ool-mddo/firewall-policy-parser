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


def test_cluster_firewall_pairs_validation(tmp_path, caplog):
    import logging

    (tmp_path / "net1" / "snap1" / "configs").mkdir(parents=True)
    config_file = os.path.join(INPUTS_DIR, "site-a-fw-1.config.inheritance")
    import shutil
    shutil.copy(config_file, tmp_path / "net1" / "snap1" / "configs" / "site-a-fw-1.config.inheritance")

    original_configs_dir = cc.MDDO_CONFIGS_DIR
    cc.MDDO_CONFIGS_DIR = str(tmp_path)

    node_pairs = [
        {"primary": {"name": "site-a-fw-1"}, "secondary": {"name": "site-a-fw-2"}},
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


def _policy_text(match_lines: str, action: str = "permit") -> str:
    return (
        "        from-zone WAN to-zone LAN {\n"
        "            policy P {\n"
        "                match {\n"
        f"{match_lines}"
        "                }\n"
        "                then {\n"
        f"                    {action};\n"
        "                }\n"
        "            }\n"
        "        }\n"
    )


def _parse_rule(match_lines: str, action: str = "permit") -> dict:
    result = pfp.ttp_parse(_policy_text(match_lines, action))
    return result[0][0]["policies"][0]["rules"][0]


MULTI_APPLICATIONS = ["junos-ping", "junos-dns-udp", "junos-dns-tcp", "junos-http", "junos-https"]


@pytest.mark.parametrize(
    "application_lines",
    [
        # multi-line bracket list
        "                    application [\n"
        + "".join(f"                        {a}\n" for a in MULTI_APPLICATIONS)
        + "                    ];\n",
        # single-line bracket list
        f"                    application [ {' '.join(MULTI_APPLICATIONS)} ];\n",
        # repeated lines
        "".join(f"                    application {a};\n" for a in MULTI_APPLICATIONS),
    ],
    ids=["multi-line-bracket", "single-line-bracket", "repeated-lines"],
)
def test_ttp_parse_multiple_applications(application_lines):
    rule = _parse_rule(
        "                    source-address any;\n"
        "                    destination-address any;\n" + application_lines
    )
    assert rule["application"] == MULTI_APPLICATIONS
    assert rule["source_address"] == ["any"]
    assert rule["destination_address"] == ["any"]
    assert rule["action"] == "permit"


def test_ttp_parse_multiple_addresses():
    rule = _parse_rule(
        "                    source-address [ host-a host-b ];\n"
        "                    destination-address net-1;\n"
        "                    destination-address net-2;\n"
        "                    application any;\n",
        action="deny",
    )
    assert rule["source_address"] == ["host-a", "host-b"]
    assert rule["destination_address"] == ["net-1", "net-2"]
    assert rule["application"] == ["any"]
    assert rule["action"] == "deny"


def test_ttp_parse_multiple_rules_keep_lists_separate():
    text = _policy_text(
        "                    source-address any;\n"
        "                    destination-address any;\n"
        "                    application [ junos-ping junos-https ];\n"
    ) + _policy_text(
        "                    source-address any;\n"
        "                    destination-address any;\n"
        "                    application any;\n",
        action="deny",
    )
    rules = [r for p in pfp.ttp_parse(text)[0][0]["policies"] for r in p["rules"]]
    assert [r["application"] for r in rules] == [["junos-ping", "junos-https"], ["any"]]
    assert [r["action"] for r in rules] == ["permit", "deny"]


def _rules_of(text: str) -> list:
    return [r for p in pfp.ttp_parse(text)[0][0]["policies"] for r in p["rules"]]


def test_ttp_parse_missing_keys_are_empty_lists():
    rule = _parse_rule("                    application any;\n")
    assert rule["source_address"] == []
    assert rule["destination_address"] == []
    assert rule["application"] == ["any"]


def test_ttp_parse_action_is_not_overwritten_by_then_statements():
    text = (
        "        from-zone WAN to-zone LAN {\n"
        "            policy P {\n"
        "                match {\n"
        "                    source-address any;\n"
        "                    destination-address any;\n"
        "                    application any;\n"
        "                }\n"
        "                then {\n"
        "                    permit;\n"
        "                    log {\n"
        "                        session-close;\n"
        "                    }\n"
        "                    count;\n"
        "                }\n"
        "            }\n"
        "        }\n"
    )
    assert _rules_of(text)[0]["action"] == "permit"


def test_ttp_parse_multiple_policies_in_a_zone_pair_keep_lists_separate():
    def policy(name, apps, action):
        return (
            f"            policy {name} {{\n"
            "                match {\n"
            "                    application " + apps + ";\n"
            "                    destination-address any;\n"
            "                    source-address [ h1 h2 ];\n"
            "                }\n"
            "                then {\n"
            f"                    {action};\n"
            "                }\n"
            "            }\n"
        )

    text = (
        "        from-zone WAN to-zone LAN {\n"
        + policy("P1", "[ junos-ping junos-https ]", "permit")
        + policy("P2", "junos-ssh", "deny")
        + "        }\n"
    )
    rules = _rules_of(text)
    assert [r["name"] for r in rules] == ["P1", "P2"]
    assert [r["application"] for r in rules] == [["junos-ping", "junos-https"], ["junos-ssh"]]
    assert [r["source_address"] for r in rules] == [["h1", "h2"], ["h1", "h2"]]
    assert [r["action"] for r in rules] == ["permit", "deny"]


def test_ttp_parse_ignores_inactive_policy():
    text = (
        "        from-zone WAN to-zone LAN {\n"
        "            policy P1 {\n"
        "                match {\n"
        "                    source-address any;\n"
        "                    destination-address any;\n"
        "                    application any;\n"
        "                }\n"
        "                then {\n"
        "                    permit;\n"
        "                }\n"
        "            }\n"
        "            inactive: policy P2 {\n"
        "                match {\n"
        "                    source-address h2;\n"
        "                    destination-address any;\n"
        "                    application [ junos-ssh junos-telnet ];\n"
        "                }\n"
        "                then {\n"
        "                    deny;\n"
        "                }\n"
        "            }\n"
        "            policy P3 {\n"
        "                match {\n"
        "                    source-address any;\n"
        "                    destination-address any;\n"
        "                    application junos-http;\n"
        "                }\n"
        "                then {\n"
        "                    permit;\n"
        "                }\n"
        "            }\n"
        "        }\n"
    )
    rules = _rules_of(text)
    assert [r["name"] for r in rules] == ["P1", "P3"]
    assert rules[0]["source_address"] == ["any"]
    assert rules[0]["action"] == "permit"
    assert rules[1]["application"] == ["junos-http"]


def test_expand_bracket_lists():
    text = (
        "    application [\n"
        "        a\n"
        "        b\n"
        "    ];\n"
        "  source-address [ x y ];\n"
        "    destination-address [z];\n"
    )
    assert pfp._expand_bracket_lists(text) == (
        "    application a;\n"
        "    application b;\n"
        "  source-address x;\n"
        "  source-address y;\n"
        "    destination-address z;\n"
    )
