from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class Candle(BaseModel):
    t: int
    o: float
    h: float
    l: float
    c: float
    v: float


class PairStats(BaseModel):
    pair_id: str
    token_mint: str
    price_usd: float
    liquidity_usd: float
    volume_5m: float
    txns_5m: int


class Zone(BaseModel):
    low: float
    high: float
    strength: int = 1


class Snapshot(BaseModel):
    pair: PairStats
    candles: List[Candle]
    support_zones: List[Zone] = Field(default_factory=list)
    resistance_zones: List[Zone] = Field(default_factory=list)
    features: Dict[str, Any] = Field(default_factory=dict)
    regime_score: int = 0
    now_ts: int = 0
    candle_index: Optional[int] = None
    last_close: float = 0.0
    last_low: float = 0.0
    last_high: float = 0.0
    resistance_levels: List[Zone] = Field(default_factory=list)
    support_level: Optional[Zone] = None
