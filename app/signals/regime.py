from __future__ import annotations


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def compute_regime_score(return_pct: float, volume_accel: float, range_ratio: float) -> int:
    score = 50.0
    score += _clamp(return_pct * 2000.0, -30.0, 30.0)
    score += _clamp(volume_accel * 20.0, -20.0, 20.0)
    score += _clamp((range_ratio - 1.0) * 20.0, -20.0, 20.0)
    score = _clamp(score, 0.0, 100.0)
    return int(round(score))
