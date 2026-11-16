"""Operational risk analysis over a topology graph."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Any

from .graph import Edge, Graph, normalize_device_name

SEVERITY_ORDER = {"error": 0, "warning": 1, "info": 2}


@dataclass(frozen=True)
class Finding:
    """One operational risk detected in the topology."""

    id: str
    severity: str
    message: str
    nodes: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-friendly representation of the finding."""
        return {
            "id": self.id,
            "severity": self.severity,
            "message": self.message,
            "nodes": list(self.nodes),
        }


def _adjacency(graph: Graph) -> dict[str, list[str]]:
    """Return the sorted adjacency lists keyed by device key."""
    return graph.adjacency()


def connected_components(graph: Graph) -> list[list[str]]:
    """Return the connected components of the graph as sorted key lists."""
    adjacency = _adjacency(graph)
    seen: set[str] = set()
    components: list[list[str]] = []
    for start in sorted(adjacency):
        if start in seen:
            continue
        seen.add(start)
        stack = [start]
        component: list[str] = []
        while stack:
            current = stack.pop()
            component.append(current)
            for neighbour in reversed(adjacency[current]):
                if neighbour not in seen:
                    seen.add(neighbour)
                    stack.append(neighbour)
        components.append(sorted(component))
    components.sort(key=lambda component: component[0])
    return components


def _canonical_cycle(path: list[str]) -> tuple[str, ...]:
    """Return a rotation-independent canonical form of an undirected cycle."""
    candidates: list[tuple[str, ...]] = []
    for sequence in (path, list(reversed(path))):
        candidates.extend(
            tuple(sequence[index:] + sequence[:index])
            for index in range(len(sequence))
        )
    return min(candidates)


def find_cycles(graph: Graph) -> list[list[str]]:
    """Return one fundamental cycle per back edge, canonicalised and sorted.

    Each cycle is a list of node keys without the closing repeat; the DFS
    parent chain guarantees a valid undirected path.
    """
    adjacency = _adjacency(graph)
    visited: set[str] = set()
    parent: dict[str, str | None] = {}
    depth: dict[str, int] = {}
    raw_cycles: list[tuple[str, ...]] = []

    def walk(node: str, previous: str | None) -> None:
        visited.add(node)
        parent[node] = previous
        depth[node] = 0 if previous is None else depth[previous] + 1
        for neighbour in adjacency[node]:
            if neighbour == previous:
                continue
            if neighbour not in visited:
                walk(neighbour, node)
            elif depth[neighbour] < depth[node]:
                path = [node]
                cursor = node
                while cursor != neighbour:
                    cursor = parent[cursor]  # type: ignore[assignment]
                    if cursor is None:  # pragma: no cover - defensive
                        break
                    path.append(cursor)
                path.reverse()
                if len(path) >= 3:
                    raw_cycles.append(_canonical_cycle(path))

    for node in sorted(adjacency):
        if node not in visited:
            walk(node, None)
    unique = sorted(set(raw_cycles))
    return [list(cycle) for cycle in unique]


def find_articulation_points(graph: Graph) -> list[str]:
    """Return the articulation points (single points of failure) as node keys."""
    adjacency = _adjacency(graph)
    if len(adjacency) <= 2:
        return []
    discovery: dict[str, int] = {}
    low: dict[str, int] = {}
    parent: dict[str, str | None] = {}
    articulation: set[str] = set()
    clock = [0]

    def walk(node: str) -> None:
        discovery[node] = low[node] = clock[0]
        clock[0] += 1
        children = 0
        for neighbour in adjacency[node]:
            if neighbour not in discovery:
                children += 1
                parent[neighbour] = node
                walk(neighbour)
                low[node] = min(low[node], low[neighbour])
                if parent.get(node) is None and children > 1:
                    articulation.add(node)
                if parent.get(node) is not None and low[neighbour] >= discovery[node]:
                    articulation.add(node)
            elif neighbour != parent.get(node):
                low[node] = min(low[node], discovery[neighbour])

    for node in sorted(adjacency):
        if node not in discovery:
            walk(node)
    return sorted(articulation)


def find_parallel_links(graph: Graph) -> list[tuple[str, str, list[Edge]]]:
    """Return ``(a, b, edges)`` for device pairs connected by multiple links."""
    grouped: dict[tuple[str, str], list[Edge]] = {}
    for edge in graph.edges:
        a_key = normalize_device_name(edge.a)
        b_key = normalize_device_name(edge.b)
        if a_key == b_key:
            continue
        grouped.setdefault(tuple(sorted((a_key, b_key))), []).append(edge)
    parallel: list[tuple[str, str, list[Edge]]] = []
    for pair in sorted(grouped):
        edges = grouped[pair]
        if len(edges) <= 1:
            continue
        parallel.append((graph.nodes[pair[0]].name, graph.nodes[pair[1]].name, edges))
    return parallel


def summarize_findings(findings: list[Finding]) -> dict[str, int]:
    """Return the number of findings per severity (always three keys)."""
    counts = {severity: 0 for severity in SEVERITY_ORDER}
    for finding in findings:
        counts[finding.severity] = counts.get(finding.severity, 0) + 1
    return counts


