"""Tests for topology analysis and statistics."""

from __future__ import annotations

import unittest

from helpers import fixture_findings, fixture_graph, make_finding, make_graph

from topomapper.analysis import (
    Finding,
    analyze,
    connected_components,
    find_articulation_points,
    find_cycles,
    find_parallel_links,
    has_errors,
    summarize_findings,
    topology_stats,
)


def triangle_graph():
    return make_graph(
        [{"name": "a"}, {"name": "b"}, {"name": "c"}],
        [
            {"a": "a", "b": "b", "a_port": "Gi0/1", "b_port": "Gi0/1"},
            {"a": "b", "b": "c", "a_port": "Gi0/2", "b_port": "Gi0/1"},
            {"a": "a", "b": "c", "a_port": "Gi0/3", "b_port": "Gi0/2"},
        ],
    )


def path_graph():
    return make_graph(
        [{"name": "a"}, {"name": "b"}, {"name": "c"}],
        [
            {"a": "a", "b": "b"},
            {"a": "b", "b": "c"},
        ],
    )


class FixtureAnalysisTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.findings = fixture_findings()

    def test_finding_ids_and_order(self) -> None:
        self.assertEqual(
            [finding.id for finding in self.findings],
            ["TOPO-CYCLE", "TOPO-ASYMMETRIC", "TOPO-SPOF", "TOPO-UNDECLARED"],
        )

    def test_finding_severities(self) -> None:
        self.assertEqual(
            [finding.severity for finding in self.findings],
            ["error", "warning", "warning", "warning"],
        )

    def test_cycle_message(self) -> None:
        cycle = self.findings[0]
        self.assertEqual(cycle.nodes, ("core-sw", "floor1-sw", "floor2-sw"))
        self.assertIn("Loop detected:", cycle.message)
        self.assertIn("core-sw -> floor1-sw -> floor2-sw -> core-sw", cycle.message)

    def test_asymmetric_message(self) -> None:
        asymmetric = self.findings[1]
        self.assertEqual(asymmetric.nodes, ("floor1-sw", "floor2-sw"))
        self.assertIn("only floor1-sw reports", asymmetric.message)

    def test_spof_message(self) -> None:
        spof = self.findings[2]
        self.assertEqual(spof.nodes, ("core-sw",))
        self.assertIn("Single point of failure: core-sw", spof.message)

    def test_undeclared_message(self) -> None:
        undeclared = self.findings[3]
        self.assertEqual(undeclared.nodes, ("fw1",))
        self.assertIn("fw1", undeclared.message)
        self.assertIn("seen from core-sw", undeclared.message)

    def test_fixture_has_no_other_findings(self) -> None:
        ids = [finding.id for finding in self.findings]
        self.assertNotIn("TOPO-DISCONNECTED", ids)
        self.assertNotIn("TOPO-PARALLEL", ids)
        self.assertNotIn("TOPO-ISOLATED", ids)

    def test_summarize_findings(self) -> None:
        counts = summarize_findings(self.findings)
        self.assertEqual(counts, {"error": 1, "warning": 3, "info": 0})

    def test_has_errors(self) -> None:
        self.assertTrue(has_errors(self.findings))

    def test_finding_to_dict(self) -> None:
        document = self.findings[0].to_dict()
        self.assertEqual(document["id"], "TOPO-CYCLE")
        self.assertEqual(document["severity"], "error")
        self.assertIsInstance(document["nodes"], list)


