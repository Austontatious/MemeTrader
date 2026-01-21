import pytest

from app.signals.sr_levels import compute_sr_zones


def test_sr_levels_basic():
    candles = [
        {"t": 1, "o": 1.0, "h": 1.0, "l": 0.9, "c": 0.95, "v": 100},
        {"t": 2, "o": 0.95, "h": 1.1, "l": 0.95, "c": 1.05, "v": 110},
        {"t": 3, "o": 1.05, "h": 1.3, "l": 1.0, "c": 1.2, "v": 120},
        {"t": 4, "o": 1.2, "h": 1.1, "l": 0.97, "c": 1.0, "v": 130},
        {"t": 5, "o": 1.0, "h": 1.0, "l": 0.8, "c": 0.9, "v": 140},
        {"t": 6, "o": 0.9, "h": 1.05, "l": 0.85, "c": 0.95, "v": 150},
        {"t": 7, "o": 0.95, "h": 1.1, "l": 0.9, "c": 1.0, "v": 160},
    ]

    support, resistance = compute_sr_zones(candles)
    assert len(support) == 1
    assert len(resistance) == 1

    support_zone = support[0]
    resistance_zone = resistance[0]

    assert support_zone["low"] < 0.8 < support_zone["high"]
    assert resistance_zone["low"] < 1.3 < resistance_zone["high"]
    assert support_zone["strength"] == 1
    assert resistance_zone["strength"] == 1

    assert support_zone["low"] < resistance_zone["low"]
