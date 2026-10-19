"""DDC/CI over Linux ``/dev/i2c-*`` (requires the ``i2c-dev`` module)."""

from __future__ import annotations

import fcntl
import os
import time
from pathlib import Path

from ..edid import parse_edid
from . import EDID_PRODUCT, EDID_VENDOR, EZ_OSD, MonitorNotFound
from . import protocol as p

I2C_SLAVE = 0x0703
DRM_ROOT = Path("/sys/class/drm")

# Timings follow ddcutil's defaults; the PG34WCDN is happy with them over DP AUX.
WRITE_READ_DELAY = 0.05
SET_DELAY = 0.06
RETRIES = 4


class LinuxDdc:
    def __init__(self, bus: int, connector: Path) -> None:
        self.bus = bus
        self.connector = connector
        self.description = f"{connector.name} (/dev/i2c-{bus})"
        self._fd = os.open(f"/dev/i2c-{bus}", os.O_RDWR)
        fcntl.ioctl(self._fd, I2C_SLAVE, p.DDC_ADDR)

    def _transact(self, request: bytes, reply_len: int) -> bytes:
        os.write(self._fd, request)
        time.sleep(WRITE_READ_DELAY)
        return os.read(self._fd, reply_len)

    def get_vcp(self, code: int) -> p.VcpReading:
        last: Exception | None = None
        for attempt in range(RETRIES):
            try:
                raw = self._transact(p.get_vcp_request(code), p.GET_VCP_REPLY_LEN)
                return p.parse_get_vcp_reply(raw, code)
            except p.UnsupportedFeature:
                raise
            except (p.DdcError, OSError) as exc:
                last = exc
                time.sleep(0.05 * (attempt + 1))
        raise p.DdcError(f"reading VCP 0x{code:02X} failed: {last}")

    def set_vcp(self, code: int, value: int) -> None:
        last: OSError | None = None
        # Never repeat a remote OSD press: it may have landed even if the write errored.
        for attempt in range(1 if code == EZ_OSD else RETRIES):
            try:
                os.write(self._fd, p.set_vcp_request(code, value))
                time.sleep(SET_DELAY)
                return
            except OSError as exc:
                last = exc
                time.sleep(0.05 * (attempt + 1))
        raise p.DdcError(f"writing VCP 0x{code:02X} failed: {last}")

    def capabilities(self) -> str:
        data = bytearray()
        offset = 0
        failures = 0
        while True:
            try:
                raw = self._transact(
                    p.capabilities_request(offset), p.CAPABILITIES_FRAGMENT_MAX + 6
                )
                fragment = p.parse_capabilities_reply(raw, offset)
            except (p.DdcError, OSError):
                failures += 1
                if failures > 10:
                    raise
                time.sleep(0.1)
                continue
            if not fragment:
                break
            data += fragment
            offset += len(fragment)
        return data.rstrip(b"\x00").decode("ascii", errors="replace")

    def edid(self) -> bytes:
        return (self.connector / "edid").read_bytes()

    def close(self) -> None:
        os.close(self._fd)


def _candidate_buses(connector: Path) -> list[int]:
    # DisplayPort connectors expose their AUX channel as an i2c-N child; that is the
    # bus that carries DDC/CI. The "ddc" symlink is a fallback for HDMI.
    buses = sorted(int(d.name[4:]) for d in connector.glob("i2c-*") if d.name[4:].isdigit())
    ddc = connector / "ddc"
    if ddc.exists():
        name = ddc.resolve().name
        if name.startswith("i2c-") and name[4:].isdigit():
            buses.append(int(name[4:]))
    return buses


def find_connectors() -> list[Path]:
    """Connected DRM connectors whose EDID belongs to a PG34WCDN."""
    found = []
    for connector in sorted(DRM_ROOT.glob("card*-*")):
        try:
            if (connector / "status").read_text().strip() != "connected":
                continue
            info = parse_edid((connector / "edid").read_bytes())
        except (OSError, ValueError):
            continue
        if info.vendor == EDID_VENDOR and info.product == EDID_PRODUCT:
            found.append(connector)
    return found


def open_linux_backend() -> LinuxDdc:
    connectors = find_connectors()
    if not connectors:
        raise MonitorNotFound("no connected PG34WCDN found under /sys/class/drm")
    errors = []
    for connector in connectors:
        for bus in _candidate_buses(connector):
            try:
                backend = LinuxDdc(bus, connector)
            except OSError as exc:
                errors.append(f"/dev/i2c-{bus}: {exc}")
                continue
            try:
                backend.get_vcp(0xDF)  # VCP version: cheap proof that DDC/CI answers
                return backend
            except p.DdcError as exc:
                errors.append(f"/dev/i2c-{bus}: {exc}")
                backend.close()
    hint = "; ".join(errors) or "no I2C bus exposed for the connector"
    raise MonitorNotFound(
        f"PG34WCDN found but DDC/CI did not answer ({hint}). Is the i2c-dev module "
        "loaded, /dev/i2c-* accessible, and DDC/CI enabled in the monitor's OSD?"
    )
