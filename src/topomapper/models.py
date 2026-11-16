"""Data models shared by the parsers, graph builder and exporters."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Neighbor:
    """One neighbour record extracted from an LLDP or CDP dump."""

    protocol: str
    local_device: str
    local_port: str
    remote_name: str
    remote_port: str
    mgmt_ip: str | None = None
    platform: str | None = None
    capabilities: str | None = None
    port_description: str | None = None

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-friendly representation of the record."""
        return {
            "protocol": self.protocol,
            "local_device": self.local_device,
            "local_port": self.local_port,
            "remote_name": self.remote_name,
            "remote_port": self.remote_port,
            "mgmt_ip": self.mgmt_ip,
            "platform": self.platform,
            "capabilities": self.capabilities,
            "port_description": self.port_description,
        }
