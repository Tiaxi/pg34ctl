"""DDC/CI on Windows through the dxva2 Monitor Configuration API.

The physical monitor handle goes stale when the PG34WCDN re-enumerates after an
aspect change, so failed calls re-discover the monitor once and retry.
"""

from __future__ import annotations

import ctypes
import time
import winreg
from ctypes import wintypes

from . import EDID_PRODUCT, EDID_VENDOR, EZ_OSD, MonitorNotFound
from .protocol import DdcError, UnsupportedFeature, VcpReading

user32 = ctypes.WinDLL("user32", use_last_error=True)
dxva2 = ctypes.WinDLL("dxva2", use_last_error=True)

ERROR_GRAPHICS_DDCCI_VCP_NOT_SUPPORTED = 0xC0262584
EDD_GET_DEVICE_INTERFACE_NAME = 0x00000001
ENUM_CURRENT_SETTINGS = -1
DM_PELSWIDTH = 0x00080000
DM_PELSHEIGHT = 0x00100000
DM_DISPLAYFREQUENCY = 0x00400000
CDS_UPDATEREGISTRY = 0x00000001
DISP_CHANGE_SUCCESSFUL = 0
HARDWARE_ID = f"{EDID_VENDOR}{EDID_PRODUCT:04X}"  # "AUSAA29"


class PHYSICAL_MONITOR(ctypes.Structure):
    _fields_ = [
        ("hPhysicalMonitor", wintypes.HANDLE),
        ("szPhysicalMonitorDescription", wintypes.WCHAR * 128),
    ]


class MONITORINFOEXW(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("rcMonitor", wintypes.RECT),
        ("rcWork", wintypes.RECT),
        ("dwFlags", wintypes.DWORD),
        ("szDevice", wintypes.WCHAR * 32),
    ]


class DISPLAY_DEVICEW(ctypes.Structure):
    _fields_ = [
        ("cb", wintypes.DWORD),
        ("DeviceName", wintypes.WCHAR * 32),
        ("DeviceString", wintypes.WCHAR * 128),
        ("StateFlags", wintypes.DWORD),
        ("DeviceID", wintypes.WCHAR * 128),
        ("DeviceKey", wintypes.WCHAR * 128),
    ]


class DEVMODEW(ctypes.Structure):
    # The display variant of DEVMODEW (the printer union members are unused).
    _fields_ = [
        ("dmDeviceName", wintypes.WCHAR * 32),
        ("dmSpecVersion", wintypes.WORD),
        ("dmDriverVersion", wintypes.WORD),
        ("dmSize", wintypes.WORD),
        ("dmDriverExtra", wintypes.WORD),
        ("dmFields", wintypes.DWORD),
        ("dmPositionX", wintypes.LONG),
        ("dmPositionY", wintypes.LONG),
        ("dmDisplayOrientation", wintypes.DWORD),
        ("dmDisplayFixedOutput", wintypes.DWORD),
        ("dmColor", ctypes.c_short),
        ("dmDuplex", ctypes.c_short),
        ("dmYResolution", ctypes.c_short),
        ("dmTTOption", ctypes.c_short),
        ("dmCollate", ctypes.c_short),
        ("dmFormName", wintypes.WCHAR * 32),
        ("dmLogPixels", wintypes.WORD),
        ("dmBitsPerPel", wintypes.DWORD),
        ("dmPelsWidth", wintypes.DWORD),
        ("dmPelsHeight", wintypes.DWORD),
        ("dmDisplayFlags", wintypes.DWORD),
        ("dmDisplayFrequency", wintypes.DWORD),
        ("dmICMMethod", wintypes.DWORD),
        ("dmICMIntent", wintypes.DWORD),
        ("dmMediaType", wintypes.DWORD),
        ("dmDitherType", wintypes.DWORD),
        ("dmReserved1", wintypes.DWORD),
        ("dmReserved2", wintypes.DWORD),
        ("dmPanningWidth", wintypes.DWORD),
        ("dmPanningHeight", wintypes.DWORD),
    ]


MONITORENUMPROC = ctypes.WINFUNCTYPE(
    wintypes.BOOL, wintypes.HMONITOR, wintypes.HDC, ctypes.POINTER(wintypes.RECT), wintypes.LPARAM
)

