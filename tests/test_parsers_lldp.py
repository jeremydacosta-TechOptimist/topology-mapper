"""Tests for the LLDP detail parser."""

from __future__ import annotations

import unittest

from helpers import SAMPLE_LLDP, lldp_block

from topomapper.parsers import parse_lldp


class LldpSampleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.neighbors = parse_lldp(SAMPLE_LLDP, "switch-a")

    def test_record_count(self) -> None:
        self.assertEqual(len(self.neighbors), 2)

    def test_protocol(self) -> None:
        self.assertEqual(self.neighbors[0].protocol, "lldp")

    def test_local_device_is_injected(self) -> None:
        self.assertEqual(self.neighbors[0].local_device, "switch-a")
        self.assertEqual(self.neighbors[1].local_device, "switch-a")

    def test_local_and_remote_ports(self) -> None:
        self.assertEqual(self.neighbors[0].local_port, "GigabitEthernet1/0/1")
        self.assertEqual(self.neighbors[0].remote_port, "GigabitEthernet1/0/2")

    def test_remote_name(self) -> None:
        self.assertEqual(self.neighbors[0].remote_name, "switch-b")
        self.assertEqual(self.neighbors[1].remote_name, "server-1")

    def test_management_address(self) -> None:
        self.assertEqual(self.neighbors[0].mgmt_ip, "192.0.2.12")
        self.assertEqual(self.neighbors[1].mgmt_ip, "192.0.2.50")

    def test_platform_from_system_description(self) -> None:
        self.assertIn("C2960", self.neighbors[0].platform or "")

    def test_capabilities_use_enabled(self) -> None:
        self.assertEqual(self.neighbors[0].capabilities, "B,R")
        self.assertEqual(self.neighbors[1].capabilities, "B")

    def test_port_description(self) -> None:
        self.assertEqual(self.neighbors[0].port_description, "uplink to switch-b.lab.example")


class LldpToleranceTests(unittest.TestCase):
    def test_inline_management_address(self) -> None:
        text = "Local Intf: Gi0/1\nPort id: Gi0/2\nSystem Name: sw-b\nManagement Addresses: IP: 192.0.2.9\n"
        neighbors = parse_lldp(text, "sw-a")
        self.assertEqual(len(neighbors), 1)
        self.assertEqual(neighbors[0].mgmt_ip, "192.0.2.9")

    def test_first_ip_wins(self) -> None:
        text = (
            "Local Intf: Gi0/1\n"
            "Port id: Gi0/2\n"
            "System Name: sw-b\n"
            "Management Addresses:\n"
            "    IP: 192.0.2.9\n"
            "    IP: 192.0.2.10\n"
        )
        neighbors = parse_lldp(text, "sw-a")
        self.assertEqual(neighbors[0].mgmt_ip, "192.0.2.9")

    def test_system_name_falls_back_to_chassis_id(self) -> None:
        text = "Local Intf: Gi0/1\nChassis id: 0011.2233.4455\nPort id: Gi0/2\n"
        neighbors = parse_lldp(text, "sw-a")
        self.assertEqual(len(neighbors), 1)
        self.assertEqual(neighbors[0].remote_name, "0011.2233.4455")

    def test_block_without_remote_identity_is_skipped(self) -> None:
        text = "Local Intf: Gi0/1\nPort id: Gi0/2\n"
        self.assertEqual(parse_lldp(text, "sw-a"), [])

    def test_lowercase_key_tolerance(self) -> None:
        text = "local intf: Gi0/1\nport id: Gi0/2\nsystem name: sw-b\n"
        neighbors = parse_lldp(text, "sw-a")
        self.assertEqual(len(neighbors), 1)
        self.assertEqual(neighbors[0].remote_name, "sw-b")

    def test_system_capabilities_used_when_enabled_missing(self) -> None:
        text = "Local Intf: Gi0/1\nPort id: Gi0/2\nSystem Name: sw-b\nSystem Capabilities: B,R\n"
        neighbors = parse_lldp(text, "sw-a")
        self.assertEqual(neighbors[0].capabilities, "B,R")

    def test_unknown_lines_are_ignored(self) -> None:
        text = (
            "Local Intf: Gi0/1\n"
            "Port id: Gi0/2\n"
            "System Name: sw-b\n"
            "Auto Negotiation - supported, enabled\n"
            "Physical media capabilities:\n"
            "    1000baseT(FD)\n"
        )
        neighbors = parse_lldp(text, "sw-a")
        self.assertEqual(len(neighbors), 1)

    def test_duplicate_blocks_are_both_parsed(self) -> None:
        text = lldp_block("Gi0/1", "sw-b", "Gi0/2") + lldp_block("Gi0/1", "sw-b", "Gi0/2")
        self.assertEqual(len(parse_lldp(text, "sw-a")), 2)

    def test_cdp_only_text_yields_no_lldp_records(self) -> None:
        from helpers import SAMPLE_CDP

        self.assertEqual(parse_lldp(SAMPLE_CDP, "switch-a"), [])

    def test_empty_text(self) -> None:
        self.assertEqual(parse_lldp("", "sw-a"), [])


if __name__ == "__main__":
    unittest.main()
