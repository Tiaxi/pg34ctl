import pytest

from pg34ctl.ddc import protocol as p


def _reply(payload: bytes) -> bytes:
    frame = bytes([0x6E, 0x80 | len(payload)]) + payload
    chk = 0x50
    for b in frame:
        chk ^= b
    return frame + bytes([chk])


def test_get_vcp_request_matches_known_bytes():
    # Brightness request as captured from ddcutil traces.
    assert p.get_vcp_request(0x10) == bytes([0x51, 0x82, 0x01, 0x10, 0xAC])


def test_set_vcp_request_encodes_16_bit_value():
    req = p.set_vcp_request(0xFD, 0x7869)
    assert req[:6] == bytes([0x51, 0x84, 0x03, 0xFD, 0x78, 0x69])
    chk = 0x6E
    for b in req[:-1]:
        chk ^= b
    assert req[-1] == chk


def test_set_vcp_request_rejects_out_of_range():
    with pytest.raises(ValueError):
        p.set_vcp_request(0x10, 0x10000)


def test_parse_get_vcp_reply_splits_words():
    raw = _reply(bytes([0x02, 0x00, 0xFF, 0x01, 0x00, 0x66, 0x00, 0x30]))
    reading = p.parse_get_vcp_reply(raw, 0xFF)
    assert reading == p.VcpReading(0xFF, current=0x0030, maximum=0x0066, continuous=False)


def test_parse_get_vcp_reply_continuous_flag():
    raw = _reply(bytes([0x02, 0x00, 0x10, 0x00, 0x00, 0x64, 0x00, 0x28]))
    reading = p.parse_get_vcp_reply(raw, 0x10)
    assert reading.continuous and reading.current == 40 and reading.maximum == 100


def test_parse_get_vcp_reply_unsupported():
    raw = _reply(bytes([0x02, 0x01, 0xD3, 0x00, 0x00, 0x00, 0x00, 0x00]))
    with pytest.raises(p.UnsupportedFeature):
        p.parse_get_vcp_reply(raw, 0xD3)


def test_parse_get_vcp_reply_rejects_bad_checksum():
    raw = bytearray(_reply(bytes([0x02, 0x00, 0x10, 0x00, 0x00, 0x64, 0x00, 0x28])))
    raw[-1] ^= 0xFF
    with pytest.raises(p.DdcError, match="checksum"):
        p.parse_get_vcp_reply(bytes(raw), 0x10)


def test_parse_get_vcp_reply_rejects_wrong_code():
    raw = _reply(bytes([0x02, 0x00, 0x12, 0x00, 0x00, 0x64, 0x00, 0x50]))
    with pytest.raises(p.DdcError, match="expected 0x10"):
        p.parse_get_vcp_reply(raw, 0x10)


def test_null_message_is_an_error():
    with pytest.raises(p.DdcError, match="null message"):
        p.parse_get_vcp_reply(bytes([0x6E, 0x80, 0xBE]), 0x10)


def test_parse_capabilities_fragment():
    raw = _reply(bytes([0xE3, 0x00, 0x20]) + b"(prot(monitor)")
    assert p.parse_capabilities_reply(raw, 0x20) == b"(prot(monitor)"


def test_parse_capabilities_end_is_empty():
    raw = _reply(bytes([0xE3, 0x01, 0x00]))
    assert p.parse_capabilities_reply(raw, 0x100) == b""
