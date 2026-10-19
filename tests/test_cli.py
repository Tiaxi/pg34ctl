import pytest

from pg34ctl.cli import _parse_value, build_parser
from pg34ctl.features import BY_KEY


def test_choice_by_label_ignores_case_and_spaces():
    assert _parse_value(BY_KEY["gamevisual"], "racing") == 0x05
    assert _parse_value(BY_KEY["gamevisual"], "srgbcal") == 0x0A
    assert _parse_value(BY_KEY["hdr_mode"], "gaming hdr") == 0x0102


def test_toggle_words():
    assert _parse_value(BY_KEY["vrr"], "on") == 1
    assert _parse_value(BY_KEY["vrr"], "OFF") == 0


def test_numbers_in_any_base():
    assert _parse_value(BY_KEY["brightness"], "40") == 40
    assert _parse_value(BY_KEY["gamma"], "0x7800") == 0x7800


def test_bad_value_lists_options():
    with pytest.raises(SystemExit, match="Racing"):
        _parse_value(BY_KEY["gamevisual"], "bogus")


def test_aspect_arguments():
    args = build_parser().parse_args(["aspect", "16:9", "--scaling", "full"])
    assert (args.ratio, args.scaling) == ("16:9", "full")


def test_unique_prefix_matches_a_choice():
    assert _parse_value(BY_KEY["power_setting"], "performance") == 0
    with pytest.raises(SystemExit):
        _parse_value(BY_KEY["hdr_mode"], "c")  # Cinema HDR or Console HDR
