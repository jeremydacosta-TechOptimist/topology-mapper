"""LLDP and CDP dump parsers."""

from __future__ import annotations

from ..models import Neighbor
from .cdp import parse_cdp
from .lldp import parse_lldp

__all__ = ["Neighbor", "parse_cdp", "parse_device_text", "parse_lldp"]


def parse_device_text(text: str, local_device: str) -> list[Neighbor]:
    """Parse every neighbour record in one device dump (LLDP and CDP)."""
    return parse_lldp(text, local_device) + parse_cdp(text, local_device)
