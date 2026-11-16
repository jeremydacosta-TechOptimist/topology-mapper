"""Exporters for topology maps: text, Mermaid, Graphviz DOT, JSON and HTML."""

from __future__ import annotations

import html
import json
import math
from collections.abc import Iterable, Sequence
from typing import Any

from . import __version__
from .analysis import SEVERITY_ORDER, summarize_findings
from .graph import Edge, Graph, Node, normalize_device_name

_SEVERITY_LABELS = {
    "error": "Error",
    "warning": "Warning",
    "info": "Info",
}
_SEVERITY_COLORS = {
    "error": ("#f8d7da", "#b02a37"),
    "warning": ("#fff3cd", "#997404"),
    "info": ("#d1e7dd", "#146c43"),
    "": ("#e2e8f0", "#475569"),
}


def _count_label(count: int, singular: str, plural: str | None = None) -> str:
    """Return a singular or plural count phrase."""
    word = singular if count == 1 else (plural if plural is not None else f"{singular}s")
    return f"{count} {word}"


def format_table(headers: Sequence[str], rows: Iterable[Sequence[Any]]) -> str:
    """Render rows as a left-aligned plain-text table."""
    rendered = [[str(cell) for cell in row] for row in rows]
    widths = [len(header) for header in headers]
    for row in rendered:
        for index, cell in enumerate(row):
            widths[index] = max(widths[index], len(cell))
    lines = [
        "  ".join(header.ljust(widths[index]) for index, header in enumerate(headers)).rstrip(),
        "  ".join("-" * width for width in widths).rstrip(),
    ]
    for row in rendered:
        lines.append("  ".join(cell.ljust(widths[index]) for index, cell in enumerate(row)).rstrip())
    return "\n".join(lines)


def _severity_by_node(graph: Graph, findings: Sequence[Any]) -> dict[str, str]:
    """Return the worst finding severity for every involved node key."""
    best: dict[str, str] = {}
    for finding in findings:
        severity = getattr(finding, "severity", "")
        for name in getattr(finding, "nodes", ()):
            key = normalize_device_name(name)
            if not key:
                continue
            current = best.get(key)
            if current is None or SEVERITY_ORDER.get(severity, 9) < SEVERITY_ORDER.get(current, 9):
                best[key] = severity
    return best


def _edge_label(edge: Edge, arrow: str = " <-> ") -> str:
    """Return the port label for an edge."""
    if edge.a_port and edge.b_port:
        return f"{edge.a_port}{arrow}{edge.b_port}"
    if edge.a_port:
        return f"{edge.a_port}{arrow}?"
    if edge.b_port:
        return f"?{arrow}{edge.b_port}"
    return ""


def _node_detail(node: Node) -> str:
    """Return a one-line detail string for a node."""
    parts = [node.role]
    if node.mgmt_ip:
        parts.append(node.mgmt_ip)
    if not node.has_dump:
        parts.append("not dumped")
    return " | ".join(part for part in parts if part)


def render_text(graph: Graph, findings: Sequence[Any]) -> str:
    """Render a human-readable topology report with a findings table."""
    summary = graph.summary()
    counts = summarize_findings(list(findings))
    lines = [
        format_table(
            ("Metric", "Value"),
            (
                ("Devices", f"{summary['devices']} ({summary['dumped_devices']} dumped, "
                             f"{summary['mention_only_devices']} mention-only)"),
                ("Links", f"{summary['edges']} ({summary['symmetric_edges']} symmetric, "
                          f"{summary['one_sided_edges']} one-sided)"),
                ("Protocols", f"lldp {summary['lldp_edges']} edges, cdp {summary['cdp_edges']} edges"),
                (
                    "Findings",
                    f"{_count_label(counts['error'], 'error')}, "
                    f"{_count_label(counts['warning'], 'warning')}, "
                    f"{_count_label(counts['info'], 'info', 'info')}",
                ),
            ),
        )
    ]
    if findings:
        lines.append("")
        lines.append(
            format_table(
                ("ID", "Severity", "Nodes", "Message"),
                (
                    (
                        finding.id,
                        finding.severity,
                        ", ".join(finding.nodes),
                        finding.message,
                    )
                    for finding in findings
                ),
            )
        )
    lines.append("")
    lines.append("Result: FAILED (error-level findings)" if counts["error"] else "Result: PASSED")
    return "\n".join(lines)


