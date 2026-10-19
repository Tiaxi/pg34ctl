"""Switch the monitor between its 21:9 and 16:9 aspect modes.

The PG34WCDN has no VCP code for Aspect Control (ASUS' 0xD3 is not implemented), so
we walk the OSD with remote joystick presses. The menu path was mapped by hand on
firmware MCM102 with HDR off and the Quick Menu emptied (so "show" opens the full menu):

    Show -> Down (Image) -> Enter -> Down x4 (Aspect Control) -> Enter
    -> highlight starts on the current ratio; Down = 16:9, Up = 21:9 -> Enter
    -> scaling submenu: Down = Pixel by Pixel -> Enter

The ratio itself is not readable over DDC, but the monitor swaps its EDID: in 16:9
mode the preferred timing is 2560x1440 instead of 3440x1440. That is how we read the
current mode and verify a switch.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from enum import Enum

from .ddc import DdcBackend, DdcError
from .edid import parse_edid
from .osd import Button, press

SCALING = 0x86
HDR_SETTING = 0xE2
PIP_PBP = 0xF4


class Aspect(Enum):
    WIDE = "21:9"
    STANDARD = "16:9"


class Scaling(Enum):
    PIXEL_BY_PIXEL = 0x01
    FULL = 0x02


NATIVE_WIDTH = {3440: Aspect.WIDE, 2560: Aspect.STANDARD}


class AspectError(Exception):
    pass


def current_aspect(backend: DdcBackend) -> Aspect:
    info = parse_edid(backend.edid())
    try:
        return NATIVE_WIDTH[info.preferred_width]
    except KeyError:
        raise AspectError(
            f"unexpected preferred mode {info.preferred_width}x{info.preferred_height}"
        ) from None


def menu_sequence(target: Aspect) -> list[Button]:
    return [
        Button.CLOSE,
        Button.SHOW,
        Button.DOWN,  # Gaming -> Image
        Button.ENTER,
        *[Button.DOWN] * 4,  # -> Aspect Control
        Button.ENTER,
        Button.DOWN if target is Aspect.STANDARD else Button.UP,
        Button.ENTER,  # opens the scaling submenu for the chosen ratio
        Button.DOWN,  # -> Pixel by Pixel
        Button.ENTER,
        Button.CLOSE,
    ]


def check_preconditions(backend: DdcBackend) -> None:
    if backend.get_vcp(HDR_SETTING).current & 0xFF:
        raise AspectError(
            "HDR is on. The menu path was only mapped with HDR off; turn HDR off first."
        )
    pip = backend.get_vcp(PIP_PBP)
    if pip.maximum != 0xFE and pip.current:
        raise AspectError("PIP/PBP is on, which disables Aspect Control.")


def switch_aspect(
    backend: DdcBackend,
    target: Aspect,
    scaling: Scaling = Scaling.PIXEL_BY_PIXEL,
    *,
    timeout: float = 15.0,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
    on_step: Callable[[str], None] = lambda _msg: None,
) -> bool:
    """Switch to ``target``. Returns False if the monitor was already there."""
    if current_aspect(backend) is target:
        _apply_scaling(backend, scaling, sleep)
        return False
    check_preconditions(backend)
    on_step(f"Navigating the OSD to Aspect Control -> {target.value}")
    press(backend, menu_sequence(target), sleep=sleep)
    on_step("Waiting for the monitor to change mode")
    deadline = clock() + timeout
    while current_aspect(backend) is not target:
        if clock() > deadline:
            press(backend, [Button.CLOSE], sleep=sleep)
            raise AspectError(
                f"the monitor did not switch to {target.value}; the OSD menu path may "
                "differ (HDR on, ELMB on, Quick Menu entries, or a firmware change)"
            )
        sleep(0.5)
    # The monitor re-enumerates after a mode change. For a few seconds it is busy and
    # the desktop (e.g. KDE's libddcutil) re-probes it on the same bus, so our replies
    # can be lost or belong to someone else's request.
    sleep(3.0)
    on_step(f"Setting scaling to {scaling.name.replace('_', ' ').title()}")
    _apply_scaling(backend, scaling, sleep)
    # Linux desktops follow the new preferred mode by themselves; Windows may not.
    apply_resolution = getattr(backend, "apply_native_resolution", None)
    if apply_resolution:
        info = parse_edid(backend.edid())
        on_step(f"Setting the desktop to {info.preferred_width}x{info.preferred_height}")
        apply_resolution(info.preferred_width, info.preferred_height)
    return True


def _apply_scaling(backend: DdcBackend, scaling: Scaling, sleep: Callable[[float], None]) -> None:
    last: Exception | None = None
    for _ in range(10):
        try:
            if backend.get_vcp(SCALING).current & 0xFF == scaling.value:
                return
            backend.set_vcp(SCALING, scaling.value)
        except DdcError as exc:
            last = exc
        sleep(1.0)
    raise AspectError(f"could not set scaling to {scaling.name}: {last}")