user32.EnumDisplayMonitors.argtypes = [
    wintypes.HDC,
    ctypes.POINTER(wintypes.RECT),
    MONITORENUMPROC,
    wintypes.LPARAM,
]
user32.GetMonitorInfoW.argtypes = [wintypes.HMONITOR, ctypes.POINTER(MONITORINFOEXW)]
user32.EnumDisplayDevicesW.argtypes = [
    wintypes.LPCWSTR,
    wintypes.DWORD,
    ctypes.POINTER(DISPLAY_DEVICEW),
    wintypes.DWORD,
]
user32.EnumDisplaySettingsW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, ctypes.POINTER(DEVMODEW)]
user32.ChangeDisplaySettingsExW.argtypes = [
    wintypes.LPCWSTR,
    ctypes.POINTER(DEVMODEW),
    wintypes.HWND,
    wintypes.DWORD,
    wintypes.LPVOID,
]
user32.ChangeDisplaySettingsExW.restype = wintypes.LONG
dxva2.GetNumberOfPhysicalMonitorsFromHMONITOR.argtypes = [
    wintypes.HMONITOR,
    ctypes.POINTER(wintypes.DWORD),
]
dxva2.GetPhysicalMonitorsFromHMONITOR.argtypes = [
    wintypes.HMONITOR,
    wintypes.DWORD,
    ctypes.POINTER(PHYSICAL_MONITOR),
]
dxva2.DestroyPhysicalMonitor.argtypes = [wintypes.HANDLE]
dxva2.GetVCPFeatureAndVCPFeatureReply.argtypes = [
    wintypes.HANDLE,
    wintypes.BYTE,
    ctypes.POINTER(wintypes.DWORD),
    ctypes.POINTER(wintypes.DWORD),
    ctypes.POINTER(wintypes.DWORD),
]
dxva2.SetVCPFeature.argtypes = [wintypes.HANDLE, wintypes.BYTE, wintypes.DWORD]
dxva2.GetCapabilitiesStringLength.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
dxva2.CapabilitiesRequestAndCapabilitiesReply.argtypes = [
    wintypes.HANDLE,
    ctypes.c_char_p,
    wintypes.DWORD,
]


def _gdi_monitors() -> list[tuple[int, str]]:
    """(HMONITOR, GDI device name like \\\\.\\DISPLAY1) for every desktop monitor."""
    found: list[tuple[int, str]] = []

    def callback(hmonitor, _hdc, _rect, _data):
        info = MONITORINFOEXW()
        info.cbSize = ctypes.sizeof(info)
        if user32.GetMonitorInfoW(hmonitor, ctypes.byref(info)):
            found.append((hmonitor, info.szDevice))
        return True

    user32.EnumDisplayMonitors(None, None, MONITORENUMPROC(callback), 0)
    return found


def _device_instance(gdi_device: str) -> str | None:
    """Registry instance path (DISPLAY\\AUSAA29\\...) of the monitor on ``gdi_device``."""
    index = 0
    while True:
        device = DISPLAY_DEVICEW()
        device.cb = ctypes.sizeof(device)
        if not user32.EnumDisplayDevicesW(
            gdi_device, index, ctypes.byref(device), EDD_GET_DEVICE_INTERFACE_NAME
        ):
            return None
        # e.g. \\?\DISPLAY#AUSAA29#5&1a2b3c&0&UID4352#{e6f07b5f-ee97-4a90-b076-33f57bf4eaa7}
        parts = device.DeviceID.split("#")
        if len(parts) >= 3 and parts[1].upper() == HARDWARE_ID:
            return f"DISPLAY\\{parts[1]}\\{parts[2]}"
        index += 1


def _find() -> tuple[int, str, str]:
    for hmonitor, gdi_device in _gdi_monitors():
        instance = _device_instance(gdi_device)
        if instance:
            return hmonitor, gdi_device, instance
    raise MonitorNotFound("no PG34WCDN (AUSAA29) attached to the Windows desktop")


def _physical_handle(hmonitor: int) -> wintypes.HANDLE:
    count = wintypes.DWORD()
    if not dxva2.GetNumberOfPhysicalMonitorsFromHMONITOR(hmonitor, ctypes.byref(count)):
        raise ctypes.WinError(ctypes.get_last_error())
    monitors = (PHYSICAL_MONITOR * count.value)()
    if not dxva2.GetPhysicalMonitorsFromHMONITOR(hmonitor, count, monitors):
        raise ctypes.WinError(ctypes.get_last_error())
    for extra in monitors[1:]:
        dxva2.DestroyPhysicalMonitor(extra.hPhysicalMonitor)
    return monitors[0].hPhysicalMonitor


def _describe(error: int) -> str:
    # FormatError takes a signed C int, and the DDC/CI errors are 0xC026xxxx.
    return f"{ctypes.FormatError(ctypes.c_int32(error).value)} (0x{error:08X})"


