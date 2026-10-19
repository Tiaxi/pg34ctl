"""Platform DDC/CI backends.

A backend is one physical monitor that can read and write VCP features. Linux talks to
``/dev/i2c-*`` directly; Windows goes through the dxva2 Monitor Configuration API.
"""

from __future__ import annotations

import sys
from typing import Protocol

from .protocol import DdcError, UnsupportedFeature, VcpReading

__all__ = [
    "DdcBackend",
    "DdcError",
    "MonitorNotFound",
    "UnsupportedFeature",
    "VcpReading",
    "open_backend",
]

MODEL = "PG34WCDN"
EDID_VENDOR = "AUS"
EDID_PRODUCT = 0xAA29


class MonitorNotFound(Exception):
    pass


class DdcBackend(Protocol):
    description: str

    def get_vcp(self, code: int) -> VcpReading: ...

    def set_vcp(self, code: int, value: int) -> None: ...

    def capabilities(self) -> str: ...

    def edid(self) -> bytes:
        """The monitor's current EDID as the OS sees it (changes with aspect mode)."""
        ...

    def close(self) -> None: ...


def open_backend() -> DdcBackend:
    """Find the PG34WCDN on this machine and open a backend for it."""
    if sys.platform == "win32":
        from .windows import open_windows_backend

        return open_windows_backend()
    from .linux import open_linux_backend

    return open_linux_backend()
