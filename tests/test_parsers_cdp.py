"""Tests for the CDP detail parser."""

from __future__ import annotations

import unittest

from helpers import SAMPLE_CDP, cdp_block

from topomapper.parsers import parse_cdp


class CdpSampleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.neighbors = parse_cdp(SAMPLE_CDP, "switch-a")

    def test_record_count(self) -> None:
        self.assertEqual(len(self.neighbors), 2)

    def test_protocol(self) -> None:
        self.assertEqual(self.neighbors[0].protocol, "cdp")

    def test_local_device_is_injected(self) -> None:
        self.assertEqual(self.neighbors[0].local_device, "switch-a")
        self.assertEqual(self.neighbors[1].local_device, "switch-a")

    def test_device_ids(self) -> None:
        self.assertEqual(self.neighbors[0].remote_name, "switch-b")
        self.assertEqual(self.neighbors[1].remote_name, "switch-c")

    def test_interface_and_port_id(self) -> None:
        self.assertEqual(self.neighbors[0].local_port, "GigabitEthernet1/0/1")
        self.assertEqual(self.neighbors[0].remote_port, "GigabitEthernet1/0/2")
        self.assertEqual(self.neighbors[1].local_port, "GigabitEthernet1/0/3")
        self.assertEqual(self.neighbors[1].remote_port, "GigabitEthernet0/1")

    def test_management_addresses(self) -> None:
        self.assertEqual(self.neighbors[0].mgmt_ip, "192.0.2.12")
        self.assertEqual(self.neighbors[1].mgmt_ip, "192.0.2.13")

    def test_platform_parsed(self) -> None:
        self.assertEqual(self.neighbors[0].platform, "cisco WS-C2960-24TT-L")
        self.assertEqual(self.neighbors[1].platform, "cisco WS-C3560-24TS")

    def test_capabilities_from_platform_line(self) -> None:
        self.assertEqual(self.neighbors[0].capabilities, "Switch IGMP")

    def test_version_section_is_not_mistaken_for_platform(self) -> None:
        self.assertNotIn("Copyright", self.neighbors[0].platform or "")
        self.assertNotIn("Version", self.neighbors[0].platform or "")


class CdpToleranceTests(unittest.TestCase):
    def test_platform_without_capabilities(self) -> None:
        text = "Device ID: sw-b\nPlatform: cisco WS-C2960-24TT-L\nInterface: Gi0/1\n"
        neighbors = parse_cdp(text, "sw-a")
        self.assertEqual(neighbors[0].platform, "cisco WS-C2960-24TT-L")
        self.assertIsNone(neighbors[0].capabilities)

    def test_separate_capabilities_line(self) -> None:
        text = "Device ID: sw-b\nPlatform: cisco WS-C2960\nCapabilities: Router\nInterface: Gi0/1\n"
        neighbors = parse_cdp(text, "sw-a")
        self.assertEqual(neighbors[0].capabilities, "Router")

    def test_interface_line_without_outgoing_port(self) -> None:
        text = "Device ID: sw-b\nInterface: GigabitEthernet0/1\n"
        neighbors = parse_cdp(text, "sw-a")
        self.assertEqual(neighbors[0].local_port, "GigabitEthernet0/1")
        self.assertEqual(neighbors[0].remote_port, "")

    def test_port_id_on_separate_line(self) -> None:
        text = "Device ID: sw-b\nInterface: Gi0/1\nPort ID (outgoing port): Gi0/2\n"
        neighbors = parse_cdp(text, "sw-a")
        self.assertEqual(neighbors[0].remote_port, "Gi0/2")

    def test_block_without_device_id_is_skipped(self) -> None:
        text = cdp_block(None, "Gi0/1", "Gi0/2")
        self.assertEqual(parse_cdp(text, "sw-a"), [])

    def test_leading_spaces_are_tolerated(self) -> None:
        text = "   Device ID: sw-b\n   Interface: Gi0/1,   Port ID (outgoing port): Gi0/2\n"
        neighbors = parse_cdp(text, "sw-a")
        self.assertEqual(len(neighbors), 1)
        self.assertEqual(neighbors[0].remote_port, "Gi0/2")

    def test_multiple_ip_addresses_first_wins(self) -> None:
        text = (
            "Device ID: sw-b\n"
            "Entry address(es):\n"
            "  IP address: 192.0.2.10\n"
            "  IP address: 192.0.2.11\n"
            "Interface: Gi0/1\n"
        )
        neighbors = parse_cdp(text, "sw-a")
        self.assertEqual(neighbors[0].mgmt_ip, "192.0.2.10")

    def test_duplicate_blocks_are_both_parsed(self) -> None:
        text = cdp_block("sw-b", "Gi0/1", "Gi0/2") + cdp_block("sw-b", "Gi0/1", "Gi0/2")
        self.assertEqual(len(parse_cdp(text, "sw-a")), 2)

    def test_lldp_only_text_yields_no_cdp_records(self) -> None:
        from helpers import SAMPLE_LLDP

        self.assertEqual(parse_cdp(SAMPLE_LLDP, "switch-a"), [])

    def test_empty_text(self) -> None:
        self.assertEqual(parse_cdp("", "sw-a"), [])

    def test_device_id_with_dots(self) -> None:
        text = "Device ID: core-sw.lab.example\nInterface: Gi0/1\n"
        neighbors = parse_cdp(text, "sw-a")
        self.assertEqual(neighbors[0].remote_name, "core-sw.lab.example")


if __name__ == "__main__":
    unittest.main()
