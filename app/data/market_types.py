from __future__ import annotations

from typing import Optional

from pydantic import BaseModel

from app.data.mock_schemas import Candle


class PriceQuote(BaseModel):
    token_mint: str
    price_usd: float
    updated_at: Optional[int] = None
    price_change_24h: Optional[float] = None
    source: Optional[str] = None


class TokenOverview(BaseModel):
    token_mint: str
    symbol: Optional[str] = None
    name: Optional[str] = None
    price_usd: Optional[float] = None
    liquidity_usd: Optional[float] = None
    volume_24h: Optional[float] = None
    trade_24h: Optional[float] = None
    market_cap_usd: Optional[float] = None
    fdv_usd: Optional[float] = None
    updated_at: Optional[int] = None
    source: Optional[str] = None


class Trade(BaseModel):
    token_mint: str
    tx_hash: Optional[str] = None
    side: Optional[str] = None
    price_usd: Optional[float] = None
    amount: Optional[float] = None
    volume_usd: Optional[float] = None
    ts: Optional[int] = None


__all__ = ["Candle", "PriceQuote", "TokenOverview", "Trade"]
