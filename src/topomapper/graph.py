"""Topology graph construction from LLDP/CDP neighbour records."""

from __future__ import annotations

import ipaddress
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .errors import NetopsError
from .models import Neighbor
from .parsers import parse_device_text

# Interface prefix normalization, ordered from the most specific to the most
# generic prefix so that ``TenGigabitEthernet`` is not matched as ``Ethernet``.
_PORT_PREFIXES: tuple[tuple[str, str], ...] = (
    ("TwentyFiveGigE", "Twe"),
    ("FortyGigabitEthernet", "Fo"),
    ("HundredGigE", "Hu"),
    ("TenGigabitEthernet", "Te"),
    ("AppGigabitEthernet", "Ap"),
    ("GigabitEthernet", "Gi"),
    ("FastEthernet", "Fa"),
    ("Port-channel", "Po"),
    ("Loopback", "Lo"),
    ("Ethernet", "Et"),
    ("Serial", "Se"),
    ("Tunnel", "Tu"),
    ("Vlan", "Vl"),
    ("Management", "Ma"),
)


def normalize_port(value: str) -> str:
    """Normalize a Cisco interface name to its usual short form.

    ``GigabitEthernet1/0/1`` becomes ``Gi1/0/1``; unknown names are returned
    with whitespace collapsed and already-short names are left untouched.
    """
    text = " ".join((value or "").strip().split())
    if not text:
        return ""
    lowered = text.casefold()
    for long_name, short_name in _PORT_PREFIXES:
        if lowered.startswith(long_name.casefold()):
            remainder = text[len(long_name) :].strip()
            return f"{short_name}{remainder}"
    return text


def normalize_device_name(value: str) -> str:
    """Return the case-insensitive identity key for a device name."""
    text = " ".join((value or "").strip().split()).rstrip(".")
    return text.casefold()


def _clean_ip(value: str | None) -> str | None:
    """Return *value* if it is a valid IP address, otherwise ``None``."""
    if not value:
        return None
    try:
        return str(ipaddress.ip_address(value.strip()))
    except ValueError:
        return None


@dataclass(frozen=True)
class Node:
    """A device in the topology graph."""

    name: str
    key: str
    role: str = "unknown"
    mgmt_ip: str | None = None
    platform: str | None = None
    declared: bool = False
    has_dump: bool = False
    mentioned_by: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-friendly representation of the node."""
        return {
            "name": self.name,
            "role": self.role,
            "mgmt_ip": self.mgmt_ip,
            "platform": self.platform,
            "declared": self.declared,
            "has_dump": self.has_dump,
            "mentioned_by": list(self.mentioned_by),
        }


@dataclass(frozen=True)
class Edge:
    """An undirected link between two devices.

    ``a_port`` and ``b_port`` are the normalized ports on each endpoint when
    they are known. ``symmetric`` means both devices reported the link.
    """

    a: str
    b: str
    a_port: str | None
    b_port: str | None
    protocols: tuple[str, ...]
    symmetric: bool
    reported_by: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-friendly representation of the edge."""
        return {
            "a": self.a,
            "b": self.b,
            "a_port": self.a_port,
            "b_port": self.b_port,
            "protocols": list(self.protocols),
            "symmetric": self.symmetric,
            "reported_by": list(self.reported_by),
        }


@dataclass(frozen=True)
class InventoryDevice:
    """A device declared in the optional inventory file."""

    name: str
    role: str = "unknown"
    mgmt_ip: str | None = None


@dataclass
class Graph:
    """A topology graph of devices and links."""

    nodes: dict[str, Node]
    edges: list[Edge]

    @property
    def device_count(self) -> int:
        """Number of nodes in the graph."""
        return len(self.nodes)

    @property
    def edge_count(self) -> int:
        """Number of links in the graph."""
        return len(self.edges)

    def node(self, name: str) -> Node:
        """Return the node matching *name*, raising ``KeyError`` when absent."""
        return self.nodes[normalize_device_name(name)]

    def adjacency(self) -> dict[str, list[str]]:
        """Return sorted neighbour keys for each node key."""
        adjacency: dict[str, set[str]] = {key: set() for key in self.nodes}
        for edge in self.edges:
            a_key = normalize_device_name(edge.a)
            b_key = normalize_device_name(edge.b)
            if a_key == b_key or a_key not in adjacency or b_key not in adjacency:
                continue
            adjacency[a_key].add(b_key)
            adjacency[b_key].add(a_key)
        return {key: sorted(neighbours) for key, neighbours in adjacency.items()}

    def degree(self, name: str) -> int:
        """Return the number of distinct neighbours of *name*."""
        key = normalize_device_name(name)
        return len(self.adjacency().get(key, ()))

    def summary(self) -> dict[str, int]:
        """Return aggregate counts used by the JSON document and statistics."""
        nodes = list(self.nodes.values())
        return {
            "devices": len(nodes),
            "dumped_devices": sum(1 for node in nodes if node.has_dump),
            "declared_devices": sum(1 for node in nodes if node.declared),
            "mention_only_devices": sum(1 for node in nodes if not node.declared),
            "edges": len(self.edges),
            "symmetric_edges": sum(1 for edge in self.edges if edge.symmetric),
            "one_sided_edges": sum(1 for edge in self.edges if not edge.symmetric),
            "lldp_edges": sum(1 for edge in self.edges if "lldp" in edge.protocols),
            "cdp_edges": sum(1 for edge in self.edges if "cdp" in edge.protocols),
        }

    def to_dict(self) -> dict[str, Any]:
        """Return the full JSON document for the graph."""
        return {
            "schema_version": 1,
            "summary": self.summary(),
            "nodes": [node.to_dict() for node in self.nodes.values()],
            "edges": [edge.to_dict() for edge in self.edges],
        }


