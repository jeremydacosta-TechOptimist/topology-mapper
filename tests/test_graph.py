"""Tests for graph construction, link merging and inventory handling."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from helpers import (
    FIXTURE_DIR,
    FIXTURE_INVENTORY,
    cdp_block,
    fixture_graph,
    lldp_block,
    write_topology,
)

from topomapper.errors import NetopsError
from topomapper.graph import (
    load_dump_files,
    load_graph,
    load_inventory,
    normalize_device_name,
)


def find_edge(graph, first: str, second: str):
    """Return the edge between two devices, or ``None``."""
    wanted = {normalize_device_name(first), normalize_device_name(second)}
    for edge in graph.edges:
        if {normalize_device_name(edge.a), normalize_device_name(edge.b)} == wanted:
            return edge
    return None


class FixtureGraphTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.graph = fixture_graph()
        cls.by_name = {node.name: node for node in cls.graph.nodes.values()}

    def test_device_count(self) -> None:
        self.assertEqual(self.graph.device_count, 5)

    def test_edge_count(self) -> None:
        self.assertEqual(self.graph.edge_count, 5)

    def test_node_names_sorted(self) -> None:
        self.assertEqual(
            [node.name for node in self.graph.nodes.values()],
            ["core-sw", "edge-rtr", "floor1-sw", "floor2-sw", "fw1"],
        )

    def test_inventory_roles(self) -> None:
        self.assertEqual(self.by_name["core-sw"].role, "core")
        self.assertEqual(self.by_name["edge-rtr"].role, "edge")
        self.assertEqual(self.by_name["floor1-sw"].role, "access")
        self.assertEqual(self.by_name["fw1"].role, "unknown")

    def test_management_addresses(self) -> None:
        self.assertEqual(self.by_name["core-sw"].mgmt_ip, "192.0.2.1")
        self.assertEqual(self.by_name["edge-rtr"].mgmt_ip, "192.0.2.254")
        self.assertEqual(self.by_name["fw1"].mgmt_ip, "192.0.2.200")

    def test_undumped_device(self) -> None:
        fw1 = self.by_name["fw1"]
        self.assertFalse(fw1.declared)
        self.assertFalse(fw1.has_dump)
        self.assertEqual(fw1.mentioned_by, ("core-sw",))

    def test_lldp_and_cdp_are_merged(self) -> None:
        edge = find_edge(self.graph, "core-sw", "floor1-sw")
        self.assertIsNotNone(edge)
        self.assertEqual(edge.protocols, ("cdp", "lldp"))
        self.assertTrue(edge.symmetric)

    def test_ports_are_normalized_on_edges(self) -> None:
        edge = find_edge(self.graph, "core-sw", "floor1-sw")
        self.assertEqual(edge.a_port, "Gi1/0/1")
        self.assertEqual(edge.b_port, "Gi1/0/1")
        fw_edge = find_edge(self.graph, "core-sw", "fw1")
        self.assertEqual(fw_edge.b_port, "Et0/1")

    def test_one_sided_edge(self) -> None:
        edge = find_edge(self.graph, "floor1-sw", "floor2-sw")
        self.assertIsNotNone(edge)
        self.assertFalse(edge.symmetric)
        self.assertEqual(edge.protocols, ("lldp",))
        self.assertEqual(edge.reported_by, ("floor1-sw",))

    def test_degree(self) -> None:
        self.assertEqual(self.graph.degree("core-sw"), 4)
        self.assertEqual(self.graph.degree("floor1-sw"), 2)
        self.assertEqual(self.graph.degree("fw1"), 1)

    def test_adjacency(self) -> None:
        adjacency = self.graph.adjacency()
        self.assertEqual(len(adjacency), 5)
        self.assertEqual(
            adjacency["core-sw"],
            ["edge-rtr", "floor1-sw", "floor2-sw", "fw1"],
        )

    def test_summary(self) -> None:
        summary = self.graph.summary()
        self.assertEqual(summary["devices"], 5)
        self.assertEqual(summary["edges"], 5)
        self.assertEqual(summary["dumped_devices"], 4)
        self.assertEqual(summary["mention_only_devices"], 1)
        self.assertEqual(summary["symmetric_edges"], 3)
        self.assertEqual(summary["one_sided_edges"], 2)
        self.assertEqual(summary["lldp_edges"], 5)
        self.assertEqual(summary["cdp_edges"], 3)

    def test_to_dict_shape(self) -> None:
        document = self.graph.to_dict()
        self.assertEqual(document["schema_version"], 1)
        self.assertEqual(len(document["nodes"]), 5)
        self.assertEqual(len(document["edges"]), 5)
        self.assertIn("summary", document)

    def test_node_to_dict(self) -> None:
        document = self.by_name["core-sw"].to_dict()
        self.assertEqual(document["name"], "core-sw")
        self.assertEqual(document["role"], "core")
        self.assertTrue(document["declared"])
        self.assertEqual(document["mentioned_by"], ["edge-rtr", "floor1-sw", "floor2-sw"])

    def test_edge_to_dict(self) -> None:
        edge = find_edge(self.graph, "core-sw", "floor1-sw")
        document = edge.to_dict()
        self.assertEqual(document["a"], "core-sw")
        self.assertEqual(document["b"], "floor1-sw")
        self.assertEqual(document["protocols"], ["cdp", "lldp"])
        self.assertTrue(document["symmetric"])

    def test_graph_loading_is_deterministic(self) -> None:
        first = json.dumps(self.graph.to_dict(), sort_keys=True)
        second = json.dumps(fixture_graph().to_dict(), sort_keys=True)
        self.assertEqual(first, second)


class DumpFileTests(unittest.TestCase):
    def test_files_are_sorted_by_name(self) -> None:
        dumps = load_dump_files(FIXTURE_DIR)
        self.assertEqual(
            [name for name, _ in dumps],
            ["core-sw", "edge-rtr", "floor1-sw", "floor2-sw"],
        )

    def test_missing_directory_raises(self) -> None:
        with self.assertRaises(NetopsError):
            load_dump_files(str(Path(FIXTURE_DIR, "missing")))

    def test_file_path_raises(self) -> None:
        with self.assertRaises(NetopsError):
            load_dump_files(FIXTURE_INVENTORY)

    def test_empty_directory_raises(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertRaises(NetopsError) as context:
                load_dump_files(temp_dir)
        self.assertIn("no device dumps", str(context.exception))

    def test_utf8_bom_is_tolerated(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            Path(temp_dir, "sw.txt").write_bytes(
                b"\xef\xbb\xbfLocal Intf: Gi0/1\r\nPort id: Gi0/2\r\nSystem Name: peer\r\n"
            )
            dumps = load_dump_files(temp_dir)
        self.assertEqual(dumps[0][0], "sw")
        self.assertIn("Local Intf", dumps[0][1])


class InventoryTests(unittest.TestCase):
    def test_fixture_inventory(self) -> None:
        inventory = load_inventory(FIXTURE_INVENTORY)
        self.assertEqual(len(inventory), 4)
        self.assertEqual(inventory["core-sw"].role, "core")
        self.assertEqual(inventory["core-sw"].mgmt_ip, "192.0.2.1")

    def test_missing_file_raises(self) -> None:
        with self.assertRaises(NetopsError):
            load_inventory(str(Path(FIXTURE_DIR, "no-inventory.json")))

    def test_invalid_json_raises(self) -> None:
        with write_topology({"bad.json": "{not json"}) as temp_dir:
            with self.assertRaises(NetopsError):
                load_inventory(str(Path(temp_dir, "bad.json")))

    def test_missing_devices_key_raises(self) -> None:
        with write_topology({"inventory.json": '{"items": []}'}) as temp_dir:
            with self.assertRaises(NetopsError):
                load_inventory(str(Path(temp_dir, "inventory.json")))

    def test_devices_must_be_a_list(self) -> None:
        with write_topology({"inventory.json": '{"devices": {}}'}) as temp_dir:
            with self.assertRaises(NetopsError):
                load_inventory(str(Path(temp_dir, "inventory.json")))

    def test_entry_must_be_an_object(self) -> None:
        with write_topology({"inventory.json": '{"devices": ["sw1"]}'}) as temp_dir:
            with self.assertRaises(NetopsError):
                load_inventory(str(Path(temp_dir, "inventory.json")))

    def test_missing_name_raises(self) -> None:
        with write_topology({"inventory.json": '{"devices": [{"role": "core"}]}'}) as temp_dir:
            with self.assertRaises(NetopsError):
                load_inventory(str(Path(temp_dir, "inventory.json")))

    def test_duplicate_name_raises(self) -> None:
        content = '{"devices": [{"name": "sw1"}, {"name": "SW1"}]}'
        with write_topology({"inventory.json": content}) as temp_dir:
            with self.assertRaises(NetopsError):
                load_inventory(str(Path(temp_dir, "inventory.json")))

    def test_invalid_management_ip_raises(self) -> None:
        content = '{"devices": [{"name": "sw1", "mgmt_ip": "not-an-ip"}]}'
        with write_topology({"inventory.json": content}) as temp_dir:
            with self.assertRaises(NetopsError):
                load_inventory(str(Path(temp_dir, "inventory.json")))

    def test_non_string_role_raises(self) -> None:
        content = '{"devices": [{"name": "sw1", "role": 4}]}'
        with write_topology({"inventory.json": content}) as temp_dir:
            with self.assertRaises(NetopsError):
                load_inventory(str(Path(temp_dir, "inventory.json")))

    def test_unknown_keys_are_ignored(self) -> None:
        content = '{"devices": [{"name": "sw1", "role": "core", "site": "lab"}]}'
        with write_topology({"inventory.json": content}) as temp_dir:
            inventory = load_inventory(str(Path(temp_dir, "inventory.json")))
        self.assertEqual(inventory["sw1"].role, "core")


class SyntheticGraphTests(unittest.TestCase):
    def test_lldp_and_cdp_merge_from_same_port(self) -> None:
        files = {
            "a.txt": lldp_block("Gi0/1", "b", "Gi0/2") + cdp_block("b", "Gi0/1", "Gi0/2"),
            "b.txt": lldp_block("Gi0/2", "a", "Gi0/1") + cdp_block("a", "Gi0/2", "Gi0/1"),
        }
        with write_topology(files) as temp_dir:
            graph = load_graph(temp_dir)
        self.assertEqual(graph.edge_count, 1)
        self.assertEqual(graph.edges[0].protocols, ("cdp", "lldp"))
        self.assertTrue(graph.edges[0].symmetric)

    def test_self_link_is_ignored(self) -> None:
        with write_topology({"a.txt": lldp_block("Gi0/1", "a", "Gi0/1")}) as temp_dir:
            graph = load_graph(temp_dir)
        self.assertEqual(graph.device_count, 1)
        self.assertEqual(graph.edge_count, 0)

    def test_reciprocal_merge_without_remote_ports(self) -> None:
        files = {
            "a.txt": lldp_block("Gi0/1", "b"),
            "b.txt": lldp_block("Gi0/2", "a"),
        }
        with write_topology(files) as temp_dir:
            graph = load_graph(temp_dir)
        self.assertEqual(graph.edge_count, 1)
        self.assertTrue(graph.edges[0].symmetric)
        self.assertEqual(graph.edges[0].a_port, "Gi0/1")
        self.assertEqual(graph.edges[0].b_port, "Gi0/2")

    def test_parallel_links_are_kept_separate(self) -> None:
        files = {
            "a.txt": lldp_block("Gi0/1", "b", "Gi0/1") + lldp_block("Gi0/2", "b", "Gi0/2"),
            "b.txt": lldp_block("Gi0/1", "a", "Gi0/1") + lldp_block("Gi0/2", "a", "Gi0/2"),
        }
        with write_topology(files) as temp_dir:
            graph = load_graph(temp_dir)
        self.assertEqual(graph.edge_count, 2)
        self.assertTrue(all(edge.symmetric for edge in graph.edges))

    def test_one_sided_link(self) -> None:
        files = {
            "a.txt": lldp_block("Gi0/1", "b", "Gi0/2"),
            "b.txt": lldp_block("Gi0/5", "c", "Gi0/6"),
            "c.txt": lldp_block("Gi0/6", "b", "Gi0/5"),
        }
        with write_topology(files) as temp_dir:
            graph = load_graph(temp_dir)
        edge = find_edge(graph, "a", "b")
        self.assertFalse(edge.symmetric)
        self.assertEqual(edge.protocols, ("lldp",))

    def test_device_name_case_is_merged(self) -> None:
        files = {
            "SwitchA.txt": lldp_block("Gi0/1", "switchb", "Gi0/2"),
            "switchb.txt": lldp_block("Gi0/2", "SWITCHA", "Gi0/1"),
        }
        with write_topology(files) as temp_dir:
            graph = load_graph(temp_dir)
        self.assertEqual(graph.device_count, 2)
        names = sorted(node.name for node in graph.nodes.values())
        self.assertEqual(names, ["SwitchA", "switchb"])

    def test_invalid_management_ip_is_dropped(self) -> None:
        with write_topology(
            {"a.txt": lldp_block("Gi0/1", "b", "Gi0/2", mgmt_ip="not-an-ip")}
        ) as temp_dir:
            graph = load_graph(temp_dir)
        node = graph.node("b")
        self.assertIsNone(node.mgmt_ip)

    def test_inventory_only_device_is_isolated(self) -> None:
        with write_topology({"a.txt": lldp_block("Gi0/1", "b", "Gi0/2")}) as temp_dir:
            inventory_path = Path(temp_dir, "inventory.json")
            inventory_path.write_text(
                '{"devices": [{"name": "a", "role": "core"}]}', encoding="utf-8"
            )
            graph = load_graph(temp_dir, inventory_path)
        node_a = graph.node("a")
        self.assertEqual(node_a.role, "core")
        self.assertTrue(node_a.declared)
        self.assertTrue(node_a.has_dump)
        self.assertEqual(graph.edge_count, 1)

    def test_dump_without_records_still_creates_a_node(self) -> None:
        with write_topology({"a.txt": "a#show lldp neighbors detail\n"}) as temp_dir:
            graph = load_graph(temp_dir)
        self.assertEqual(graph.device_count, 1)
        self.assertEqual(graph.edge_count, 0)


if __name__ == "__main__":
    unittest.main()
