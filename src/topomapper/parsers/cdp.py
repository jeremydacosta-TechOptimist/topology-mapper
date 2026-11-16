"""Parser for Cisco IOS style ``show cdp neighbors detail`` dumps."""

from __future__ import annotations

import re

from ..models import Neighbor

_BLOCK_START = "device id:"
_INTERFACE_PATTERN = re.compile(
    r"^interface:\s*(?P<local>[^,]+?)\s*,\s*port id \(outgoing port\):\s*(?P<remote>.+)$",
    re.IGNORECASE,
)
_PLATFORM_PATTERN = re.compile(
    r"^platform:\s*(?P<platform>[^,]+?)\s*(?:,\s*capabilities:\s*(?P<capabilities>.*))?$",
    re.IGNORECASE,
)


def _collapse(value: str) -> str:
    """Collapse runs of whitespace into single spaces."""
    return " ".join(value.split())


def _build_neighbor(fields: dict[str, str], local_device: str) -> Neighbor | None:
    """Build a :class:`Neighbor` from one CDP block."""
    remote_name = _collapse(fields.get("device id", ""))
    if not remote_name:
        return None
    return Neighbor(
        protocol="cdp",
        local_device=local_device,
        local_port=fields.get("interface", ""),
        remote_name=remote_name,
        remote_port=fields.get("port id", ""),
        mgmt_ip=fields.get("mgmt_ip"),
        platform=fields.get("platform"),
        capabilities=fields.get("capabilities"),
    )


def parse_cdp(text: str, local_device: str) -> list[Neighbor]:
    """Parse every CDP neighbour block in *text*.

    A block starts on a ``Device ID:`` line and continues until the next block;
    the multi-line ``Version`` section is ignored.
    """
    neighbors: list[Neighbor] = []
    fields: dict[str, str] | None = None
    in_addresses = False

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.casefold().startswith(_BLOCK_START):
            if fields is not None:
                neighbor = _build_neighbor(fields, local_device)
                if neighbor is not None:
                    neighbors.append(neighbor)
            fields = {"device id": line.split(":", 1)[1].strip()}
            in_addresses = False
            continue
        if fields is None:
            continue
        lowered = line.casefold()
        if lowered.startswith("entry address(es):"):
            in_addresses = True
            remainder = line.split(":", 1)[1].strip()
            if remainder.casefold().startswith("ip address:") and "mgmt_ip" not in fields:
                fields["mgmt_ip"] = remainder.split(":", 1)[1].strip()
            continue
        if in_addresses and lowered.startswith("ip address:") and "mgmt_ip" not in fields:
            fields["mgmt_ip"] = line.split(":", 1)[1].strip()
            continue
        if lowered.startswith("platform:"):
            match = _PLATFORM_PATTERN.match(line)
            if match:
                fields["platform"] = _collapse(match.group("platform"))
                if match.group("capabilities"):
                    fields["capabilities"] = _collapse(match.group("capabilities"))
            continue
        if lowered.startswith("capabilities:") and "capabilities" not in fields:
            fields["capabilities"] = _collapse(line.split(":", 1)[1])
            continue
        if lowered.startswith("interface:"):
            match = _INTERFACE_PATTERN.match(line)
            if match:
                fields["interface"] = match.group("local").strip()
                fields["port id"] = match.group("remote").strip()
            else:
                fields["interface"] = line.split(":", 1)[1].strip()
            continue
        if lowered.startswith("port id (outgoing port):"):
            fields["port id"] = line.split(":", 1)[1].strip()
            continue

    if fields is not None:
        neighbor = _build_neighbor(fields, local_device)
        if neighbor is not None:
            neighbors.append(neighbor)
    return neighbors
