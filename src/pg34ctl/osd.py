"""Remote control of the monitor's own OSD menu ("EzOSD", VCP 0xEB).

These are the same virtual joystick presses DisplayWidget Center sends. They let us
reach settings that have no VCP code of their own, such as Aspect Control.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Iterable
from enum import IntEnum

from .ddc import DdcBackend, DdcError

EZ_OSD = 0xEB


class Button(IntEnum):
    CLOSE = 0
    SHOW = 1
    UP = 2
    DOWN = 3
    RIGHT = 4
    LEFT = 5
    ENTER = 6
    BACK = 7


def press(
    backend: DdcBackend,
    buttons: Iterable[Button],
    delay: float = 0.4,
    sleep: Callable[[float], None] = time.sleep,
) -> None:
    for button in buttons:
        try:
            backend.set_vcp(EZ_OSD, int(button))
        except DdcError:
            # Close is sent defensively and the monitor NAKs it when no menu is open.
            if button is not Button.CLOSE:
                raise
        sleep(delay)