class ComponentAndCycleTests(unittest.TestCase):
    def test_triangle_has_one_cycle(self) -> None:
        cycles = find_cycles(triangle_graph())
        self.assertEqual(len(cycles), 1)
        self.assertEqual(len(cycles[0]), 3)

    def test_square_has_one_cycle(self) -> None:
        graph = make_graph(
            [{"name": "a"}, {"name": "b"}, {"name": "c"}, {"name": "d"}],
            [
                {"a": "a", "b": "b"},
                {"a": "b", "b": "c"},
                {"a": "c", "b": "d"},
                {"a": "d", "b": "a"},
            ],
        )
        cycles = find_cycles(graph)
        self.assertEqual(len(cycles), 1)
        self.assertEqual(len(cycles[0]), 4)

    def test_tree_has_no_cycle(self) -> None:
        self.assertEqual(find_cycles(path_graph()), [])

    def test_two_independent_cycles(self) -> None:
        graph = make_graph(
            [{"name": name} for name in ("a", "b", "c", "d", "e")],
            [
                {"a": "a", "b": "b"},
                {"a": "b", "b": "c"},
                {"a": "c", "b": "a"},
                {"a": "c", "b": "d"},
                {"a": "d", "b": "e"},
                {"a": "e", "b": "c"},
            ],
        )
        self.assertEqual(len(find_cycles(graph)), 2)

    def test_cycle_detection_is_deterministic(self) -> None:
        self.assertEqual(find_cycles(triangle_graph()), find_cycles(triangle_graph()))

    def test_single_component(self) -> None:
        components = connected_components(fixture_graph())
        self.assertEqual(len(components), 1)
        self.assertEqual(len(components[0]), 5)

    def test_two_components(self) -> None:
        graph = make_graph(
            [{"name": name} for name in ("a", "b", "c", "d")],
            [{"a": "a", "b": "b"}, {"a": "c", "b": "d"}],
        )
        components = connected_components(graph)
        self.assertEqual(len(components), 2)
        self.assertEqual([len(component) for component in components], [2, 2])


class ArticulationPointTests(unittest.TestCase):
    def test_path_middle_node(self) -> None:
        self.assertEqual(find_articulation_points(path_graph()), ["b"])

    def test_star_center(self) -> None:
        graph = make_graph(
            [{"name": name} for name in ("hub", "l1", "l2", "l3")],
            [
                {"a": "hub", "b": "l1"},
                {"a": "hub", "b": "l2"},
                {"a": "hub", "b": "l3"},
            ],
        )
        self.assertEqual(find_articulation_points(graph), ["hub"])

    def test_triangle_has_no_articulation_point(self) -> None:
        self.assertEqual(find_articulation_points(triangle_graph()), [])

    def test_two_nodes_are_exempt(self) -> None:
        graph = make_graph(
            [{"name": "a"}, {"name": "b"}], [{"a": "a", "b": "b"}]
        )
        self.assertEqual(find_articulation_points(graph), [])

    def test_square_has_no_articulation_point(self) -> None:
        graph = make_graph(
            [{"name": name} for name in ("a", "b", "c", "d")],
            [
                {"a": "a", "b": "b"},
                {"a": "b", "b": "c"},
                {"a": "c", "b": "d"},
                {"a": "d", "b": "a"},
            ],
        )
        self.assertEqual(find_articulation_points(graph), [])


