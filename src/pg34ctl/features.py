"""The PG34WCDN's DDC/CI feature map.

Opcodes come from ASUS DisplayWidget Center's ``VCPAPI`` (decompiled) and from live
diffs taken on a PG34WCDN running firmware MCM101/MCM102. ``verified`` marks features
whose code and value meaning were confirmed on this exact monitor; the rest follow
DisplayWidget Center's tables and are very likely right but unconfirmed.

ASUS packs several settings into one 16-bit VCP word (e.g. the 0xFD toggle register),
so a feature addresses ``mask`` bits of its code's current value.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

LOCKED_MAX = 0xFE  # ASUS reports this as the maximum when a feature is greyed out


class Kind(Enum):
    RANGE = "range"
    CHOICE = "choice"
    TOGGLE = "toggle"


class Tab(Enum):
    GAMING = "Gaming"
    IMAGE = "Image"
    COLOR = "Color"
    OLED = "OLED Care"
    SYSTEM = "System"


@dataclass(frozen=True)
class Feature:
    key: str
    label: str
    code: int
    kind: Kind
    tab: Tab
    choices: dict[int, str] = field(default_factory=dict)
    mask: int = 0xFFFF
    verified: bool = False
    note: str = ""
    confirm: str = ""  # non-empty: ask before writing, with this warning
    zero_clears_word: bool = False  # writing 0 must clear the whole shared word
    # (mask, value) to fill in when writing a non-zero value finds those bits empty
    fill_if_empty: tuple[int, int] | None = None

    @property
    def shift(self) -> int:
        return (self.mask & -self.mask).bit_length() - 1

    def decode(self, word: int) -> int:
        return (word & self.mask) >> self.shift

    def encode(self, word: int, value: int) -> int:
        """Merge ``value`` into the current ``word`` of a shared register."""
        if self.kind is Kind.TOGGLE:
            value = 1 if value else 0
        if value == 0 and self.zero_clears_word:
            return 0
        word = (word & ~self.mask & 0xFFFF) | ((value << self.shift) & self.mask)
        if value and self.fill_if_empty and not word & self.fill_if_empty[0]:
            word |= self.fill_if_empty[1]
        return word

    def label_for(self, value: int) -> str:
        if self.kind is Kind.TOGGLE:
            return "On" if value else "Off"
        if self.kind is Kind.CHOICE:
            return self.choices.get(value, f"0x{value:02X}")
        return str(value)


def _toggle(key: str, label: str, bit: int, tab: Tab, **kw) -> Feature:
    return Feature(key, label, 0xFD, Kind.TOGGLE, tab, mask=bit, **kw)


def _levels(off: str, count: int, last: str | None = None) -> dict[int, str]:
    levels = {0: off} | {i: f"Level {i}" for i in range(1, count + 1)}
    if last:
        levels[count] = last
    return levels


GAMEVISUAL = {
    0x01: "Cinema",
    0x02: "Scenery",
    0x04: "User",
    0x05: "Racing",
    0x06: "RTS/RPG",
    0x07: "FPS",
    0x08: "MOBA",
    0x09: "Night Vision",
    0x0A: "sRGB Cal",
}

HDR_MODES = {
    0x0101: "Cinema HDR",
    0x0102: "Gaming HDR",
    0x0103: "Console HDR",
    0x0108: "DisplayHDR 500 True Black",
}

FEATURES: list[Feature] = [
    # Gaming
    _toggle("vrr", "Variable Refresh Rate", 0x0001, Tab.GAMING),
    Feature("gamevisual", "GameVisual", 0xDC, Kind.CHOICE, Tab.GAMING, GAMEVISUAL, verified=True),
    Feature(
        "shadow_boost",
        "Shadow Boost",
        0xE5,
        Kind.CHOICE,
        Tab.GAMING,
        _levels("Off", 4, "Dynamic Shadow Boost"),
    ),
    Feature(
        "crosshair",
        "Crosshair",
        0xE3,
        Kind.CHOICE,
        Tab.GAMING,
        {
            0x00: "Off",
            0x07: "Light blue dot",
            0x08: "Green dot",
            0x09: "Small light blue crosshair",
            0x0A: "Small green crosshair",
            0x0B: "Big blue crosshair",
            0x0C: "Big green crosshair",
            0x0D: "Dynamic dot",
            0x0E: "Dynamic small crosshair",
            0x0F: "Dynamic big crosshair",
        },
    ),
    Feature(
        "timer",
        "Timer",
        0xE4,
        Kind.CHOICE,
        Tab.GAMING,
        {0: "Off", 1: "30 min", 2: "40 min", 3: "50 min", 4: "60 min", 5: "90 min"},
    ),
    Feature(
        "fps_counter",
        "FPS Counter",
        0xEA,
        Kind.CHOICE,
        Tab.GAMING,
        {0: "Off", 1: "Number", 2: "Bar graph"},
    ),
    # Image
    Feature("brightness", "Brightness", 0x10, Kind.RANGE, Tab.IMAGE, verified=True),
    _toggle("uniform_brightness", "Uniform Brightness", 0x0040, Tab.IMAGE, verified=True),
    Feature("contrast", "Contrast", 0x12, Kind.RANGE, Tab.IMAGE, verified=True),
    Feature("sharpness", "VividPixel", 0x87, Kind.RANGE, Tab.IMAGE),
    Feature(
        "hdr_mode",
        "HDR Setting",
        0xE2,
        Kind.CHOICE,
        Tab.IMAGE,
        HDR_MODES,
        verified=True,
        note="Only available while the PC sends an HDR signal.",
    ),
    Feature(
        "adjustable_hdr",
        "Adjustable HDR",
        0x5F,
        Kind.TOGGLE,
        Tab.IMAGE,
        verified=True,
        note="Only changeable while HDR is active.",
    ),
    Feature(
        "scaling",
        "Aspect scaling",
        0x86,
        Kind.CHOICE,
        Tab.IMAGE,
        {0x01: "Pixel by Pixel", 0x02: "Full"},
        verified=True,
    ),
    Feature(
        "blue_light",
        "Blue Light Filter",
        0xE6,
        Kind.CHOICE,
        Tab.IMAGE,
        _levels("Off", 4),
    ),
    # Color
    Feature(
        "color_temp",
        "Color Temp.",
        0x14,
        Kind.CHOICE,
        Tab.COLOR,
        {
            0x03: "4000K",
            0x04: "5000K",
            0x05: "6500K",
            0x06: "7500K",
            0x07: "8200K",
            0x08: "9300K",
            0x09: "10000K",
            0x0B: "User",
        },
        verified=True,
    ),
    Feature("red_gain", "Red", 0x16, Kind.RANGE, Tab.COLOR, verified=True, note="User mode"),
    Feature("green_gain", "Green", 0x18, Kind.RANGE, Tab.COLOR, verified=True, note="User mode"),
    Feature("blue_gain", "Blue", 0x1A, Kind.RANGE, Tab.COLOR, verified=True, note="User mode"),
    Feature(
        "gamma",
        "Gamma",
        0x72,
        Kind.CHOICE,
        Tab.COLOR,
        {0x5000: "1.8", 0x6400: "2.0", 0x7800: "2.2", 0x8C00: "2.4", 0xA000: "2.6"},
        verified=True,
    ),
    Feature("saturation", "Saturation", 0x8A, Kind.RANGE, Tab.COLOR),
    Feature("sat_red", "Six-axis: Red", 0x59, Kind.RANGE, Tab.COLOR),
    Feature("sat_yellow", "Six-axis: Yellow", 0x5A, Kind.RANGE, Tab.COLOR),
    Feature("sat_green", "Six-axis: Green", 0x5B, Kind.RANGE, Tab.COLOR),
    Feature("sat_cyan", "Six-axis: Cyan", 0x5C, Kind.RANGE, Tab.COLOR),
    Feature("sat_blue", "Six-axis: Blue", 0x5D, Kind.RANGE, Tab.COLOR),
    Feature("sat_magenta", "Six-axis: Magenta", 0x5E, Kind.RANGE, Tab.COLOR),
    # OLED care. Toggle names follow DisplayWidget Center's internal names.
    Feature(
        "screen_move",
        "Screen Move",
        0xF9,
        Kind.CHOICE,
        Tab.OLED,
        {0: "Off", 1: "Light", 2: "Middle", 3: "Strong"},
    ),
    Feature(
        "pixel_cleaning_reminder",
        "Pixel Cleaning Reminder",
        0xF8,
        Kind.CHOICE,
        Tab.OLED,
        {0: "Off", 2: "2 hours", 4: "4 hours", 8: "8 hours"},
        verified=True,
    ),
    _toggle("screen_dimming", "Screen Dimming (Display Saver)", 0x0008, Tab.OLED),
    _toggle("logo_detection", "Logo Detection", 0x0020, Tab.OLED),
    _toggle("taskbar_detection", "Taskbar Detection", 0x0800, Tab.OLED),
    _toggle("boundary_detection", "Boundary Detection", 0x1000, Tab.OLED),
    _toggle("outer_dimming", "Outer Dimming Control", 0x2000, Tab.OLED),
    _toggle("global_dimming", "Global Dimming Control", 0x4000, Tab.OLED),
    # System
    Feature(
        "power_setting",
        "Power Setting",
        0xE1,
        Kind.CHOICE,
        Tab.SYSTEM,
        {0: "Performance Mode", 1: "Power Saving Mode"},
        verified=True,
        note="Power Saving Mode greys out VRR, GamePlus, Shadow Boost and more.",
    ),
    Feature(
        "input",
        "Input Select",
        0x60,
        Kind.CHOICE,
        Tab.SYSTEM,
        {0x0F: "DisplayPort", 0x11: "HDMI-1", 0x12: "HDMI-2", 0x1A: "USB-C"},
        confirm="Switching input makes this PC's picture go away.",
    ),
    Feature(
        "dp_stream",
        "DisplayPort Stream",
        0x61,
        Kind.CHOICE,
        Tab.SYSTEM,
        {0x01: "DisplayPort 1.2", 0x02: "DisplayPort 1.4", 0x03: "DisplayPort 2.1"},
        confirm="Changing the DisplayPort stream restarts the monitor.",
    ),
    Feature("volume", "Volume", 0x62, Kind.RANGE, Tab.SYSTEM),
    Feature("mute", "Mute", 0x8D, Kind.CHOICE, Tab.SYSTEM, {0x01: "Muted", 0x02: "Unmuted"}),
    Feature(
        "aura_effect",
        "Lighting Effect",
        0xF2,
        Kind.CHOICE,
        Tab.SYSTEM,
        {
            0x00: "Off",
            0x02: "Rainbow",
            0x03: "Color Cycle",
            0x04: "Static",
            0x05: "Breathing",
            0x06: "Strobing",
        },
        mask=0x00FF,
        zero_clears_word=True,  # the monitor rejects "off" with a stale colour byte
        fill_if_empty=(0xFF00, 0x0100),  # after "off" the colour byte is 0; pick Red
    ),
    Feature(
        "aura_color",
        "Lighting Color",
        0xF2,
        Kind.CHOICE,
        Tab.SYSTEM,
        {1: "Red", 2: "Green", 3: "Blue", 4: "Cyan", 5: "Magenta", 6: "Yellow"},
        mask=0xFF00,
        note="Static, Breathing and Strobing only.",
    ),
]

BY_KEY = {f.key: f for f in FEATURES}

# Writing one of these can change other settings, so re-read everything afterwards.
MODE_CHANGING = {0xDC, 0xE1, 0xE2, 0x5F, 0x14, 0xFD, 0xE6, 0x60, 0x61, 0x86}

# Read-only information.
FIRMWARE = 0xFF  # maximum byte = firmware number, e.g. 0x66 -> MCM102
USAGE_HOURS = 0xC0
PIXEL_CLEANING_BIT = 0x0010  # 0xFD bit that starts a pixel cleaning run (~6-8 min)


def firmware_name(maximum: int) -> str:
    number = maximum & 0xFF
    return f"MCE{number}" if number <= 100 else f"MCM{number}"


def is_locked(maximum: int) -> bool:
    return maximum == LOCKED_MAX
