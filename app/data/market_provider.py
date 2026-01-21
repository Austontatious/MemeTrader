from __future__ import annotations

from typing import Dict, List, Optional, Protocol

from app.data.market_types import Candle, PriceQuote, TokenOverview, Trade


class MarketDataProvider(Protocol):
    async def get_spot_price(self, token_mint: str) -> PriceQuote:
        ...

    async def get_spot_prices(self, token_mints: List[str]) -> Dict[str, PriceQuote]:
        ...

    async def get_ohlcv(
        self,
        token_mint: str,
        interval: str,
        start_ts: int,
        end_ts: int,
        limit: Optional[int] = None,
    ) -> List[Candle]:
        ...

    async def get_token_overview(self, token_mint: str) -> TokenOverview:
        ...

    async def get_trades(
        self,
        token_mint: str,
        start_ts: Optional[int] = None,
        end_ts: Optional[int] = None,
        limit: Optional[int] = None,
    ) -> List[Trade]:
        ...


__all__ = ["MarketDataProvider"]
