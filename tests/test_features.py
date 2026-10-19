from fakes import FakeMonitor, make_edid

from pg34ctl.edid import parse_edid
from pg34ctl.features import BY_KEY, FEATURES, firmware_name
from pg34ctl.monitor import Monitor


def test_feature_keys_are_unique():
    assert len(BY_KEY) == len(FEATURES)


def test_toggle_bit_encoding_preserves_other_bits():
    ub = BY_KEY["uniform_brightness"]
    assert ub.decode(0x7869) == 1
    assert ub.encode(0x7829, 1) == 0x7869
    assert ub.encode(0x7869, 0) == 0x7829


def test_byte_fields_share_a_word():
    effect, colour = BY_KEY["aura_effect"], BY_KEY["aura_color"]
    assert effect.decode(0x0602) == 0x02 and colour.decode(0x0602) == 0x06
    assert effect.encode(0x0602, 0x04) == 0x0604
    assert colour.encode(0x0604, 0x01) == 0x0104


def test_aura_off_clears_the_whole_word():
    assert BY_KEY["aura_effect"].encode(0x0602, 0) == 0


def test_firmware_name():
    assert firmware_name(0x0066) == "MCM102"
    assert firmware_name(0x0065) == "MCM101"


def test_parse_edid_reads_preferred_mode():
    info = parse_edid(make_edid(2560))
    assert (info.vendor, info.product, info.preferred_width) == ("AUS", 0xAA29, 2560)


def test_monitor_write_toggle_is_read_modify_write():
    fake = FakeMonitor()
    state = Monitor(fake).write(BY_KEY["uniform_brightness"], 0)
    assert fake.writes == [(0xFD, 0x7829)]
    assert state.value == 0


def test_monitor_write_rejects_unknown_choice():
    import pytest

    with pytest.raises(ValueError):
        Monitor(FakeMonitor()).write(BY_KEY["gamevisual"], 0x03)


def test_locked_features_are_unavailable():
    fake = FakeMonitor({0xE5: (0xFE, 0xFE)})
    state = Monitor(fake).read(BY_KEY["shadow_boost"])
    assert state.locked and not state.available


def test_hdr_mode_unavailable_in_sdr():
    states = Monitor(FakeMonitor()).read_all([BY_KEY["hdr_mode"]])
    assert not states["hdr_mode"].available


def test_read_all_reads_shared_registers_once():
    fake = FakeMonitor()
    calls = []
    original = fake.get_vcp
    fake.get_vcp = lambda code: calls.append(code) or original(code)
    Monitor(fake).read_all([BY_KEY["aura_effect"], BY_KEY["aura_color"]])
    assert calls == [0xF2]


def test_unsupported_feature_is_reported_not_raised():
    states = Monitor(FakeMonitor()).read_all([BY_KEY["crosshair"]])
    assert states["crosshair"].value is None and states["crosshair"].error