def _escape_mermaid(text: str) -> str:
    return html.escape(" ".join(text.split()), quote=True)


def render_mermaid(graph: Graph, findings: Sequence[Any]) -> str:
    """Render the graph as a Mermaid ``graph LR`` diagram."""
    nodes = sorted(graph.nodes.values(), key=lambda node: node.key)
    identifiers = {node.key: f"n{index}" for index, node in enumerate(nodes)}
    severity = _severity_by_node(graph, findings)
    lines = ["graph LR"]
    for node in nodes:
        detail = _node_detail(node)
        label = f"{_escape_mermaid(node.name)}<br/>{_escape_mermaid(detail)}" if detail else _escape_mermaid(node.name)
        lines.append(f'    {identifiers[node.key]}["{label}"]')
    for edge in graph.edges:
        a_id = identifiers.get(normalize_device_name(edge.a))
        b_id = identifiers.get(normalize_device_name(edge.b))
        if a_id is None or b_id is None:
            continue
        connector = "---" if edge.symmetric else "-.-"
        label = _edge_label(edge)
        if label:
            lines.append(f'    {a_id} {connector}|"{_escape_mermaid(label)}"| {b_id}')
        else:
            lines.append(f"    {a_id} {connector} {b_id}")
    styled = {
        severity_name: [
            identifiers[key]
            for key in identifiers
            if severity.get(key) == severity_name
        ]
        for severity_name in ("error", "warning", "info")
    }
    if any(styled.values()):
        lines.append("    classDef error fill:#f8d7da,stroke:#b02a37,stroke-width:2px")
        lines.append("    classDef warning fill:#fff3cd,stroke:#997404,stroke-width:2px")
        lines.append("    classDef info fill:#d1e7dd,stroke:#146c43,stroke-width:2px")
        for severity_name in ("error", "warning", "info"):
            if styled[severity_name]:
                lines.append(f"    class {','.join(styled[severity_name])} {severity_name}")
    return "\n".join(lines) + "\n"


def _escape_dot(text: str) -> str:
    return (
        text.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", "\\n")
    )


def render_dot(graph: Graph, findings: Sequence[Any]) -> str:
    """Render the graph as a Graphviz DOT document."""
    severity = _severity_by_node(graph, findings)
    lines = [
        "graph topology {",
        "    graph [rankdir=LR]",
        '    node [shape=box, style="rounded,filled", fontname="Helvetica", color="#475569"]',
        '    edge [fontname="Helvetica", fontsize=9, color="#64748b"]',
    ]
    for node in sorted(graph.nodes.values(), key=lambda item: item.key):
        label = node.name
        detail = _node_detail(node)
        if detail:
            label = f"{label}\n{detail}"
        fill, stroke = _SEVERITY_COLORS.get(severity.get(node.key, ""), _SEVERITY_COLORS[""])
        lines.append(
            f'    "{_escape_dot(node.name)}" '
            f'[label="{_escape_dot(label)}", fillcolor="{fill}", color="{stroke}"];'
        )
    for edge in graph.edges:
        attributes = []
        label = _edge_label(edge)
        if label:
            attributes.append(f'label="{_escape_dot(label)}"')
        if not edge.symmetric:
            attributes.append("style=dashed")
        suffix = f" [{', '.join(attributes)}]" if attributes else ""
        lines.append(
            f'    "{_escape_dot(edge.a)}" -- "{_escape_dot(edge.b)}"{suffix};'
        )
    lines.append("}")
    return "\n".join(lines) + "\n"


