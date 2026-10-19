"""Just enough EDID parsing to identify the monitor and read its preferred mode."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class EdidInfo:
    vendor: str
    product: int
    preferred_width: int
    preferred_height: int


def parse_edid(data: bytes) -> EdidInfo:
    if len(data) < 128 or data[:8] != b"\x00\xff\xff\xff\xff\xff\xff\x00":
        raise ValueError("not an EDID block")
    raw_vendor = (data[8] << 8) | data[9]
    vendor = "".join(chr(((raw_vendor >> shift) & 0x1F) + 64) for shift in (10, 5, 0))
    product = data[10] | (data[11] << 8)
    # The first detailed timing descriptor (bytes 54-71) is the preferred mode.
    dtd = data[54:72]
    width = dtd[2] | ((dtd[4] & 0xF0) << 4)
    height = dtd[5] | ((dtd[7] & 0xF0) << 4)
    return EdidInfo(vendor, product, width, height)
