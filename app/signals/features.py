from __future__ import annotations

from math import log1p
from statistics import mean, median
from typing import Dict, List

from app.signals.regime import compute_regime_score


def _get_value(candle, key: str) -> float:
    if hasattr(candle, key):
        return float(getattr(candle, key))
    return float(candle[key])


def compute_features(
    candles: List,
    lookback: int,
    vol_multiplier: float,
    compression_max_range_ratio: float = 1.25,
    compression_lookback: int | None = None,
    expansion_min_pct: float = 0.06,
    expansion_reference: str = "highest_close",
) -> Dict[str, float | int | bool]:
    if len(candles) < 2:
        return {
            "highest_close": 0.0,
            "lowest_close": 0.0,
            "avg_volume": 0.0,
            "breakout": False,
            "breakout_strict": False,
            "price_range_ratio": 1.0,
            "range_compressed": False,
            "expansion_pct": 0.0,
            "price_expanded": False,
            "return_pct": 0.0,
            "volume_accel": 0.0,
            "range_ratio": 1.0,
            "regime_score": 0,
        }

    closes = [_get_value(c, "c") for c in candles]
    volumes = [_get_value(c, "v") for c in candles]
    ranges = [_get_value(c, "h") - _get_value(c, "l") for c in candles]

    current_close = closes[-1]
    current_vol = volumes[-1]
    current_range = ranges[-1]

    lookback_window = closes[-(lookback + 1) : -1] if len(closes) > 1 else closes
    vol_window = volumes[-(lookback + 1) : -1] if len(volumes) > 1 else volumes
    range_window = ranges[-(lookback + 1) : -1] if len(ranges) > 1 else ranges

    if not lookback_window:
        lookback_window = closes[:-1]
    if not vol_window:
        vol_window = volumes[:-1]
    if not range_window:
        range_window = ranges[:-1]

    highest_close = max(lookback_window) if lookback_window else current_close
    lowest_close = min(lookback_window) if lookback_window else current_close
    avg_vol = mean(vol_window) if vol_window else current_vol
    avg_range = mean(range_window) if range_window else current_range

    ref_lookback = compression_lookback if compression_lookback and compression_lookback > 0 else lookback
    ref_window = closes[-(ref_lookback + 1) : -1] if len(closes) > 1 else closes
    if not ref_window:
        ref_window = closes[:-1]
    ref_high = max(ref_window) if ref_window else current_close
    ref_low = min(ref_window) if ref_window else current_close
    price_range_ratio = (ref_high / ref_low) if ref_low > 0 else 1.0
    range_compressed = price_range_ratio <= compression_max_range_ratio

    expansion_reference_value = ref_high
    if expansion_reference != "highest_close":
        expansion_reference_value = ref_high

    expansion_pct = 0.0
    if expansion_reference_value > 0:
        expansion_pct = (current_close / expansion_reference_value) - 1.0
    price_expanded = expansion_pct >= expansion_min_pct
    breakout_strict = range_compressed and price_expanded

    return_pct = 0.0
    if len(closes) > lookback:
        prior_close = closes[-(lookback + 1)]
        if prior_close > 0:
            return_pct = (current_close / prior_close) - 1.0

    volume_accel = (current_vol / avg_vol) - 1.0 if avg_vol > 0 else 0.0
    range_ratio = current_range / avg_range if avg_range > 0 else 1.0

    regime_score = compute_regime_score(return_pct, volume_accel, range_ratio)

    return {
        "highest_close": float(highest_close),
        "lowest_close": float(lowest_close),
        "avg_volume": float(avg_vol),
        "breakout": bool(breakout_strict),
        "breakout_strict": bool(breakout_strict),
        "price_range_ratio": float(price_range_ratio),
        "range_compressed": bool(range_compressed),
        "expansion_pct": float(expansion_pct),
        "price_expanded": bool(price_expanded),
        "return_pct": float(return_pct),
        "volume_accel": float(volume_accel),
        "range_ratio": float(range_ratio),
        "regime_score": int(regime_score),
    }


def momentum_score(candles: List, lookback: int) -> float:
    if len(candles) < lookback + 1 or lookback <= 0:
        return 0.0

    window = candles[-(lookback + 1) :]
    close_now = _get_value(window[-1], "c")
    close_then = _get_value(window[0], "c")
    if close_then <= 0:
        return 0.0

    ret = (close_now / close_then) - 1.0

    vols = [_get_value(c, "v") for c in window[:-1]]
    median_vol = median(vols) if vols else 0.0
    vol_mult = (vols[-1] / median_vol) if median_vol > 0 else 1.0

    ranges = []
    for c in window[:-1]:
        close_val = _get_value(c, "c")
        if close_val <= 0:
            continue
        ranges.append((_get_value(c, "h") - _get_value(c, "l")) / close_val)
    median_range = median(ranges) if ranges else 0.0
    range_now = (_get_value(window[-1], "h") - _get_value(window[-1], "l")) / max(close_now, 1e-9)
    range_mult = (range_now / median_range) if median_range > 0 else 1.0

    score = 100.0 * ret
    if median_vol > 0:
        score += 10.0 * log1p(max(0.0, vol_mult - 1.0))
    if median_range > 0:
        score += 5.0 * log1p(max(0.0, range_mult - 1.0))

    return float(score)
