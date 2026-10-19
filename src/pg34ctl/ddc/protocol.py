"""DDC/CI packet encoding and decoding (VESA DDC/CI 1.1, MCCS 2.2).

Only the pieces needed over a raw I2C transport live here; Windows' dxva2 API does
this framing itself. Everything is pure so it can be tested without hardware.
"""

from __future__ import annotations

from dataclasses import dataclass

DDC_ADDR = 0x37  # 7-bit I2C address of the monitor's DDC/CI endpoint
HOST_ADDR = 0x51  # source address byte the host puts in every request
_WRITE_ADDR = DDC_ADDR << 1  # 0x6E, folded into request checksums
_REPLY_CHECKSUM_SEED = 0x50  # replies are checksummed against the "virtual host" 0x50

GET_VCP = 0x01
GET_VCP_REPLY = 0x02
SET_VCP = 0x03
CAPABILITIES_REQUEST = 0xF3
CAPABILITIES_REPLY = 0xE3

GET_VCP_REPLY_LEN = 11  # 0x6E, len, 0x02, rc, code, type, mh, ml, sh, sl, chk
CAPABILITIES_FRAGMENT_MAX = 32


class DdcError(Exception):
    """Raised for malformed, corrupt, or negative DDC/CI replies."""


class UnsupportedFeature(DdcError):
    """The monitor answered, but says it does not support this VCP code."""


@dataclass(frozen=True)
class VcpReading:
    """A VCP feature value as reported by the monitor.

    ``current`` and ``maximum`` are the full 16-bit words (sh:sl and mh:ml). ASUS packs
    two settings into one word for several features, so callers decide how to split.
    """

    code: int
    current: int
    maximum: int
    continuous: bool = False


def _checksum(seed: int, data: bytes) -> int:
    value = seed
    for byte in data:
        value ^= byte
    return value


def _request(payload: bytes) -> bytes:
    if len(payload) > 0x7F:
        raise ValueError("DDC/CI payload too long")
    body = bytes([HOST_ADDR, 0x80 | len(payload)]) + payload
    return body + bytes([_checksum(_WRITE_ADDR, body)])


def get_vcp_request(code: int) -> bytes:
    return _request(bytes([GET_VCP, code & 0xFF]))


def set_vcp_request(code: int, value: int) -> bytes:
    if not 0 <= value <= 0xFFFF:
        raise ValueError(f"VCP value out of range: {value}")
    return _request(bytes([SET_VCP, code & 0xFF, value >> 8, value & 0xFF]))


def capabilities_request(offset: int) -> bytes:
    return _request(bytes([CAPABILITIES_REQUEST, offset >> 8, offset & 0xFF]))


def _unwrap_reply(raw: bytes) -> bytes:
    """Validate the envelope of a monitor reply and return its payload."""
    if len(raw) < 3:
        raise DdcError(f"reply too short: {raw.hex()}")
    if raw[0] != _WRITE_ADDR:
        raise DdcError(f"unexpected reply source 0x{raw[0]:02X}")
    if not raw[1] & 0x80:
        raise DdcError(f"bad reply length byte 0x{raw[1]:02X}")
    length = raw[1] & 0x7F
    if length == 0:
        # The DDC/CI "null message": the monitor is busy or ignored the request.
        raise DdcError("monitor returned a null message")
    if len(raw) < length + 3:
        raise DdcError(f"reply truncated: expected {length} payload bytes")
    frame = raw[: length + 2]
    if _checksum(_REPLY_CHECKSUM_SEED, frame) != raw[length + 2]:
        raise DdcError("reply checksum mismatch")
    return frame[2:]


def parse_get_vcp_reply(raw: bytes, code: int) -> VcpReading:
    payload = _unwrap_reply(raw)
    if len(payload) != 8 or payload[0] != GET_VCP_REPLY:
        raise DdcError(f"not a Get VCP reply: {payload.hex()}")
    result, reply_code, kind, mh, ml, sh, sl = payload[1:]
    if reply_code != code:
        raise DdcError(f"reply for VCP 0x{reply_code:02X}, expected 0x{code:02X}")
    if result == 0x01:
        raise UnsupportedFeature(f"VCP 0x{code:02X} is not supported")
    if result != 0x00:
        raise DdcError(f"VCP 0x{code:02X} result code 0x{result:02X}")
    return VcpReading(code, (sh << 8) | sl, (mh << 8) | ml, continuous=kind == 0x00)


def parse_capabilities_reply(raw: bytes, offset: int) -> bytes:
    """Return the capabilities fragment carried by ``raw`` (empty when finished)."""
    payload = _unwrap_reply(raw)
    if len(payload) < 3 or payload[0] != CAPABILITIES_REPLY:
        raise DdcError(f"not a capabilities reply: {payload.hex()}")
    reply_offset = (payload[1] << 8) | payload[2]
    if reply_offset != offset:
        raise DdcError(f"capabilities fragment at {reply_offset}, expected {offset}")
    return payload[3:]
