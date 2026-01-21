from __future__ import annotations

import time
from typing import Any, Dict, Iterable, Optional

from app.core.request_spec import RequestSpec


SUBMINUTE_START_TS = 1746203400
RETENTION_1S_SEC = 14 * 24 * 60 * 60
RETENTION_15S_SEC = 90 * 24 * 60 * 60
RETENTION_30S_SEC = 90 * 24 * 60 * 60
SUB_MINUTE_INTERVALS = {"1s", "15s", "30s"}


class BirdeyeRequestError(ValueError):
    pass


class BirdeyeLimitError(BirdeyeRequestError):
    pass


class BirdeyeRetentionError(BirdeyeRequestError):
    pass


class BirdeyeRequestFactory:
    def __init__(self, api_key: str, base_url: str = "https://public-api.birdeye.so", chain: str = "solana") -> None:
        self.api_key = (api_key or "").strip()
        self.base_url = base_url.rstrip("/")
        self.chain = (chain or "solana").strip()

    def build_price_request(
        self,
        mint: str,
        chain: Optional[str] = None,
        check_liquidity: Optional[bool] = None,
        include_liquidity: Optional[bool] = None,
        ui_amount_mode: Optional[str] = None,
    ) -> RequestSpec:
        query: Dict[str, Any] = {"address": mint}
        if check_liquidity is not None:
            query["check_liquidity"] = check_liquidity
        if include_liquidity is not None:
            query["include_liquidity"] = include_liquidity
        if ui_amount_mode is not None:
            query["ui_amount_mode"] = ui_amount_mode
        return RequestSpec(
            method="GET",
            base_url=self.base_url,
            path="/defi/price",
            query=query,
            headers=self._headers(chain),
        )

    def build_multi_price_request(
        self,
        mints: Iterable[str],
        chain: Optional[str] = None,
        check_liquidity: Optional[bool] = None,
        include_liquidity: Optional[bool] = None,
        ui_amount_mode: Optional[str] = None,
    ) -> RequestSpec:
        mint_list = list(mints)
        if len(mint_list) > 100:
            raise BirdeyeLimitError("multi_price supports up to 100 tokens")
        if not mint_list:
            raise BirdeyeRequestError("multi_price requires at least one token")
        query: Dict[str, Any] = {"list_address": ",".join(mint_list)}
        if check_liquidity is not None:
            query["check_liquidity"] = check_liquidity
        if include_liquidity is not None:
            query["include_liquidity"] = include_liquidity
        if ui_amount_mode is not None:
            query["ui_amount_mode"] = ui_amount_mode
        return RequestSpec(
            method="GET",
            base_url=self.base_url,
            path="/defi/multi_price",
            query=query,
            headers=self._headers(chain),
        )

    def build_ohlcv_v1_request(
        self,
        mint: str,
        interval: str,
        start_ts: int,
        end_ts: int,
        chain: Optional[str] = None,
        currency: Optional[str] = None,
        ui_amount_mode: Optional[str] = None,
    ) -> RequestSpec:
        query: Dict[str, Any] = {
            "address": mint,
            "type": interval,
            "time_from": int(start_ts),
            "time_to": int(end_ts),
        }
        if currency is not None:
            query["currency"] = currency
        if ui_amount_mode is not None:
            query["ui_amount_mode"] = ui_amount_mode
        return RequestSpec(
            method="GET",
            base_url=self.base_url,
            path="/defi/ohlcv",
            query=query,
            headers=self._headers(chain),
        )

    def build_ohlcv_v3_request(
        self,
        mint: str,
        interval: str,
        start_ts: int,
        end_ts: int,
        limit: Optional[int] = None,
        chain: Optional[str] = None,
        currency: Optional[str] = None,
        mode: Optional[str] = None,
        padding: Optional[bool] = None,
        outlier: Optional[bool] = None,
        ui_amount_mode: Optional[str] = None,
        now_ts: Optional[int] = None,
    ) -> RequestSpec:
        if limit is not None and limit > 5000:
            raise BirdeyeLimitError("ohlcv v3 supports up to 5000 records")
        self._validate_subminute_retention(interval, start_ts, now_ts)
        query: Dict[str, Any] = {
            "address": mint,
            "type": interval,
            "time_from": int(start_ts),
            "time_to": int(end_ts),
        }
        if currency is not None:
            query["currency"] = currency
        if limit is not None:
            query["count_limit"] = int(limit)
            query["mode"] = mode or "count"
        elif mode is not None:
            query["mode"] = mode
        if padding is not None:
            query["padding"] = padding
        if outlier is not None:
            query["outlier"] = outlier
        if ui_amount_mode is not None:
            query["ui_amount_mode"] = ui_amount_mode
        return RequestSpec(
            method="GET",
            base_url=self.base_url,
            path="/defi/v3/ohlcv",
            query=query,
            headers=self._headers(chain),
        )

    def build_token_overview_request(
        self,
        mint: str,
        chain: Optional[str] = None,
        frames: Optional[str] = None,
        ui_amount_mode: Optional[str] = None,
    ) -> RequestSpec:
        query: Dict[str, Any] = {"address": mint}
        if frames is not None:
            query["frames"] = frames
        if ui_amount_mode is not None:
            query["ui_amount_mode"] = ui_amount_mode
        return RequestSpec(
            method="GET",
            base_url=self.base_url,
            path="/defi/token_overview",
            query=query,
            headers=self._headers(chain),
        )

    def build_trades_token_request(
        self,
        mint: str,
        chain: Optional[str] = None,
        offset: Optional[int] = None,
        limit: Optional[int] = None,
        tx_type: Optional[str] = "swap",
        sort_type: Optional[str] = "desc",
        ui_amount_mode: Optional[str] = None,
    ) -> RequestSpec:
        query: Dict[str, Any] = {"address": mint, "sort_type": sort_type or "desc"}
        if offset is not None:
            query["offset"] = int(offset)
        if limit is not None:
            query["limit"] = int(limit)
        if tx_type is not None:
            query["tx_type"] = tx_type
        if ui_amount_mode is not None:
            query["ui_amount_mode"] = ui_amount_mode
        return RequestSpec(
            method="GET",
            base_url=self.base_url,
            path="/defi/txs/token",
            query=query,
            headers=self._headers(chain),
        )

    def build_token_trending_request(
        self,
        sort_by: str = "rank",
        sort_type: str = "asc",
        interval: Optional[str] = None,
        chain: Optional[str] = None,
        offset: Optional[int] = None,
        limit: Optional[int] = None,
        ui_amount_mode: Optional[str] = None,
    ) -> RequestSpec:
        query: Dict[str, Any] = {"sort_by": sort_by, "sort_type": sort_type}
        if interval is not None:
            query["interval"] = interval
        if offset is not None:
            query["offset"] = int(offset)
        if limit is not None:
            query["limit"] = int(limit)
        if ui_amount_mode is not None:
            query["ui_amount_mode"] = ui_amount_mode
        return RequestSpec(
            method="GET",
            base_url=self.base_url,
            path="/defi/token_trending",
            query=query,
            headers=self._headers(chain),
        )

    def _headers(self, chain: Optional[str]) -> Dict[str, str]:
        chain_value = (chain or self.chain).strip()
        if not chain_value:
            raise BirdeyeRequestError("x-chain header is required")
        return {"X-API-KEY": self.api_key, "x-chain": chain_value}

    def _validate_subminute_retention(self, interval: str, start_ts: int, now_ts: Optional[int]) -> None:
        if interval not in SUB_MINUTE_INTERVALS:
            return
        now_value = int(time.time()) if now_ts is None else int(now_ts)
        if start_ts < SUBMINUTE_START_TS:
            raise BirdeyeRetentionError("sub-minute data is not available before 2025-05-02T16:30:00Z")
        age = now_value - int(start_ts)
        if interval == "1s" and age > RETENTION_1S_SEC:
            raise BirdeyeRetentionError("1s data is retained for roughly 2 weeks")
        if interval in {"15s", "30s"} and age > RETENTION_15S_SEC:
            raise BirdeyeRetentionError("15s/30s data is retained for roughly 3 months")
