"""Tests for the text, Mermaid, DOT, JSON and HTML renderers."""

from __future__ import annotations

import json
import unittest

from helpers import fixture_findings, fixture_graph, make_finding, make_graph

from topomapper import __version__
from topomapper.render import (
    format_table,
    render_dot,
    render_html,
    render_json,
    render_mermaid,
    render_text,
)


def clean_graph():
    return make_graph(
        [
            {"name": "a", "role": "core", "mgmt_ip": "192.0.2.1"},
            {"name": "b", "role": "access", "mgmt_ip": "192.0.2.2"},
        ],
        [{"a": "a", "b": "b", "a_port": "Gi0/1", "b_port": "Gi0/1"}],
    )


def risky_graph():
    return make_graph(
        [
            {"name": "a", "role": "core", "mgmt_ip": "192.0.2.1"},
            {"name": "b", "role": "access", "mgmt_ip": "192.0.2.2"},
            {"name": "c", "role": "access", "mgmt_ip": "192.0.2.3"},
        ],
        [
            {"a": "a", "b": "b", "a_port": "Gi0/1", "b_port": "Gi0/1"},
            {
                "a": "b",
                "b": "c",
                "a_port": "Gi0/2",
                "b_port": "Gi0/1",
                "symmetric": False,
                "reported_by": ("b",),
            },
        ],
    )


RISK_FINDINGS = [
    make_finding("TOPO-CYCLE", "error", "Loop detected: a -> b -> c -> a", ("a", "b", "c")),
    make_finding("TOPO-ASYMMETRIC", "warning", "One-sided link between b and c", ("b", "c")),
]


def severity_graph():
    return make_graph(
        [{"name": name} for name in ("a", "b", "c", "d")],
        [],
    )


SEVERITY_FINDINGS = [
    make_finding("TOPO-CYCLE", "error", "error on a", ("a",)),
    make_finding("TOPO-UNDECLARED", "warning", "warning on b", ("b",)),
    make_finding("TOPO-PARALLEL", "info", "info on c", ("c",)),
]


class TextRenderTests(unittest.TestCase):
    def test_format_table(self) -> None:
        table = format_table(("ID", "Severity"), [("TOPO-CYCLE", "error")])
        self.assertIn("ID", table)
        self.assertIn("----------", table)
        self.assertIn("TOPO-CYCLE", table)

    def test_clean_report_passes(self) -> None:
        output = render_text(clean_graph(), [])
        self.assertIn("Devices", output)
        self.assertIn("Links", output)
        self.assertIn("Result: PASSED", output)
        self.assertNotIn("TOPO-", output)

    def test_findings_report_fails(self) -> None:
        output = render_text(risky_graph(), RISK_FINDINGS)
        self.assertIn("TOPO-CYCLE", output)
        self.assertIn("TOPO-ASYMMETRIC", output)
        self.assertIn("Result: FAILED", output)
        self.assertIn("1 error, 1 warning", output)


class MermaidRenderTests(unittest.TestCase):
    def test_starts_with_graph_direction(self) -> None:
        self.assertTrue(render_mermaid(clean_graph(), []).startswith("graph LR\n"))

    def test_node_labels_and_edges(self) -> None:
        output = render_mermaid(clean_graph(), [])
        self.assertIn('n0["a<br/>core | 192.0.2.1"]', output)
        self.assertIn("n0 ---", output)
        self.assertIn("Gi0/1 &lt;-&gt; Gi0/1", output)

    def test_one_sided_edge_uses_dotted_connector(self) -> None:
        self.assertIn("-.-", render_mermaid(risky_graph(), RISK_FINDINGS))

    def test_severity_classes_are_applied(self) -> None:
        output = render_mermaid(risky_graph(), RISK_FINDINGS)
        self.assertIn("classDef error", output)
        self.assertIn("classDef warning", output)
        self.assertIn("class n0,n1,n2 error", output)

    def test_no_classes_without_findings(self) -> None:
        output = render_mermaid(clean_graph(), [])
        self.assertNotIn("classDef", output)

    def test_labels_are_escaped(self) -> None:
        graph = make_graph(
            [{"name": "sw<1>", "role": "core"}], []
        )
        output = render_mermaid(graph, [])
        self.assertIn("sw&lt;1&gt;", output)
        self.assertNotIn("sw<1>", output)

    def test_deterministic(self) -> None:
        self.assertEqual(
            render_mermaid(risky_graph(), RISK_FINDINGS),
            render_mermaid(risky_graph(), RISK_FINDINGS),
        )


