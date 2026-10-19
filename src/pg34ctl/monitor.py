"""High-level access to the PG34WCDN on top of a DDC backend."""

from __future__ import annotations

from dataclasses import dataclass

from .ddc import DdcBackend, DdcError, UnsupportedFeature, VcpReading
from .edid import EdidInfo, parse_edid
from .features import (
    FEATURES,
    FIRMWARE,
    PIXEL_CLEANING_BIT,
    USAGE_HOURS,
    Feature,
    Kind,
    firmware_name,
    is_locked,
)


@dataclass(frozen=True)
class FeatureState:
    feature: Feature
    value: int | None  # decoded value, None when the monitor would not answer
    maximum: int = 0
    locked: bool = False
    error: str = ""

    @property
    def available(self) -> bool:
        if self.value is None or self.locked:
            return False
        if self.feature.kind is Kind.CHOICE:
            return self.value in self.feature.choices
        return True


class Monitor:
    def __init__(self, backend: DdcBackend) -> None:
        self.backend = backend

    def read(self, feature: Feature) -> FeatureState:
        try:
            reading = self.backend.get_vcp(feature.code)
        except (DdcError, UnsupportedFeature) as exc:
            return FeatureState(feature, None, error=str(exc))
        return self._state(feature, reading)

    def read_all(self, features: list[Feature] = FEATURES) -> dict[str, FeatureState]:
        # Several features share one register; read each code once.
        readings: dict[int, VcpReading | Exception] = {}
        states = {}
        for feature in features:
            if feature.code not in readings:
                try:
                    readings[feature.code] = self.backend.get_vcp(feature.code)
                except (DdcError, UnsupportedFeature) as exc:
                    readings[feature.code] = exc
            reading = readings[feature.code]
            if isinstance(reading, Exception):
                states[feature.key] = FeatureState(feature, None, error=str(reading))
            else:
                states[feature.key] = self._state(feature, reading)
        return states

    @staticmethod
    def _state(feature: Feature, reading: VcpReading) -> FeatureState:
        maximum = reading.maximum if feature.mask == 0xFFFF else feature.decode(reading.maximum)
        locked = is_locked(reading.maximum) or (
            feature.kind is Kind.CHOICE and feature.mask == 0xFFFF and reading.maximum == 0
        )
        return FeatureState(feature, feature.decode(reading.current), maximum, locked)

    def write(self, feature: Feature, value: int) -> FeatureState:
        if feature.kind is Kind.CHOICE and value not in feature.choices:
            raise ValueError(f"{value!r} is not a valid {feature.label} value")
        word = value
        if feature.mask != 0xFFFF or feature.zero_clears_word:
            word = feature.encode(self.backend.get_vcp(feature.code).current, value)
        self.backend.set_vcp(feature.code, word)
        return self.read(feature)

    def firmware(self) -> str:
        return firmware_name(self.backend.get_vcp(FIRMWARE).maximum)

    def usage_hours(self) -> int:
        return self.backend.get_vcp(USAGE_HOURS).current

    def start_pixel_cleaning(self) -> None:
        current = self.backend.get_vcp(0xFD).current
        self.backend.set_vcp(0xFD, current | PIXEL_CLEANING_BIT)

    def edid(self) -> EdidInfo:
        return parse_edid(self.backend.edid())

    def close(self) -> None:
        self.backend.close()
