"""Command-line interface for the topology mapper."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from . import __version__
from .analysis import analyze, has_errors, summarize_findings, topology_stats
from .errors import EXIT_OK, EXIT_RUNTIME, EXIT_USAGE, NetopsError
from .graph import load_dump_files, load_graph
from .parsers import parse_device_text
from .render import (
    format_table,
    render_dot,
    render_html,
    render_json,
    render_mermaid,
    render_text,
)

_JSON_HELP = "print JSON instead of text"


def _count_label(count: int, singular: str, plural: str | None = None) -> str:
    """Return a singular or plural count phrase."""
    word = singular if count == 1 else (plural if plural is not None else f"{singular}s")
    return f"{count} {word}"


def _write_output(path: str, content: str) -> None:
    """Write *content* to *path*, creating parent directories as needed."""
    target = Path(path)
    try:
        if target.parent != Path("."):
            target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8", newline="\n")
    except OSError as exc:
        raise NetopsError(f"cannot write {target}: {exc}") from exc


def _neighbor_sort_key(neighbor: Any) -> tuple[str, str, str, str]:
    return (
        neighbor.local_device.casefold(),
        neighbor.protocol,
        neighbor.local_port.casefold(),
        neighbor.remote_name.casefold(),
    )


def _cmd_parse(args: argparse.Namespace) -> int:
    dumps = load_dump_files(args.directory)
    if args.name is not None:
        if len(dumps) != 1:
            raise NetopsError("--name can only be used with a single device dump")
        dumps = [(args.name, dumps[0][1])]
    neighbors = []
    for local_name, text in dumps:
        neighbors.extend(parse_device_text(text, local_name))
    neighbors.sort(key=_neighbor_sort_key)
    lldp_count = sum(1 for neighbor in neighbors if neighbor.protocol == "lldp")
    cdp_count = sum(1 for neighbor in neighbors if neighbor.protocol == "cdp")
    devices = sorted({neighbor.local_device for neighbor in neighbors}, key=str.casefold)
    if args.json:
        print(
            json.dumps(
                {
                    "neighbors": [neighbor.to_dict() for neighbor in neighbors],
                    "counts": {
                        "total": len(neighbors),
                        "lldp": lldp_count,
                        "cdp": cdp_count,
                    },
                    "devices": devices,
                },
                indent=2,
                ensure_ascii=False,
            )
        )
        return EXIT_OK
    rows = [
        (
            neighbor.local_device,
            neighbor.protocol,
            neighbor.local_port or "-",
            neighbor.remote_name,
            neighbor.remote_port or "-",
            neighbor.mgmt_ip or "-",
        )
        for neighbor in neighbors
    ]
    print(
        format_table(
            ("Device", "Protocol", "Local port", "Remote device", "Remote port", "Mgmt IP"),
            rows,
        )
    )
    print()
    print(
        f"{len(neighbors)} neighbor records ({lldp_count} LLDP, {cdp_count} CDP) "
        f"from {len(dumps)} device dumps"
    )
    return EXIT_OK


def _cmd_build(args: argparse.Namespace) -> int:
    graph = load_graph(args.directory, args.inventory)
    findings = analyze(graph)
    _write_output(args.out, render_json(graph, findings))
    print(
        f"Wrote graph JSON: {graph.device_count} devices, {graph.edge_count} edges, "
        f"{len(findings)} findings -> {args.out}"
    )
    return EXIT_OK


def _cmd_check(args: argparse.Namespace) -> int:
    graph = load_graph(args.directory, args.inventory)
    findings = analyze(graph)
    counts = summarize_findings(findings)
    if args.json:
        print(
            json.dumps(
                {
                    "devices": graph.device_count,
                    "edges": graph.edge_count,
                    "counts": counts,
                    "findings": [finding.to_dict() for finding in findings],
                },
                indent=2,
                ensure_ascii=False,
            )
        )
        return EXIT_RUNTIME if has_errors(findings) else EXIT_OK
    print(f"Topology check: {args.directory}")
    print(render_text(graph, findings))
    return EXIT_RUNTIME if has_errors(findings) else EXIT_OK


def _cmd_stats(args: argparse.Namespace) -> int:
    graph = load_graph(args.directory, args.inventory)
    findings = analyze(graph)
    stats = topology_stats(graph, findings)
    if args.json:
        print(json.dumps(stats, indent=2, ensure_ascii=False))
        return EXIT_OK
    degree = stats["degree"]
    protocol_counts = stats["protocol_edge_counts"]
    roles = stats["roles"]
    print(f"Topology statistics: {args.directory}")
    print()
    print(
        format_table(
            ("Metric", "Value"),
            (
                (
                    "Devices",
                    f"{stats['devices']} ({stats['dumped_devices']} dumped, "
                    f"{stats['declared_devices']} declared, "
                    f"{stats['mention_only_devices']} mention-only)",
                ),
                (
                    "Links",
                    f"{stats['edges']} ({stats['symmetric_edges']} symmetric, "
                    f"{stats['one_sided_edges']} one-sided)",
                ),
                (
                    "Protocols",
                    f"lldp {protocol_counts.get('lldp', 0)}, "
                    f"cdp {protocol_counts.get('cdp', 0)}, "
                    f"merged {stats['multi_protocol_edges']}",
                ),
                (
                    "Components",
                    f"{stats['components']} (sizes: "
                    f"{', '.join(str(size) for size in stats['component_sizes'])})",
                ),
                (
                    "Degree",
                    f"min {degree['min']}, max {degree['max']}, "
                    f"average {degree['average']}",
                ),
                (
                    "Roles",
                    ", ".join(f"{role} {count}" for role, count in roles.items()) or "-",
                ),
                (
                    "Isolated",
                    ", ".join(stats["isolated_devices"]) or "none",
                ),
                (
                    "Findings",
                    f"{_count_label(stats['findings']['error'], 'error')}, "
                    f"{_count_label(stats['findings']['warning'], 'warning')}, "
                    f"{_count_label(stats['findings']['info'], 'info', 'info')}",
                ),
            ),
        )
    )
    return EXIT_OK


def _cmd_export(args: argparse.Namespace) -> int:
    graph = load_graph(args.directory, args.inventory)
    findings = analyze(graph)
    labels = {"mermaid": "Mermaid", "dot": "Graphviz DOT", "json": "JSON", "html": "HTML"}
    if args.format == "mermaid":
        content = render_mermaid(graph, findings)
    elif args.format == "dot":
        content = render_dot(graph, findings)
    elif args.format == "html":
        content = render_html(graph, findings)
    else:
        content = render_json(graph, findings)
    _write_output(args.out, content)
    print(
        f"Wrote {labels[args.format]} map: {graph.device_count} devices, "
        f"{graph.edge_count} edges -> {args.out}"
    )
    return EXIT_OK


def _cmd_version(args: argparse.Namespace) -> int:
    print(f"topomapper {__version__}")
    return EXIT_OK


def _add_inventory(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--inventory",
        metavar="FILE",
        help="JSON inventory declaring device names, roles and management IPs",
    )


def _add_directory(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--dir",
        dest="directory",
        required=True,
        metavar="DIR",
        help="directory containing <device>.txt LLDP/CDP dumps",
    )


def build_parser() -> argparse.ArgumentParser:
    """Build the argparse command tree."""
    parser = argparse.ArgumentParser(
        prog="topomapper",
        description="Build network topology maps from LLDP and CDP neighbor dumps.",
        epilog="Run 'topomapper COMMAND --help' for the options of each command.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    subparsers = parser.add_subparsers(dest="command", metavar="COMMAND")

    parse_parser = subparsers.add_parser(
        "parse",
        help="Parse neighbor dumps and list the extracted records.",
        description="Parse every LLDP and CDP record in the device dumps.",
    )
    _add_directory(parse_parser)
    parse_parser.add_argument("--json", action="store_true", help=_JSON_HELP)
    parse_parser.add_argument(
        "--name",
        metavar="NAME",
        help="override the local device name (only valid with a single dump)",
    )
    parse_parser.set_defaults(handler=_cmd_parse)

    build_parser_ = subparsers.add_parser(
        "build",
        help="Build the topology graph and write it as JSON.",
        description="Build the topology graph and write a JSON document.",
    )
    _add_directory(build_parser_)
    _add_inventory(build_parser_)
    build_parser_.add_argument(
        "--out", required=True, metavar="FILE", help="output graph JSON file"
    )
    build_parser_.set_defaults(handler=_cmd_build)

    check_parser = subparsers.add_parser(
        "check",
        help="Analyze the topology and report operational risks.",
        description="Report loops, one-sided links, missing devices, parallel links and SPOFs.",
    )
    _add_directory(check_parser)
    _add_inventory(check_parser)
    check_parser.add_argument("--json", action="store_true", help=_JSON_HELP)
    check_parser.set_defaults(handler=_cmd_check)

    stats_parser = subparsers.add_parser(
        "stats",
        help="Print topology statistics.",
        description="Print device, link, component and degree statistics.",
    )
    _add_directory(stats_parser)
    _add_inventory(stats_parser)
    stats_parser.add_argument("--json", action="store_true", help=_JSON_HELP)
    stats_parser.set_defaults(handler=_cmd_stats)

    export_parser = subparsers.add_parser(
        "export",
        help="Export the topology as Mermaid, DOT, JSON or HTML.",
        description="Export the topology map in a diagram or document format.",
    )
    _add_directory(export_parser)
    _add_inventory(export_parser)
    export_parser.add_argument(
        "--format",
        required=True,
        choices=("mermaid", "dot", "json", "html"),
        help="export format",
    )
    export_parser.add_argument(
        "--out", required=True, metavar="FILE", help="output file"
    )
    export_parser.set_defaults(handler=_cmd_export)

    version_parser = subparsers.add_parser(
        "version", help="Print the topomapper version."
    )
    version_parser.set_defaults(handler=_cmd_version)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the CLI and return a process exit code."""
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "command", None):
        parser.print_help()
        return EXIT_USAGE
    try:
        return int(args.handler(args))
    except NetopsError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_RUNTIME
    except KeyboardInterrupt:  # pragma: no cover - interactive only
        print("interrupted", file=sys.stderr)
        return 130