def render_json(graph: Graph, findings: Sequence[Any] | None = None) -> str:
    """Render the graph (and optional findings) as an indented JSON document."""
    document: dict[str, Any] = graph.to_dict()
    if findings is not None:
        serialized = [finding.to_dict() for finding in findings]
        document["findings"] = serialized
        document["findings_summary"] = summarize_findings(list(findings))
    document["generated_by"] = f"topomapper {__version__}"
    return json.dumps(document, indent=2, ensure_ascii=False) + "\n"


def _svg_text(x: float, y: float, text: str, css_class: str) -> str:
    return (
        f'<text x="{x:.1f}" y="{y:.1f}" class="{css_class}" '
        f'text-anchor="middle">{html.escape(text)}</text>'
    )


def _svg_node(node: Node, x: float, y: float, severity: str) -> list[str]:
    fill, stroke = _SEVERITY_COLORS.get(severity, _SEVERITY_COLORS[""])
    detail = _node_detail(node)
    parts = [
        f'<g class="node">',
        f'<circle cx="{x:.1f}" cy="{y:.1f}" r="42" fill="{fill}" stroke="{stroke}" stroke-width="2"/>',
        _svg_text(x, y - 1, node.name, "node-name"),
    ]
    if detail:
        parts.append(_svg_text(x, y + 15, detail, "node-detail"))
    parts.append("</g>")
    return parts


def render_html(
    graph: Graph,
    findings: Sequence[Any],
    title: str = "Network topology map",
) -> str:
    """Render a standalone HTML page with a static SVG circular map."""
    nodes = sorted(graph.nodes.values(), key=lambda node: node.key)
    width, height = 980.0, 620.0
    center_x, center_y = width / 2, 300.0
    radius = 215.0 if len(nodes) > 1 else 0.0
    positions: dict[str, tuple[float, float]] = {}
    for index, node in enumerate(nodes):
        angle = (2 * math.pi * index / len(nodes)) - (math.pi / 2)
        positions[node.key] = (
            center_x + radius * math.cos(angle),
            center_y + radius * math.sin(angle),
        )
    severity = _severity_by_node(graph, findings)
    summary = graph.summary()
    counts = summarize_findings(list(findings))

    svg: list[str] = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width:.0f} {height:.0f}" '
        'role="img" aria-label="Network topology map">'
    ]
    for edge in graph.edges:
        a_key = normalize_device_name(edge.a)
        b_key = normalize_device_name(edge.b)
        if a_key not in positions or b_key not in positions:
            continue
        x1, y1 = positions[a_key]
        x2, y2 = positions[b_key]
        css_class = "edge" if edge.symmetric else "edge one-sided"
        svg.append(
            f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" class="{css_class}"/>'
        )
        label = _edge_label(edge, " - ")
        if label:
            svg.append(
                f'<text x="{(x1 + x2) / 2:.1f}" y="{(y1 + y2) / 2 - 4:.1f}" '
                f'class="edge-label" text-anchor="middle">{html.escape(label)}</text>'
            )
    for node in nodes:
        x, y = positions[node.key]
        svg.extend(_svg_node(node, x, y, severity.get(node.key, "")))
    svg.append("</svg>")

    legend = "".join(
        f'<li><span class="swatch {name}"></span>{label}</li>'
        for name, label in _SEVERITY_LABELS.items()
    )
    finding_rows: list[str] = []
    for finding in findings:
        finding_rows.append(
            "<tr>"
            f'<td>{html.escape(finding.id)}</td>'
            f'<td><span class="badge {html.escape(finding.severity)}">'
            f"{html.escape(finding.severity)}</span></td>"
            f"<td>{html.escape(', '.join(finding.nodes))}</td>"
            f"<td>{html.escape(finding.message)}</td>"
            "</tr>"
        )
    findings_section = (
        "<table><thead><tr><th>ID</th><th>Severity</th><th>Nodes</th><th>Message</th></tr></thead>"
        "<tbody>" + "".join(finding_rows) + "</tbody></table>"
        if finding_rows
        else "<p>No findings detected.</p>"
    )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(title)}</title>
