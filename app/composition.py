from __future__ import annotations

from typing import Optional, Tuple

from app.data.birdeye.provider import MockProvider as MockMarketProvider, get_market_data_provider
from app.data.chain_provider import ChainIntelProvider
from app.data.helius.provider import MockHeliusProvider, get_chain_intel_provider
from app.data.market_provider import MarketDataProvider


def build_providers(
    market_choice: Optional[str] = None, chain_choice: Optional[str] = None
) -> Tuple[MarketDataProvider, ChainIntelProvider]:
    market = (market_choice or "").strip().lower()
    chain = (chain_choice or "").strip().lower()

    if not market:
        market = "birdeye"
    if not chain:
        chain = "helius"

    if market == "mock":
        market_provider: MarketDataProvider = MockMarketProvider()
    elif market == "birdeye":
        market_provider = get_market_data_provider()
    else:
        raise ValueError(f"Unknown MARKET_DATA provider: {market}")

    if chain == "mock":
        chain_provider: ChainIntelProvider = MockHeliusProvider()
    elif chain == "helius":
        chain_provider = get_chain_intel_provider()
    else:
        raise ValueError(f"Unknown CHAIN_INTEL provider: {chain}")

    return market_provider, chain_provider


__all__ = ["build_providers"]