class FindingRuleTests(unittest.TestCase):
    def test_disconnected_topology(self) -> None:
        graph = make_graph(
            [{"name": name} for name in ("a", "b", "c", "d")],
            [{"a": "a", "b": "b"}, {"a": "c", "b": "d"}],
        )
        findings = analyze(graph)
        disconnected = [finding for finding in findings if finding.id == "TOPO-DISCONNECTED"]
        self.assertEqual(len(disconnected), 1)
        self.assertIn("2 disconnected components", disconnected[0].message)
        self.assertEqual(len(disconnected[0].nodes), 4)

    def test_isolated_declared_node(self) -> None:
        graph = make_graph(
            [{"name": "a"}, {"name": "b"}, {"name": "c"}],
            [{"a": "a", "b": "b"}],
        )
        isolated = [finding for finding in analyze(graph) if finding.id == "TOPO-ISOLATED"]
        self.assertEqual(len(isolated), 1)
        self.assertEqual(isolated[0].nodes, ("c",))

    def test_mention_only_node_is_undeclared_not_isolated(self) -> None:
        graph = make_graph(
            [{"name": "a"}, {"name": "b", "declared": False, "has_dump": False, "mentioned_by": ("a",)}],
            [{"a": "a", "b": "b", "symmetric": False}],
        )
        ids = [finding.id for finding in analyze(graph)]
        self.assertIn("TOPO-UNDECLARED", ids)
        self.assertNotIn("TOPO-ISOLATED", ids)

    def test_parallel_links_finding(self) -> None:
        graph = make_graph(
            [{"name": "a"}, {"name": "b"}],
            [
                {"a": "a", "b": "b", "a_port": "Gi0/1", "b_port": "Gi0/1"},
                {"a": "a", "b": "b", "a_port": "Gi0/2", "b_port": "Gi0/2"},
            ],
        )
        parallel = [finding for finding in analyze(graph) if finding.id == "TOPO-PARALLEL"]
        self.assertEqual(len(parallel), 1)
        self.assertEqual(parallel[0].severity, "info")
        self.assertIn("2 connections", parallel[0].message)

    def test_parallel_links_helper(self) -> None:
        graph = make_graph(
            [{"name": "a"}, {"name": "b"}],
            [
                {"a": "a", "b": "b", "a_port": "Gi0/1"},
                {"a": "a", "b": "b", "a_port": "Gi0/2"},
            ],
        )
        parallel = find_parallel_links(graph)
        self.assertEqual(len(parallel), 1)
        self.assertEqual(parallel[0][0], "a")
        self.assertEqual(parallel[0][1], "b")
        self.assertEqual(len(parallel[0][2]), 2)

    def test_asymmetric_requires_both_dumps(self) -> None:
        graph = make_graph(
            [
                {"name": "a"},
                {"name": "b", "declared": False, "has_dump": False, "mentioned_by": ("a",)},
            ],
            [{"a": "a", "b": "b", "symmetric": False, "reported_by": ("a",)}],
        )
        ids = [finding.id for finding in analyze(graph)]
        self.assertNotIn("TOPO-ASYMMETRIC", ids)

    def test_asymmetric_reported_when_both_dumped(self) -> None:
        graph = make_graph(
            [{"name": "a"}, {"name": "b"}],
            [{"a": "a", "b": "b", "symmetric": False, "reported_by": ("a",)}],
        )
        asymmetric = [finding for finding in analyze(graph) if finding.id == "TOPO-ASYMMETRIC"]
        self.assertEqual(len(asymmetric), 1)
        self.assertIn("only a reports", asymmetric[0].message)

    def test_has_errors_false_for_clean_graph(self) -> None:
        self.assertFalse(has_errors(analyze(path_graph())))

    def test_finding_dataclass_defaults(self) -> None:
        finding = Finding(id="TOPO-TEST", severity="info", message="message")
        self.assertEqual(finding.nodes, ())


class StatisticsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.graph = fixture_graph()
        cls.stats = topology_stats(cls.graph, fixture_findings())

    def test_device_counts(self) -> None:
        self.assertEqual(self.stats["devices"], 5)
        self.assertEqual(self.stats["dumped_devices"], 4)
        self.assertEqual(self.stats["declared_devices"], 4)
        self.assertEqual(self.stats["mention_only_devices"], 1)

    def test_edge_counts(self) -> None:
        self.assertEqual(self.stats["edges"], 5)
        self.assertEqual(self.stats["symmetric_edges"], 3)
        self.assertEqual(self.stats["one_sided_edges"], 2)

    def test_protocol_counts(self) -> None:
        self.assertEqual(self.stats["protocol_edge_counts"], {"cdp": 3, "lldp": 5})
        self.assertEqual(self.stats["multi_protocol_edges"], 3)

    def test_components(self) -> None:
        self.assertEqual(self.stats["components"], 1)
        self.assertEqual(self.stats["component_sizes"], [5])

    def test_degree(self) -> None:
        self.assertEqual(self.stats["degree"], {"min": 1, "max": 4, "average": 2.0})

    def test_roles(self) -> None:
        self.assertEqual(self.stats["roles"], {"access": 2, "core": 1, "edge": 1, "unknown": 1})

    def test_isolated_devices(self) -> None:
        self.assertEqual(self.stats["isolated_devices"], [])

    def test_findings_counts(self) -> None:
        self.assertEqual(self.stats["findings"], {"error": 1, "warning": 3, "info": 0})

    def test_single_node_degree(self) -> None:
        graph = make_graph([{"name": "solo"}], [])
        stats = topology_stats(graph, analyze(graph))
        self.assertEqual(stats["degree"], {"min": 0, "max": 0, "average": 0.0})
        self.assertEqual(stats["components"], 1)


if __name__ == "__main__":
    unittest.main()