<style>
:root {{
  color-scheme: light;
  --ink: #1e293b;
  --muted: #64748b;
  --line: #cbd5e1;
  --page: #f8fafc;
}}
* {{
  box-sizing: border-box;
}}
body {{
  margin: 0;
  padding: 24px;
  background: var(--page);
  color: var(--ink);
  font-family: "Segoe UI", system-ui, -apple-system, sans-serif;
}}
header {{
  max-width: 1040px;
  margin: 0 auto 16px;
}}
h1 {{
  margin: 0 0 4px;
  font-size: 1.6rem;
}}
.subtitle, footer {{
  color: var(--muted);
  font-size: 0.9rem;
}}
main {{
  display: grid;
  grid-template-columns: minmax(0, 3fr) minmax(220px, 1fr);
  gap: 16px;
  max-width: 1040px;
  margin: 0 auto;
}}
section {{
  background: #ffffff;
  border: 1px solid var(--line);
  border-radius: 10px;
  padding: 16px;
}}
section.map {{
  grid-column: 1 / -1;
}}
h2 {{
  margin: 0 0 12px;
  font-size: 1.05rem;
}}
svg {{
  display: block;
  width: 100%;
  height: auto;
}}
.edge {{
  stroke: #94a3b8;
  stroke-width: 2;
}}
.edge.one-sided {{
  stroke: #b45309;
  stroke-dasharray: 6 4;
}}
.edge-label {{
  fill: #475569;
  font-size: 10px;
}}
.node-name {{
  fill: #1e293b;
  font-size: 12px;
  font-weight: 600;
}}
.node-detail {{
  fill: #475569;
  font-size: 9px;
}}
ul.legend {{
  list-style: none;
  margin: 0;
  padding: 0;
  display: grid;
  gap: 8px;
}}
.swatch {{
  display: inline-block;
  width: 14px;
  height: 14px;
  margin-right: 8px;
  border-radius: 4px;
  border: 2px solid #475569;
  vertical-align: -2px;
}}
.swatch.error {{
  background: #f8d7da;
  border-color: #b02a37;
}}
.swatch.warning {{
  background: #fff3cd;
  border-color: #997404;
}}
.swatch.info {{
  background: #d1e7dd;
  border-color: #146c43;
}}
table {{
  width: 100%;
  border-collapse: collapse;
  font-size: 0.88rem;
}}
th, td {{
  text-align: left;
  padding: 7px 10px;
  border-bottom: 1px solid var(--line);
  vertical-align: top;
}}
th {{
  color: var(--muted);
  font-weight: 600;
}}
.badge {{
  display: inline-block;
  padding: 1px 8px;
  border-radius: 999px;
  font-size: 0.78rem;
  font-weight: 600;
}}
.badge.error {{
  background: #f8d7da;
  color: #842029;
}}
.badge.warning {{
  background: #fff3cd;
  color: #664d03;
}}
.badge.info {{
  background: #d1e7dd;
  color: #0f5132;
}}
footer {{
  max-width: 1040px;
  margin: 16px auto 0;
}}
@media (max-width: 760px) {{
  main {{
    grid-template-columns: 1fr;
  }}
}}
</style>
</head>
<body>
<header>
  <h1>{html.escape(title)}</h1>
  <p class="subtitle">{_count_label(summary['devices'], 'device')}, {_count_label(summary['edges'], 'link')}, {_count_label(counts['error'], 'error')}, {_count_label(counts['warning'], 'warning')}, {_count_label(counts['info'], 'info', 'info')}</p>
</header>
<main>
  <section class="map">
    {''.join(svg)}
  </section>
  <section class="legend">
    <h2>Legend</h2>
    <ul class="legend">{legend}</ul>
    <p class="subtitle">Dashed orange links are reported by one device only.</p>
  </section>
  <section class="findings">
    <h2>Findings</h2>
    {findings_section}
  </section>
</main>
<footer>Generated by topomapper {__version__}</footer>
</body>
</html>
"""
