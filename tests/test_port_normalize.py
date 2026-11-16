"""Tests for interface name and device name normalization."""

from __future__ import annotations

import unittest

from topomapper.graph import normalize_device_name, normalize_port


class PortNormalizationTests(unittest.TestCase):
    def test_gigabit_ethernet(self) -> None:
        self.assertEqual(normalize_port("GigabitEthernet0/1"), "Gi0/1")
        self.assertEqual(normalize_port("gigabitethernet1/0/1"), "Gi1/0/1")

    def test_ten_gigabit_ethernet(self) -> None:
        self.assertEqual(normalize_port("TenGigabitEthernet1/1"), "Te1/1")

    def test_twenty_five_gigabit(self) -> None:
        self.assertEqual(normalize_port("TwentyFiveGigE1/0/1"), "Twe1/0/1")

    def test_forty_and_hundred_gigabit(self) -> None:
        self.assertEqual(normalize_port("FortyGigabitEthernet0/1"), "Fo0/1")
        self.assertEqual(normalize_port("HundredGigE0/1"), "Hu0/1")

    def test_fast_ethernet(self) -> None:
        self.assertEqual(normalize_port("FastEthernet0/12"), "Fa0/12")

    def test_plain_ethernet_is_not_matched_as_gigabit(self) -> None:
        self.assertEqual(normalize_port("Ethernet0/1"), "Et0/1")
        self.assertEqual(normalize_port("AppGigabitEthernet1/0/1"), "Ap1/0/1")

    def test_port_channel(self) -> None:
        self.assertEqual(normalize_port("Port-channel1"), "Po1")
        self.assertEqual(normalize_port("Port-Channel10"), "Po10")

    def test_loopback_and_vlan(self) -> None:
        self.assertEqual(normalize_port("Loopback0"), "Lo0")
        self.assertEqual(normalize_port("Vlan100"), "Vl100")

    def test_management_interface(self) -> None:
        self.assertEqual(normalize_port("Management0"), "Ma0")

    def test_space_between_name_and_number(self) -> None:
        self.assertEqual(normalize_port("GigabitEthernet 1/0/1"), "Gi1/0/1")
        self.assertEqual(normalize_port("  GigabitEthernet   1/0/2  "), "Gi1/0/2")

    def test_already_short_names_are_kept(self) -> None:
        self.assertEqual(normalize_port("Gi1/0/1"), "Gi1/0/1")
        self.assertEqual(normalize_port("Twe1/0/1"), "Twe1/0/1")

    def test_unknown_names_pass_through(self) -> None:
        self.assertEqual(normalize_port("Bundle-Ether1"), "Bundle-Ether1")
        self.assertEqual(normalize_port("Wlan-GigabitEthernet0/1/0"), "Wlan-GigabitEthernet0/1/0")

    def test_empty_value(self) -> None:
        self.assertEqual(normalize_port(""), "")
        self.assertEqual(normalize_port("   "), "")


class DeviceNameNormalizationTests(unittest.TestCase):
    def test_case_is_folded(self) -> None:
        self.assertEqual(normalize_device_name("Core-SW"), "core-sw")

    def test_trailing_dot_is_stripped(self) -> None:
        self.assertEqual(normalize_device_name("core-sw.lab.example."), "core-sw.lab.example")

    def test_inner_whitespace_is_collapsed(self) -> None:
        self.assertEqual(normalize_device_name("  core  sw  "), "core sw")

    def test_empty_name(self) -> None:
        self.assertEqual(normalize_device_name(""), "")
        self.assertEqual(normalize_device_name("   "), "")


if __name__ == "__main__":
    unittest.main()
