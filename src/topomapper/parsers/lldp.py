"""Parser for Cisco IOS style ``show lldp neighbors detail`` dumps."""

from __future__ import annotations

from ..models import Neighbor

_BLOCK_START = "local intf:"
_SKIP_KEYS = frozenset(
    {
        "time remaining",
        "chassis id subtype",
        "port id subtype",
    }
)


def _collapse(value: str) -> str:
    """Collapse runs of whitespace into single spaces."""
    return " ".join(value.split())


def _split_key(line: str) -> tuple[str, str] | None:
    """Split a ``Key: value`` line, returning lowercase key and value."""
    if ":" not in line:
        return None
    key, _, value = line.partition(":")
    return key.strip().casefold(), value.strip()


def _first_ip(line: str) -> str | None:
    """Extract an ``IP:`` management address from a line."""
    _, _, value = line.partition(":")
    candidate = value.strip()
    return candidate or None


def _build_neighbor(fields: dict[str, str], local_device: str) -> Neighbor | None:
    """Build a :class:`Neighbor` from one LLDP block."""
    remote_name = fields.get("system name") or fields.get("chassis id") or ""
    remote_name = _collapse(remote_name)
    remote_port = _collapse(fields.get("port id", ""))
    if not remote_name and not remote_port:
        return None
    if not remote_name:
        return None
    return Neighbor(
        protocol="lldp",
        local_device=local_device,
        local_port=fields.get("local intf", ""),
        remote_name=remote_name,
        remote_port=remote_port,
        mgmt_ip=fields.get("mgmt_ip"),
        platform=fields.get("platform"),
        capabilities=fields.get("capabilities"),
        port_description=fields.get("port description"),
    )


def parse_lldp(text: str, local_device: str) -> list[Neighbor]:
    """Parse every LLDP neighbour block in *text*.

    A block starts on a ``Local Intf:`` line and continues until the next
    block; unknown lines (timers, media capabilities, counters) are ignored.
    """
    neighbors: list[Neighbor] = []
    fields: dict[str, str] | None = None
    in_management = False

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.casefold().startswith(_BLOCK_START):
            if fields is not None:
                neighbor = _build_neighbor(fields, local_device)
                if neighbor is not None:
                    neighbors.append(neighbor)
            fields = {"local intf": line.split(":", 1)[1].strip()}
            in_management = False
            continue
        if fields is None:
            continue
        if line.casefold().startswith("management addresses:"):
            in_management = True
            remainder = line.split(":", 1)[1].strip()
            if remainder.casefold().startswith("ip:") and "mgmt_ip" not in fields:
                address = _first_ip(remainder)
                if address:
                    fields["mgmt_ip"] = address
            continue
        if in_management and line.casefold().startswith("ip:") and "mgmt_ip" not in fields:
            address = _first_ip(line)
            if address:
                fields["mgmt_ip"] = address
            continue
        split = _split_key(line)
        if split is None:
            continue
        key, value = split
        if key in _SKIP_KEYS:
            continue
        if key == "port id":
            fields["port id"] = value
        elif key == "port description":
            fields["port description"] = value
        elif key == "system name":
            fields["system name"] = value
        elif key == "chassis id":
            fields["chassis id"] = value
        elif key == "system description":
            fields["platform"] = _collapse(value)
        elif key == "enabled capabilities":
            fields["capabilities"] = _collapse(value)
        elif key == "system capabilities" and "capabilities" not in fields:
            fields["capabilities"] = _collapse(value)

    if fields is not None:
        neighbor = _build_neighbor(fields, local_device)
        if neighbor is not None:
            neighbors.append(neighbor)
    return neighbors
