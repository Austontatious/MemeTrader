from __future__ import annotations

from typing import Dict, Optional

from app.data.market_provider import MarketDataProvider
from app.data.mock_schemas import PairStats, Snapshot
from app.orchestrator.snapshot import build_snapshot


async def build_snapshot_from_provider(
    provider: MarketDataProvider,
    token_mint: str,
    interval: str,
    start_ts: int,
    end_ts: int,
    config: dict,
    limit: Optional[int] = None,
    pair: Optional[PairStats] = None,
    extra_features: Optional[Dict[str, float | int | bool | str | list]] = None,
) -> Optional[Snapshot]:
    candles = await provider.get_ohlcv(token_mint, interval, start_ts, end_ts, limit=limit)
    if not candles:
        return None
    if pair is None:
        pair = PairStats(
            pair_id=token_mint,
            token_mint=token_mint,
            price_usd=0.0,
            liquidity_usd=0.0,
            volume_5m=0.0,
            txns_5m=0,
        )
    return build_snapshot(pair, candles, config, candle_index=len(candles) - 1, extra_features=extra_features)
