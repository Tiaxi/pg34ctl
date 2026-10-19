from pg34ctl.ddc import DdcError, UnsupportedFeature, VcpReading

HEADER = b"\x00\xff\xff\xff\xff\xff\xff\x00"


def make_edid(width: int, height: int = 1440) -> bytes:
    data = bytearray(128)
    data[:8] = HEADER
    data[8:10] = bytes([0x06, 0xB3])  # "AUS"
    data[10:12] = bytes([0x29, 0xAA])  # product 0xAA29
    dtd = bytearray(18)
    dtd[2] = width & 0xFF
    dtd[4] = (width >> 8) << 4
    dtd[5] = height & 0xFF
    dtd[7] = (height >> 8) << 4
    data[54:72] = dtd
    return bytes(data)


class FakeMonitor:
    """In-memory PG34WCDN: VCP registers plus an OSD that can switch aspect mode."""

    description = "fake"

    def __init__(self, registers: dict[int, tuple[int, int]] | None = None, width=3440):
        self.registers = {
            0x10: (40, 100),
            0x86: (0x01, 0x0B),
            0xE2: (0x0000, 0x0108),
            0xF4: (0x00, 0x07),
            0xFD: (0x7869, 0x787D),
            0xF2: (0x0602, 0x0606),
            0xFF: (0x30, 0x66),
            0xDC: (0x05, 0x020A),
        } | (registers or {})
        self.width = width
        self.writes: list[tuple[int, int]] = []
        self.osd_works = True
        self._presses: list[int] = []

    def get_vcp(self, code: int) -> VcpReading:
        if code not in self.registers:
            raise UnsupportedFeature(f"0x{code:02X}")
        current, maximum = self.registers[code]
        return VcpReading(code, current, maximum)

    def set_vcp(self, code: int, value: int) -> None:
        self.writes.append((code, value))
        if code == 0xEB:
            self._osd(value)
            return
        if code not in self.registers:
            raise DdcError("no such code")
        self.registers[code] = (value, self.registers[code][1])

    def _osd(self, button: int) -> None:
        if button == 0:  # Close: apply the ratio chosen by the last Up/Down before Enter
            presses, self._presses = self._presses, []
            if self.osd_works and presses[:1] == [1] and len(presses) >= 12:
                chosen = presses[8]
                self.width = 2560 if chosen == 3 else 3440
            return
        self._presses.append(button)

    def capabilities(self) -> str:
        return "(model(PG34WCDN))"

    def edid(self) -> bytes:
        return make_edid(self.width)

    def close(self) -> None:
        pass