def has_errors(findings: list[Finding]) -> bool:
    """Return ``True`` when at least one finding has error severity."""
    return any(finding.severity == "error" for finding in findings)


def analyze(graph: Graph) -> list[Finding]:
    """Return every operational risk found in *graph*, deterministically sorted."""
    findings: list[Finding] = []
    adjacency = _adjacency(graph)
    display = {key: node.name for key, node in graph.nodes.items()}

    components = connected_components(graph)
    if len(components) > 1:
        described = " / ".join(
            ", ".join(display[key] for key in component) for component in components
        )
        findings.append(
            Finding(
                id="TOPO-DISCONNECTED",
                severity="warning",
                message=f"Topology is split into {len(components)} disconnected components: {described}",
                nodes=tuple(sorted(display[key] for key in adjacency)),
            )
        )

    for cycle in find_cycles(graph):
        names = [display[key] for key in cycle]
        path = " -> ".join(names + [names[0]])
        findings.append(
            Finding(
                id="TOPO-CYCLE",
                severity="error",
                message=f"Loop detected: {path}",
                nodes=tuple(names),
            )
        )

    for edge in graph.edges:
        if edge.symmetric:
            continue
        reporter = edge.reported_by[0] if edge.reported_by else edge.a
        a_node = graph.node(edge.a)
        b_node = graph.node(edge.b)
        if not (a_node.has_dump and b_node.has_dump):
            continue
        findings.append(
            Finding(
                id="TOPO-ASYMMETRIC",
                severity="warning",
                message=(
                    f"One-sided link between {edge.a} and {edge.b}: only {reporter} "
                    "reports the connection"
                ),
                nodes=(edge.a, edge.b),
            )
        )

    for node in sorted(graph.nodes.values(), key=lambda item: item.key):
        if not node.declared:
            seen_from = ", ".join(node.mentioned_by)
            detail = f" (seen from {seen_from})" if seen_from else ""
            findings.append(
                Finding(
                    id="TOPO-UNDECLARED",
                    severity="warning",
                    message=f"Device mentioned but not dumped: {node.name}{detail}",
                    nodes=(node.name,),
                )
            )

    for node in sorted(graph.nodes.values(), key=lambda item: item.key):
        if node.declared and not adjacency.get(node.key):
            findings.append(
                Finding(
                    id="TOPO-ISOLATED",
                    severity="warning",
                    message=f"Isolated device with no neighbour records: {node.name}",
                    nodes=(node.name,),
                )
            )

    for a_name, b_name, edges in find_parallel_links(graph):
        pair = tuple(sorted((a_name, b_name), key=str.casefold))
        findings.append(
            Finding(
                id="TOPO-PARALLEL",
                severity="info",
                message=(
                    f"Parallel links between {pair[0]} and {pair[1]}: "
                    f"{len(edges)} connections"
                ),
                nodes=pair,
            )
        )

    for key in find_articulation_points(graph):
        findings.append(
            Finding(
                id="TOPO-SPOF",
                severity="warning",
                message=(
                    f"Single point of failure: {display[key]} "
                    "(removing it partitions the topology)"
                ),
                nodes=(display[key],),
            )
        )

    findings.sort(
        key=lambda finding: (
            SEVERITY_ORDER.get(finding.severity, len(SEVERITY_ORDER)),
            finding.id,
            finding.message,
            finding.nodes,
        )
    )
    return findings


def topology_stats(graph: Graph, findings: list[Finding]) -> dict[str, Any]:
    """Return aggregate topology statistics for the ``stats`` command."""
    adjacency = _adjacency(graph)
    degrees = [len(neighbours) for neighbours in adjacency.values()]
    components = connected_components(graph)
    role_counts = Counter(node.role for node in graph.nodes.values())
    protocol_counts = Counter(
        protocol for edge in graph.edges for protocol in edge.protocols
    )
    isolated = [
        node.name
        for node in graph.nodes.values()
        if node.declared and not adjacency.get(node.key)
    ]
    return {
        "devices": graph.device_count,
        "dumped_devices": sum(1 for node in graph.nodes.values() if node.has_dump),
        "declared_devices": sum(1 for node in graph.nodes.values() if node.declared),
        "mention_only_devices": sum(1 for node in graph.nodes.values() if not node.declared),
        "edges": graph.edge_count,
        "symmetric_edges": sum(1 for edge in graph.edges if edge.symmetric),
        "one_sided_edges": sum(1 for edge in graph.edges if not edge.symmetric),
        "protocol_edge_counts": dict(sorted(protocol_counts.items())),
        "multi_protocol_edges": sum(1 for edge in graph.edges if len(edge.protocols) > 1),
        "components": len(components),
        "component_sizes": [len(component) for component in components],
        "isolated_devices": isolated,
        "degree": {
            "min": min(degrees) if degrees else 0,
            "max": max(degrees) if degrees else 0,
            "average": round(sum(degrees) / len(degrees), 2) if degrees else 0.0,
        },
        "roles": dict(sorted(role_counts.items())),
        "findings": summarize_findings(findings),
    }