class DotRenderTests(unittest.TestCase):
    def test_document_structure(self) -> None:
        output = render_dot(clean_graph(), [])
        self.assertTrue(output.startswith("graph topology {\n"))
        self.assertTrue(output.endswith("}\n"))
        self.assertEqual(output.count('"a" [label='), 1)

    def test_multiline_labels(self) -> None:
        self.assertIn('label="a\\ncore | 192.0.2.1"', render_dot(clean_graph(), []))

    def test_one_sided_edge_is_dashed(self) -> None:
        output = render_dot(risky_graph(), RISK_FINDINGS)
        self.assertIn('"b" -- "c" [label="Gi0/2 <-> Gi0/1", style=dashed];', output)

    def test_severity_colors(self) -> None:
        output = render_dot(severity_graph(), SEVERITY_FINDINGS)
        self.assertIn('fillcolor="#f8d7da"', output)
        self.assertIn('fillcolor="#fff3cd"', output)
        self.assertIn('fillcolor="#d1e7dd"', output)
        self.assertIn('fillcolor="#e2e8f0"', output)

    def test_quotes_are_escaped(self) -> None:
        graph = make_graph([{"name": 'sw"1', "role": "core"}], [])
        output = render_dot(graph, [])
        self.assertIn('"sw\\"1" [label="sw\\"1', output)

    def test_deterministic(self) -> None:
        self.assertEqual(
            render_dot(risky_graph(), RISK_FINDINGS),
            render_dot(risky_graph(), RISK_FINDINGS),
        )


class JsonRenderTests(unittest.TestCase):
    def test_document_fields(self) -> None:
        document = json.loads(render_json(clean_graph(), []))
        self.assertEqual(document["schema_version"], 1)
        self.assertEqual(len(document["nodes"]), 2)
        self.assertEqual(len(document["edges"]), 1)
        self.assertEqual(document["generated_by"], f"topomapper {__version__}")

    def test_findings_are_included(self) -> None:
        document = json.loads(render_json(risky_graph(), RISK_FINDINGS))
        self.assertEqual(len(document["findings"]), 2)
        self.assertEqual(document["findings_summary"], {"error": 1, "warning": 1, "info": 0})

    def test_findings_omitted_when_not_requested(self) -> None:
        document = json.loads(render_json(clean_graph()))
        self.assertNotIn("findings", document)

    def test_fixture_json_summary(self) -> None:
        document = json.loads(render_json(fixture_graph(), fixture_findings()))
        self.assertEqual(document["summary"]["devices"], 5)
        self.assertEqual(len(document["findings"]), 4)

    def test_deterministic(self) -> None:
        self.assertEqual(
            render_json(fixture_graph(), fixture_findings()),
            render_json(fixture_graph(), fixture_findings()),
        )


class HtmlRenderTests(unittest.TestCase):
    def test_document_structure(self) -> None:
        output = render_html(clean_graph(), [])
        self.assertTrue(output.startswith("<!DOCTYPE html>"))
        self.assertIn('<svg xmlns="http://www.w3.org/2000/svg"', output)
        self.assertIn("</html>", output)
        self.assertIn(f"Generated by topomapper {__version__}", output)

    def test_legend_is_present(self) -> None:
        output = render_html(clean_graph(), [])
        self.assertIn("Legend", output)
        self.assertIn("Dashed orange links", output)

    def test_clean_page_says_no_findings(self) -> None:
        self.assertIn("No findings detected.", render_html(clean_graph(), []))

    def test_findings_table(self) -> None:
        output = render_html(risky_graph(), RISK_FINDINGS)
        self.assertIn("TOPO-CYCLE", output)
        self.assertIn("Loop detected: a -&gt; b -&gt; c -&gt; a", output)

    def test_severity_colors_in_svg(self) -> None:
        output = render_html(severity_graph(), SEVERITY_FINDINGS)
        self.assertIn('fill="#f8d7da"', output)
        self.assertIn('fill="#fff3cd"', output)
        self.assertIn('fill="#d1e7dd"', output)
        self.assertIn('fill="#e2e8f0"', output)

    def test_html_escaping_of_messages(self) -> None:
        findings = [make_finding("TOPO-TEST", "error", '<script>alert("x")</script>', ("a",))]
        output = render_html(risky_graph(), findings)
        self.assertNotIn("<script>", output)
        self.assertIn("&lt;script&gt;", output)

    def test_html_escaping_of_node_names(self) -> None:
        graph = make_graph([{"name": "<sw1>", "role": "core"}], [])
        output = render_html(graph, [])
        self.assertIn("&lt;sw1&gt;", output)
        self.assertNotIn("<sw1>", output)

    def test_title_is_escaped(self) -> None:
        output = render_html(clean_graph(), [], title="Topology <lab>")
        self.assertIn("&lt;lab&gt;", output)
        self.assertNotIn("Topology <lab>", output)

    def test_deterministic(self) -> None:
        self.assertEqual(
            render_html(fixture_graph(), fixture_findings()),
            render_html(fixture_graph(), fixture_findings()),
        )


if __name__ == "__main__":
    unittest.main()
