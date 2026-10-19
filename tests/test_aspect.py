import pytest
from fakes import FakeMonitor

from pg34ctl.aspect import Aspect, AspectError, Scaling, current_aspect, switch_aspect


class Clock:
    def __init__(self):
        self.now = 0.0

    def sleep(self, seconds):
        self.now += seconds

    def __call__(self):
        return self.now


def _switch(fake, target, **kw):
    clock = Clock()
    return switch_aspect(fake, target, sleep=clock.sleep, clock=clock, **kw)


def test_current_aspect_from_edid():
    assert current_aspect(FakeMonitor(width=3440)) is Aspect.WIDE
    assert current_aspect(FakeMonitor(width=2560)) is Aspect.STANDARD


def test_switch_to_16_9_presses_the_mapped_path():
    fake = FakeMonitor(width=3440)
    assert _switch(fake, Aspect.STANDARD) is True
    presses = [v for code, v in fake.writes if code == 0xEB]
    assert presses == [0, 1, 3, 6, 3, 3, 3, 3, 6, 3, 6, 3, 6, 0]
    assert current_aspect(fake) is Aspect.STANDARD


def test_switch_back_to_21_9_uses_up():
    fake = FakeMonitor(width=2560)
    assert _switch(fake, Aspect.WIDE) is True
    presses = [v for code, v in fake.writes if code == 0xEB]
    assert presses[9] == 2
    assert current_aspect(fake) is Aspect.WIDE


def test_already_in_target_only_fixes_scaling():
    fake = FakeMonitor(width=2560)
    assert _switch(fake, Aspect.STANDARD, scaling=Scaling.FULL) is False
    assert fake.writes == [(0x86, 0x02)]


def test_full_scaling_written_after_switch():
    fake = FakeMonitor(width=3440)
    _switch(fake, Aspect.STANDARD, scaling=Scaling.FULL)
    assert fake.writes[-1] == (0x86, 0x02)


def test_refuses_with_hdr_on():
    fake = FakeMonitor({0xE2: (0x0102, 0x0108)})
    with pytest.raises(AspectError, match="HDR"):
        _switch(fake, Aspect.STANDARD)
    assert not fake.writes


def test_refuses_with_pip_on():
    fake = FakeMonitor({0xF4: (0x01, 0x07)})
    with pytest.raises(AspectError, match="PIP"):
        _switch(fake, Aspect.STANDARD)


def test_times_out_and_closes_menu_when_osd_path_fails():
    fake = FakeMonitor()
    fake.osd_works = False
    with pytest.raises(AspectError, match="did not switch"):
        _switch(fake, Aspect.STANDARD)
    assert fake.writes[-1] == (0xEB, 0)


def test_scaling_survives_a_noisy_bus_after_the_switch():
    from pg34ctl.ddc import DdcError

    fake = FakeMonitor(width=3440)
    original = fake.get_vcp
    failures = {"left": 3}

    def flaky(code):
        if code == 0x86 and fake.width == 2560 and failures["left"]:
            failures["left"] -= 1
            raise DdcError("reply for VCP 0xDD, expected 0x86")
        return original(code)

    fake.get_vcp = flaky
    assert _switch(fake, Aspect.STANDARD, scaling=Scaling.FULL) is True
    assert fake.registers[0x86][0] == 0x02
