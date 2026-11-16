"""Shared helpers for the offline topology-mapper test suite."""

from __future__ import annotations

import contextlib
import io
import os
import sys
import tempfile
from collections.abc import Iterator
from pathlib import Path
from typing import Any

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC_DIR = os.path.join(REPO_ROOT, "src")
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

from topomapper import cli  # noqa: E402
from topomapper.analysis import Finding, analyze  # noqa: E402
from topomapper.graph import Edge, Graph, Node, normalize_device_name  # noqa: E402

FIXTURE_DIR = os.path.join(REPO_ROOT, "examples", "lab-topology")
FIXTURE_INVENTORY = os.path.join(FIXTURE_DIR, "inventory.json")

SAMPLE_LLDP = """\
switch-a#show lldp neighbors detail
------------------------------------------------
Local Intf: GigabitEthernet1/0/1
Chassis id: 0011.2233.4455
Port id: GigabitEthernet1/0/2
Port Description: uplink to switch-b.lab.example
System Name: switch-b
System Description: Cisco IOS Software, C2960 Software, Version 15.2(7)E7
Time remaining: 98 seconds
System Capabilities: B,R
Enabled Capabilities: B,R
Management Addresses:
    IP: 192.0.2.12
Auto Negotiation - supported, enabled
------------------------------------------------
Local Intf: GigabitEthernet1/0/2
Chassis id: 0011.2233.4466
Port id: Ethernet0/1
System Name: server-1
System Description: Linux bridge
Time remaining: 110 seconds
System Capabilities: B
Enabled Capabilities: B
Management Addresses:
    IP: 192.0.2.50
"""

SAMPLE_CDP = """\
switch-a#show cdp neighbors detail
-------------------------
Device ID: switch-b
Entry address(es):
  IP address: 192.0.2.12
Platform: cisco WS-C2960-24TT-L,  Capabilities: Switch IGMP
Interface: GigabitEthernet1/0/1,  Port ID (outgoing port): GigabitEthernet1/0/2
Holdtime : 152 sec

Version :
Cisco IOS Software, C2960 Software (C2960-LANBASEK9-M), Version 15.2(7)E7

advertisement version: 2
-------------------------
Device ID: switch-c
Entry address(es):
  IP address: 192.0.2.13
Platform: cisco WS-C3560-24TS,  Capabilities: Switch IGMP
Interface: GigabitEthernet1/0/3,  Port ID (outgoing port): GigabitEthernet0/1
Holdtime : 178 sec

Version :
Cisco IOS Software, C3560 Software, Version 15.0(2)SE11
"""


def run_cli(args: list[str]) -> tuple[int, str, str]:
    """Run the CLI in-process and capture its exit code, stdout and stderr."""
    stdout = io.StringIO()
    stderr = io.StringIO()
    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        try:
            code = cli.main(args)
        except SystemExit as exc:
            code = int(exc.code) if exc.code is not None else 0
    return code, stdout.getvalue(), stderr.getvalue()


def fixture_graph() -> Graph:
    """Load the committed lab topology."""
    from topomapper.graph import load_graph

    return load_graph(FIXTURE_DIR, FIXTURE_INVENTORY)


def fixture_findings() -> list[Finding]:
    """Analyze the committed lab topology."""
    return analyze(fixture_graph())


def lldp_block(
    local_port: str,
    remote_name: str | None,
    remote_port: str | None = None,
    mgmt_ip: str | None = None,
    platform: str = "Cisco IOS Software, C2960 Software",
    capabilities: str = "B,R",
    port_description: str | None = None,
) -> str:
    """Build one LLDP detail block for synthetic dumps."""
    lines = ["------------------------------------------------", f"Local Intf: {local_port}", "Chassis id: 0011.2233.4400"]
    if remote_port:
        lines.append(f"Port id: {remote_port}")
    if port_description:
        lines.append(f"Port Description: {port_description}")
    if remote_name:
        lines.append(f"System Name: {remote_name}")
    lines.extend(
        [
            f"System Description: {platform}",
            "Time remaining: 100 seconds",
            f"System Capabilities: {capabilities}",
            f"Enabled Capabilities: {capabilities}",
        ]
    )
    if mgmt_ip:
        lines.extend(["Management Addresses:", f"    IP: {mgmt_ip}"])
    return "\n".join(lines) + "\n"


def cdp_block(
    device_id: str | None,
    local_port: str,
    remote_port: str | None = None,
    mgmt_ip: str | None = None,
    platform: str = "cisco WS-C2960-24TT-L",
    capabilities: str = "Switch IGMP",
) -> str:
    """Build one CDP detail block for synthetic dumps."""
    lines = ["-------------------------"]
    if device_id is not None:
        lines.append(f"Device ID: {device_id}")
    if mgmt_ip:
        lines.extend(["Entry address(es):", f"  IP address: {mgmt_ip}"])
    platform_line = f"Platform: {platform}"
    if capabilities:
        platform_line += f",  Capabilities: {capabilities}"
    lines.append(platform_line)
    interface_line = f"Interface: {local_port}"
    if remote_port:
        interface_line += f",  Port ID (outgoing port): {remote_port}"
    lines.append(interface_line)
    lines.extend(["Holdtime : 150 sec", "", "Version :", "Cisco IOS Software"])
    return "\n".join(lines) + "\n"


@contextlib.contextmanager
def write_topology(files: dict[str, str]) -> Iterator[str]:
    """Write dump files into a temporary directory and yield its path."""
    with tempfile.TemporaryDirectory() as temp_dir:
        for filename, content in files.items():
            Path(temp_dir, filename).write_text(content, encoding="utf-8")
        yield temp_dir


def make_graph(
    nodes: list[dict[str, Any]], edges: list[dict[str, Any]]
) -> Graph:
    """Build a synthetic graph directly from node and edge specifications."""
    node_objects: dict[str, Node] = {}
    for spec in nodes:
        name = str(spec["name"])
        key = normalize_device_name(name)
        node_objects[key] = Node(
            name=name,
            key=key,
            role=str(spec.get("role", "unknown")),
            mgmt_ip=spec.get("mgmt_ip"),
            platform=spec.get("platform"),
            declared=bool(spec.get("declared", True)),
            has_dump=bool(spec.get("has_dump", True)),
            mentioned_by=tuple(spec.get("mentioned_by", ())),
        )
    edge_objects: list[Edge] = []
    for spec in edges:
        edge_objects.append(
            Edge(
                a=str(spec["a"]),
                b=str(spec["b"]),
                a_port=spec.get("a_port"),
                b_port=spec.get("b_port"),
                protocols=tuple(spec.get("protocols", ("lldp",))),
                symmetric=bool(spec.get("symmetric", True)),
                reported_by=tuple(spec.get("reported_by", (spec["a"],))),
            )
        )
    return Graph(nodes=dict(sorted(node_objects.items())), edges=edge_objects)


def make_finding(
    finding_id: str = "TOPO-CYCLE",
    severity: str = "error",
    message: str = "Loop detected",
    nodes: tuple[str, ...] = ("sw1",),
) -> Finding:
    """Create a Finding for renderer tests."""
    return Finding(id=finding_id, severity=severity, message=message, nodes=nodes)
