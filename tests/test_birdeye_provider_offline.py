import asyncio

import pytest

from app.config import get_config
from app.data.birdeye.provider import MockProvider, get_market_data_provider
from app.data.market_features import build_snapshot_from_provider
from app.signals.features import momentum_score


def test_offline_provider_features(monkeypatch):
    monkeypatch.setenv("BIRDEYE_LIVE", "0")
    monkeypatch.delenv("BIRDEYE_API_KEY", raising=False)

    provider = get_market_data_provider()
    assert isinstance(provider, MockProvider)

    cfg = get_config(refresh=True)
    cfg.setdefault("rules", {})
    cfg["rules"]["breakout_lookback"] = 3
    cfg["rules"]["vol_multiplier"] = 1.0
    cfg.setdefault("breakout", {})
    cfg["breakout"]["compression_max_range_ratio"] = 10.0
    cfg["breakout"]["expansion_min_pct"] = 0.0

    snapshot = asyncio.run(
        build_snapshot_from_provider(
            provider,
            "So11111111111111111111111111111111111111112",
            "1m",
            start_ts=0,
            end_ts=10_000,
            config=cfg,
        )
    )
    assert snapshot is not None
    candles = snapshot.candles
    assert len(candles) == 5

    features = snapshot.features
    assert features["highest_close"] == 3.0
    assert features["avg_volume"] == pytest.approx(140.0)
    assert features["breakout"] is True
    assert features["return_pct"] == pytest.approx(0.75)
    assert features["volume_accel"] == pytest.approx(0.2857142857142858)
    assert features["range_ratio"] == pytest.approx(1.125)
    assert features["regime_score"] == 88

    score = momentum_score(candles, lookback=3)
    assert score == pytest.approx(76.33531392624522)