class WindowsDdc:
    def __init__(self) -> None:
        self._handle = None
        self._open()

    def _open(self) -> None:
        # Open the new handle before releasing the old one, so a failed re-discovery
        # (the monitor is mid re-enumeration) never leaves us holding a dead handle.
        hmonitor, gdi_device, instance = _find()
        try:
            handle = _physical_handle(hmonitor)
        except OSError as exc:
            raise DdcError(f"cannot open the physical monitor: {exc}") from exc
        if self._handle:
            dxva2.DestroyPhysicalMonitor(self._handle)
        self._handle, self.gdi_device, self.instance = handle, gdi_device, instance
        self.description = f"{gdi_device} ({instance})"

    def _call(self, func, *args, attempts: int = 4):
        error = 0
        for attempt in range(attempts):
            if func(self._handle, *args):
                return
            error = ctypes.get_last_error() & 0xFFFFFFFF
            if error == ERROR_GRAPHICS_DDCCI_VCP_NOT_SUPPORTED:
                raise UnsupportedFeature(f"{func.__name__}{args[:1]} is not supported")
            if attempt + 1 == attempts:
                break
            time.sleep(0.1 * (attempt + 1))
            if attempt == 1:
                try:
                    self._open()
                except (MonitorNotFound, DdcError):
                    pass
        raise DdcError(f"{func.__name__} failed: {_describe(error)}")

    def get_vcp(self, code: int) -> VcpReading:
        kind, current, maximum = wintypes.DWORD(), wintypes.DWORD(), wintypes.DWORD()
        self._call(
            dxva2.GetVCPFeatureAndVCPFeatureReply,
            code,
            ctypes.byref(kind),
            ctypes.byref(current),
            ctypes.byref(maximum),
        )
        return VcpReading(code, current.value, maximum.value, continuous=kind.value == 1)

    def set_vcp(self, code: int, value: int) -> None:
        # A remote OSD press that reports failure may still have reached the monitor;
        # repeating it would move the menu cursor twice.
        self._call(dxva2.SetVCPFeature, code, value, attempts=1 if code == EZ_OSD else 4)

    def capabilities(self) -> str:
        length = wintypes.DWORD()
        self._call(dxva2.GetCapabilitiesStringLength, ctypes.byref(length))
        buffer = ctypes.create_string_buffer(length.value)
        self._call(dxva2.CapabilitiesRequestAndCapabilitiesReply, buffer, length)
        return buffer.value.decode("ascii", errors="replace")

    def edid(self) -> bytes:
        # Re-find the monitor each time: the instance can change when it re-enumerates.
        try:
            _, self.gdi_device, self.instance = _find()
        except MonitorNotFound:
            pass
        key = f"SYSTEM\\CurrentControlSet\\Enum\\{self.instance}\\Device Parameters"
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key) as handle:
            data, _ = winreg.QueryValueEx(handle, "EDID")
        return bytes(data)

    def apply_native_resolution(self, width: int, height: int) -> None:
        """Put the desktop on ``width``x``height`` at the highest refresh rate offered.

        With GPU scaling on, Windows keeps a scaled 2560x1440 after going back to 21:9,
        so set the resolution explicitly after an aspect switch.
        """
        best = None
        index = 0
        while True:
            mode = DEVMODEW()
            mode.dmSize = ctypes.sizeof(mode)
            if not user32.EnumDisplaySettingsW(self.gdi_device, index, ctypes.byref(mode)):
                break
            if (mode.dmPelsWidth, mode.dmPelsHeight) == (width, height) and (
                best is None or mode.dmDisplayFrequency > best.dmDisplayFrequency
            ):
                best = mode
            index += 1
        if best is None:
            raise DdcError(f"Windows offers no {width}x{height} mode for {self.gdi_device}")
        best.dmFields = DM_PELSWIDTH | DM_PELSHEIGHT | DM_DISPLAYFREQUENCY
        result = user32.ChangeDisplaySettingsExW(
            self.gdi_device, ctypes.byref(best), None, CDS_UPDATEREGISTRY, None
        )
        if result != DISP_CHANGE_SUCCESSFUL:
            raise DdcError(f"ChangeDisplaySettingsEx failed with {result}")

    def close(self) -> None:
        if self._handle:
            dxva2.DestroyPhysicalMonitor(self._handle)
            self._handle = None


def open_windows_backend() -> WindowsDdc:
    try:
        return WindowsDdc()
    except OSError as exc:
        raise MonitorNotFound(f"cannot open the PG34WCDN: {exc}") from exc
