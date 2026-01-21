from __future__ import annotations

from typing import Dict, List, Optional

from app.data.mock_schemas import Candle, PairStats, Snapshot, Zone
from app.signals.features import compute_features
from app.signals.sr_levels import compute_sr_zones


def build_snapshot(
    pair: PairStats,
    candles: List[Candle],
    config: dict,
    candle_index: Optional[int] = None,
    extra_features: Optional[Dict[str, float | int | bool | str | list]] = None,
) -> Snapshot:
    support_raw, resistance_raw = compute_sr_zones(candles)
    support_zones = [Zone(**zone) for zone in support_raw]
    resistance_zones = [Zone(**zone) for zone in resistance_raw]

    rules_cfg = config.get("rules", {})
    breakout_cfg = config.get("breakout", {})
    lookback = int(rules_cfg.get("breakout_lookback", 20))
    vol_multiplier = float(rules_cfg.get("vol_multiplier", 1.0))
    compression_max_range_ratio = float(breakout_cfg.get("compression_max_range_ratio", 1.25))
    compression_lookback = breakout_cfg.get("compression_lookback_bars")
    if compression_lookback is not None:
        compression_lookback = int(compression_lookback)
    expansion_min_pct = float(breakout_cfg.get("expansion_min_pct", 0.06))
    expansion_reference = str(breakout_cfg.get("expansion_reference", "highest_close"))

    features = compute_features(
        candles,
        lookback,
        vol_multiplier,
        compression_max_range_ratio=compression_max_range_ratio,
        compression_lookback=compression_lookback,
        expansion_min_pct=expansion_min_pct,
        expansion_reference=expansion_reference,
    )
    if extra_features:
        features.update(extra_features)
    regime_score = int(features.get("regime_score", 0))

    last = candles[-1]
    last_close = float(last.c)
    last_low = float(last.l)
    last_high = float(last.h)
    now_ts = int(last.t)

    resistance_levels = [zone for zone in resistance_zones if zone.low >= last_close]
    resistance_levels.sort(key=lambda z: z.low)
    resistance_levels = resistance_levels[:3]

    support_levels = [zone for zone in support_zones if zone.high <= last_close]
    support_levels.sort(key=lambda z: z.low)
    support_level = support_levels[-1] if support_levels else None

    return Snapshot(
        pair=pair,
        candles=candles,
        support_zones=support_zones,
        resistance_zones=resistance_zones,
        features=features,
        regime_score=regime_score,
        now_ts=now_ts,
        candle_index=candle_index,
        last_close=last_close,
        last_low=last_low,
        last_high=last_high,
        resistance_levels=resistance_levels,
        support_level=support_level,
    )
