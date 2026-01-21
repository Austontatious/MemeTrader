from __future__ import annotations

from typing import List, Tuple


def _get_value(candle, key: str) -> float:
    if hasattr(candle, key):
        return float(getattr(candle, key))
    return float(candle[key])


def _cluster_levels(levels: List[float]) -> List[dict]:
    zones: List[dict] = []
    for price in levels:
        width = price * 0.01
        low = price - (width / 2.0)
        high = price + (width / 2.0)
        matched = False
        for zone in zones:
            if zone["low"] <= price <= zone["high"]:
                zone["strength"] += 1
                zone["low"] = min(zone["low"], low)
                zone["high"] = max(zone["high"], high)
                matched = True
                break
        if not matched:
            zones.append({"low": low, "high": high, "strength": 1})
    zones.sort(key=lambda z: z["low"])
    return zones


def compute_sr_zones(candles: List) -> Tuple[List[dict], List[dict]]:
    if len(candles) < 5:
        return [], []

    swing_highs: List[float] = []
    swing_lows: List[float] = []

    for i in range(2, len(candles) - 2):
        high = _get_value(candles[i], "h")
        low = _get_value(candles[i], "l")
        neighbors_high = max(
            _get_value(candles[i - 2], "h"),
            _get_value(candles[i - 1], "h"),
            _get_value(candles[i + 1], "h"),
            _get_value(candles[i + 2], "h"),
        )
        neighbors_low = min(
            _get_value(candles[i - 2], "l"),
            _get_value(candles[i - 1], "l"),
            _get_value(candles[i + 1], "l"),
            _get_value(candles[i + 2], "l"),
        )
        if high > neighbors_high:
            swing_highs.append(high)
        if low < neighbors_low:
            swing_lows.append(low)

    resistance = _cluster_levels(swing_highs)
    support = _cluster_levels(swing_lows)
    return support, resistance
