from __future__ import annotations

from typing import Any, Dict, List, Optional

import httpx

from app.config import get_config
from app.data.mock_schemas import Candle, PairStats


class MockApiClient:
    def __init__(
        self,
        base_url: Optional[str] = None,
        timeout: float = 10.0,
        async_client: Optional[httpx.AsyncClient] = None,
    ) -> None:
        cfg = get_config()
        self.base_url = base_url or cfg.get("mock_api_base", "http://127.0.0.1:18080")
        self.timeout = timeout
        self._client = async_client
        self._owns_client = async_client is None

    async def __aenter__(self) -> "MockApiClient":
        if self._client is None:
            self._client = httpx.AsyncClient(base_url=self.base_url, timeout=self.timeout)
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        if self._owns_client and self._client is not None:
            await self._client.aclose()

    async def get_candidates(self) -> List[Dict[str, Any]]:
        resp = await self._client.get("/dex/candidates")
        resp.raise_for_status()
        return resp.json()

    async def get_pair(self, pair_id: str) -> PairStats:
        resp = await self._client.get(f"/dex/pair/{pair_id}")
        resp.raise_for_status()
        return PairStats(**resp.json())

    async def get_ohlcv(self, token_mint: str, tf: str = "1m", limit: int = 300) -> List[Candle]:
        resp = await self._client.get(f"/birdeye/ohlcv/{token_mint}", params={"tf": tf, "limit": limit})
        resp.raise_for_status()
        return [Candle(**row) for row in resp.json()]

    async def quote(
        self,
        token_in: str,
        token_out: str,
        amount_in: float,
        slippage_bps: int,
    ) -> Dict[str, Any]:
        payload = {
            "token_in": token_in,
            "token_out": token_out,
            "amount_in": amount_in,
            "slippage_bps": slippage_bps,
        }
        resp = await self._client.post("/jupiter/quote", json=payload)
        resp.raise_for_status()
        return resp.json()

    async def build_swap_tx(self, quote: Dict[str, Any], user_pubkey: str) -> Dict[str, Any]:
        payload = {"quote": quote, "user_pubkey": user_pubkey}
        resp = await self._client.post("/jupiter/build_swap_tx", json=payload)
        resp.raise_for_status()
        return resp.json()