def load_dump_files(directory: str | Path) -> list[tuple[str, str]]:
    """Read every ``*.txt`` device dump in *directory*, sorted by file name."""
    path = Path(directory)
    if not path.exists():
        raise NetopsError(f"topology directory not found: {path}")
    if not path.is_dir():
        raise NetopsError(f"not a directory: {path}")
    files = sorted(
        (file for file in path.glob("*.txt") if file.is_file()),
        key=lambda file: file.name.casefold(),
    )
    if not files:
        raise NetopsError(f"no device dumps (*.txt) found in {path}")
    dumps: list[tuple[str, str]] = []
    for file in files:
        try:
            text = file.read_text(encoding="utf-8-sig", errors="replace")
        except OSError as exc:
            raise NetopsError(f"cannot read {file}: {exc}") from exc
        dumps.append((file.stem, text))
    return dumps


def load_inventory(path: str | Path) -> dict[str, InventoryDevice]:
    """Load and validate the optional JSON device inventory."""
    inventory_path = Path(path)
    try:
        raw = json.loads(inventory_path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise NetopsError(f"cannot read inventory {inventory_path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise NetopsError(f"invalid inventory JSON in {inventory_path}: {exc}") from exc
    if not isinstance(raw, dict) or not isinstance(raw.get("devices"), list):
        raise NetopsError("inventory must be a JSON object with a 'devices' list")
    inventory: dict[str, InventoryDevice] = {}
    for index, entry in enumerate(raw["devices"], start=1):
        if not isinstance(entry, dict):
            raise NetopsError(f"inventory device #{index} must be an object")
        name = entry.get("name")
        if not isinstance(name, str) or not name.strip():
            raise NetopsError(f"inventory device #{index} has no name")
        key = normalize_device_name(name)
        if key in inventory:
            raise NetopsError(f"duplicate inventory device {name!r}")
        role = entry.get("role", "unknown")
        if not isinstance(role, str):
            raise NetopsError(f"inventory device {name!r} has a non-string role")
        mgmt_ip = entry.get("mgmt_ip")
        if mgmt_ip is not None:
            if not isinstance(mgmt_ip, str) or _clean_ip(mgmt_ip) is None:
                raise NetopsError(f"inventory device {name!r} has an invalid mgmt_ip")
            mgmt_ip = _clean_ip(mgmt_ip)
        inventory[key] = InventoryDevice(
            name=" ".join(name.strip().split()),
            role=role.strip() or "unknown",
            mgmt_ip=mgmt_ip,
        )
    return inventory


@dataclass
class _LinkDraft:
    """One local viewpoint of a link, before reciprocal merging."""

    local_key: str
    local_port: str
    remote_key: str
    remote_ports: list[str]
    protocols: set[str]


def _register(
    name: str,
    priority_level: int,
    displays: dict[str, str],
    priorities: dict[str, int],
) -> str:
    """Register a device name and keep the highest-priority display spelling."""
    key = normalize_device_name(name)
    if not key:
        return ""
    display = " ".join(name.strip().split())
    if key not in displays or priority_level < priorities[key]:
        displays[key] = display
        priorities[key] = priority_level
    return key


def _make_edge(
    first: _LinkDraft,
    second: _LinkDraft | None,
    displays: dict[str, str],
) -> Edge:
    """Build an :class:`Edge` from one or two reciprocal link drafts."""
    a_key, b_key = sorted((first.local_key, first.remote_key))
    first_remote_port = first.remote_ports[0] if first.remote_ports else None
    if first.local_key == a_key:
        a_port: str | None = first.local_port or None
        b_port: str | None = first_remote_port
    else:
        b_port = first.local_port or None
        a_port = first_remote_port
    protocols = set(first.protocols)
    reporters = {first.local_key}
    symmetric = False
    if second is not None:
        protocols |= second.protocols
        reporters.add(second.local_key)
        symmetric = True
        if second.local_key == a_key:
            a_port = second.local_port or a_port
        elif second.local_key == b_key:
            b_port = second.local_port or b_port
    return Edge(
        a=displays[a_key],
        b=displays[b_key],
        a_port=a_port,
        b_port=b_port,
        protocols=tuple(sorted(protocols)),
        symmetric=symmetric,
        reported_by=tuple(sorted(displays[key] for key in reporters)),
    )


def load_graph(directory: str | Path, inventory_path: str | Path | None = None) -> Graph:
    """Build a :class:`Graph` from the device dumps in *directory*.

    LLDP and CDP records for the same local port are merged into one edge and
    edges reported from both sides are marked symmetric. The optional
    inventory declares device roles and management addresses.
    """
    inventory = load_inventory(inventory_path) if inventory_path is not None else {}
    dumps = load_dump_files(directory)

    displays: dict[str, str] = {}
    priorities: dict[str, int] = {}
    roles: dict[str, str] = {}
    management: dict[str, str] = {}
    platforms: dict[str, str] = {}
    has_dump: set[str] = set()
    mentioned_by: dict[str, set[str]] = {}
    neighbors: list[Neighbor] = []

    for key, device in inventory.items():
        displays[key] = device.name
        priorities[key] = 0
        roles[key] = device.role
        if device.mgmt_ip:
            management[key] = device.mgmt_ip

    for local_name, text in dumps:
        local_key = _register(local_name, 1, displays, priorities)
        has_dump.add(local_key)
        for neighbor in parse_device_text(text, local_name):
            neighbors.append(neighbor)
            if not neighbor.remote_name:
                continue
            remote_key = _register(neighbor.remote_name, 2, displays, priorities)
            if not remote_key:
                continue
            mentioned_by.setdefault(remote_key, set()).add(
                " ".join(local_name.strip().split())
            )
            remote_ip = _clean_ip(neighbor.mgmt_ip)
            if remote_ip and remote_key not in management:
                management[remote_key] = remote_ip
            if neighbor.platform and remote_key not in platforms:
                platforms[remote_key] = neighbor.platform

    drafts: dict[tuple[str, str, str], _LinkDraft] = {}
    for neighbor in neighbors:
        local_key = normalize_device_name(neighbor.local_device)
        remote_key = normalize_device_name(neighbor.remote_name)
        if not local_key or not remote_key or local_key == remote_key:
            continue
        local_port = normalize_port(neighbor.local_port)
        remote_port = normalize_port(neighbor.remote_port)
        draft_key = (local_key, local_port, remote_key)
        draft = drafts.get(draft_key)
        if draft is None:
            draft = _LinkDraft(local_key, local_port, remote_key, [], set())
            drafts[draft_key] = draft
        draft.protocols.add(neighbor.protocol)
        if remote_port and remote_port not in draft.remote_ports:
            draft.remote_ports.append(remote_port)

    raw = list(drafts.values())
    used: set[int] = set()
    edges: list[Edge] = []
    for index, draft in enumerate(raw):
        if index in used:
            continue
        exact: list[int] = []
        for other_index, other in enumerate(raw):
            if other_index == index or other_index in used:
                continue
            if other.local_key != draft.remote_key or other.remote_key != draft.local_key:
                continue
            if draft.local_port and other.local_port and draft.remote_ports and other.remote_ports:
                if other.local_port in draft.remote_ports and draft.local_port in other.remote_ports:
                    exact.append(other_index)
        if len(exact) == 1:
            match = exact[0]
            used.update({index, match})
            edges.append(_make_edge(draft, raw[match], displays))

    for index, draft in enumerate(raw):
        if index in used:
            continue
        fallback: list[int] = []
        for other_index, other in enumerate(raw):
            if other_index == index or other_index in used:
                continue
            if other.local_key != draft.remote_key or other.remote_key != draft.local_key:
                continue
            well_known_ports = (
                draft.local_port
                and other.local_port
                and draft.remote_ports
                and other.remote_ports
            )
            if not well_known_ports:
                fallback.append(other_index)
        if len(fallback) == 1:
            match = fallback[0]
            used.update({index, match})
            edges.append(_make_edge(draft, raw[match], displays))
        else:
            used.add(index)
            edges.append(_make_edge(draft, None, displays))

    edges.sort(key=lambda edge: (edge.a.casefold(), edge.a_port or "", edge.b.casefold(), edge.b_port or ""))

    nodes: dict[str, Node] = {}
    for key in sorted(displays):
        nodes[key] = Node(
            name=displays[key],
            key=key,
            role=roles.get(key, "unknown"),
            mgmt_ip=management.get(key),
            platform=platforms.get(key),
            declared=key in has_dump or key in inventory,
            has_dump=key in has_dump,
            mentioned_by=tuple(sorted(mentioned_by.get(key, set()), key=str.casefold)),
        )
    return Graph(nodes=nodes, edges=edges)
