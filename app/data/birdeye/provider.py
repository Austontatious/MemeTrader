from __future__ import annotations

import asyncio
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Type, TypeVar

import httpx
from pydantic import ValidationError

from app.config import repo_root
from app.core.exceptions import ProviderMisconfigured, UpstreamBadResponse, UpstreamRateLimited
from app.core.fixtures import load_fixture
from app.core.request_spec import RequestSpec
from app.data.birdeye.request_factory import SUB_MINUTE_INTERVALS, BirdeyeRequestFactory
from app.data.birdeye.schemas import (
    BirdeyeMultiPriceResponse,
    BirdeyeOhlcvDataV1,
    BirdeyeOhlcvDataV3,
    BirdeyeOhlcvResponseV1,
    BirdeyeOhlcvResponseV3,
    BirdeyePriceData,
    BirdeyePriceResponse,
    BirdeyeTokenOverviewData,
    BirdeyeTokenOverviewResponse,
    BirdeyeTradeItem,
    BirdeyeTradesResponse,
)
from app.data.market_provider import MarketDataProvider
from app.data.market_types import Candle, PriceQuote, TokenOverview, Trade

T = TypeVar("T")


class CircuitBreakerOpen(RuntimeError):
    pass


@dataclass(frozen=True)
class BirdeyeSettings:
    api_key: str
    chain: str
    base_url: str
    live: bool

    @classmethod
    def from_env(cls) -> "BirdeyeSettings":
        api_key = os.getenv("BIRDEYE_API_KEY", "").strip()
        chain = os.getenv("BIRDEYE_CHAIN", "solana").strip() or "solana"
        base_url = os.getenv("BIRDEYE_BASE_URL", "https://public-api.birdeye.so").strip().rstrip("/")
        live_flag = os.getenv("BIRDEYE_LIVE", "0").strip().lower() in {"1", "true", "yes"}
        if live_flag and not api_key:
            raise ProviderMisconfigured("BIRDEYE_API_KEY is required when BIRDEYE_LIVE=1")
        return cls(api_key=api_key, chain=chain, base_url=base_url, live=live_flag and bool(api_key))


class TokenBucket:
    def __init__(self, rate_per_sec: float, capacity: Optional[float] = None) -> None:
        self.rate_per_sec = max(rate_per_sec, 0.1)
        self.capacity = capacity or self.rate_per_sec
        self.tokens = self.capacity
        self.last_refill = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self, amount: float = 1.0) -> None:
        while True:
            async with self._lock:
                now = time.monotonic()
                elapsed = now - self.last_refill
                self.tokens = min(self.capacity, self.tokens + elapsed * self.rate_per_sec)
                self.last_refill = now
                if self.tokens >= amount:
                    self.tokens -= amount
                    return
                wait_time = (amount - self.tokens) / self.rate_per_sec
            await asyncio.sleep(wait_time)


class CircuitBreaker:
    def __init__(self, failure_threshold: int = 5, cooldown_sec: float = 30.0) -> None:
        self.failure_threshold = max(1, failure_threshold)
        self.cooldown_sec = max(1.0, cooldown_sec)
        self.failures = 0
        self.open_until = 0.0

    def allow(self) -> bool:
        if self.open_until and time.monotonic() < self.open_until:
            return False
        return True

    def record_success(self) -> None:
        self.failures = 0
        self.open_until = 0.0

    def record_failure(self) -> None:
        self.failures += 1
        if self.failures >= self.failure_threshold:
            self.open_until = time.monotonic() + self.cooldown_sec
            self.failures = 0


class BirdeyeHttpClient:
    def __init__(
        self,
        timeout: float = 10.0,
        rps: float = 5.0,
        max_retries: int = 3,
        backoff_base: float = 0.5,
        backoff_max: float = 8.0,
        async_client: Optional[httpx.AsyncClient] = None,
    ) -> None:
        self.timeout = timeout
        self.max_retries = max(0, max_retries)
        self.backoff_base = max(0.1, backoff_base)
        self.backoff_max = max(backoff_max, self.backoff_base)
        self._client = async_client
        self._owns_client = async_client is None
        self._rate_limiter = TokenBucket(rate_per_sec=rps)
        self._circuit_breaker = CircuitBreaker()

    async def __aenter__(self) -> "BirdeyeHttpClient":
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self.timeout)
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        if self._owns_client and self._client is not None:
            await self._client.aclose()

    async def request(self, spec: RequestSpec) -> Dict[str, Any]:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self.timeout)
        if not self._circuit_breaker.allow():
            raise CircuitBreakerOpen("Birdeye circuit breaker is open")

        last_error: Optional[BaseException] = None
        for attempt in range(self.max_retries + 1):
            await self._rate_limiter.acquire()
            try:
                resp = await self._client.request(
                    spec.method,
                    f"{spec.base_url}{spec.path}",
                    params=spec.query,
                    headers=spec.headers,
                )
                if resp.status_code == 429:
                    self._circuit_breaker.record_failure()
                    last_error = UpstreamRateLimited("Birdeye rate limited", status_code=resp.status_code)
                    await self._sleep_backoff(attempt, resp.headers.get("Retry-After"))
                    continue
                if resp.status_code >= 500:
                    self._circuit_breaker.record_failure()
                    last_error = UpstreamBadResponse("Birdeye upstream error", status_code=resp.status_code)
                    await self._sleep_backoff(attempt, resp.headers.get("Retry-After"))
                    continue
                if resp.status_code >= 400:
                    raise UpstreamBadResponse("Birdeye request rejected", status_code=resp.status_code)
                try:
                    payload = resp.json()
                except ValueError as exc:
                    raise UpstreamBadResponse("Birdeye returned invalid JSON") from exc
                self._circuit_breaker.record_success()
                return payload
            except httpx.HTTPError as exc:
                self._circuit_breaker.record_failure()
                last_error = exc
                if attempt >= self.max_retries:
                    break
                await self._sleep_backoff(attempt)

        if last_error:
            raise last_error
        raise RuntimeError("Birdeye request failed without a response")

    async def _sleep_backoff(self, attempt: int, retry_after: Optional[str] = None) -> None:
        if retry_after:
            try:
                delay = float(retry_after)
                await asyncio.sleep(delay)
                return
            except ValueError:
                pass
        delay = min(self.backoff_max, self.backoff_base * (2**attempt))
        await asyncio.sleep(delay)


def price_quote_from_birdeye(token_mint: str, data: BirdeyePriceData) -> PriceQuote:
    return PriceQuote(
        token_mint=token_mint,
        price_usd=float(data.value),
        updated_at=int(data.update_unix_time),
        price_change_24h=float(data.price_change_24h),
        source="birdeye",
    )


def _resolve_scaled(value: float, scaled: Optional[float], scaled_enabled: Optional[bool]) -> float:
    if scaled_enabled and scaled is not None:
        return float(scaled)
    return float(value)


def _parse_birdeye_response(payload: Dict[str, Any], model: Type[T], context: str) -> T:
    if isinstance(payload, dict) and payload.get("success") is False:
        message = payload.get("message") or f"Birdeye {context} response unsuccessful"
        raise UpstreamBadResponse(message)
    try:
        return model.model_validate(payload)
    except ValidationError as exc:
        raise UpstreamBadResponse(f"Birdeye {context} response invalid") from exc


def candles_from_birdeye_v1(data: BirdeyeOhlcvDataV1) -> List[Candle]:
    scaled_enabled = bool(data.is_scaled_ui_token)
    candles: List[Candle] = []
    for item in data.items:
        candles.append(
            Candle(
                t=int(item.unix_time),
                o=_resolve_scaled(item.o, item.scaled_o, scaled_enabled),
                h=_resolve_scaled(item.h, item.scaled_h, scaled_enabled),
                l=_resolve_scaled(item.l, item.scaled_l, scaled_enabled),
                c=_resolve_scaled(item.c, item.scaled_c, scaled_enabled),
                v=_resolve_scaled(item.v, item.scaled_v, scaled_enabled),
            )
        )
    return candles


def candles_from_birdeye_v3(data: BirdeyeOhlcvDataV3) -> List[Candle]:
    scaled_enabled = bool(data.is_scaled_ui_token)
    candles: List[Candle] = []
    for item in data.items:
        candles.append(
            Candle(
                t=int(item.unix_time),
                o=_resolve_scaled(item.o, item.scaled_o, scaled_enabled),
                h=_resolve_scaled(item.h, item.scaled_h, scaled_enabled),
                l=_resolve_scaled(item.l, item.scaled_l, scaled_enabled),
                c=_resolve_scaled(item.c, item.scaled_c, scaled_enabled),
                v=_resolve_scaled(item.v, item.scaled_v, scaled_enabled),
            )
        )
    return candles


def token_overview_from_birdeye(token_mint: str, data: BirdeyeTokenOverviewData) -> TokenOverview:
    return TokenOverview(
        token_mint=token_mint,
        symbol=data.symbol,
        name=data.name,
        price_usd=data.price,
        liquidity_usd=data.liquidity,
        volume_24h=data.volume_24h,
        trade_24h=data.trade_24h,
        market_cap_usd=data.market_cap,
        fdv_usd=data.fdv,
        updated_at=data.last_trade_unix_time,
        source="birdeye",
    )


def trade_from_birdeye(token_mint: str, item: BirdeyeTradeItem) -> Trade:
    return Trade(
        token_mint=token_mint,
        tx_hash=item.tx_hash,
        side=item.side,
        price_usd=item.price,
        amount=item.size,
        volume_usd=item.volume_usd,
        ts=item.block_unix_time,
    )


class BirdeyeProvider(MarketDataProvider):
    def __init__(self, settings: BirdeyeSettings, http_client: Optional[BirdeyeHttpClient] = None) -> None:
        self.settings = settings
        self.request_factory = BirdeyeRequestFactory(
            api_key=settings.api_key, base_url=settings.base_url, chain=settings.chain
        )
        self._client = http_client or BirdeyeHttpClient()
        self._owns_client = http_client is None

    async def __aenter__(self) -> "BirdeyeProvider":
        await self._client.__aenter__()
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        if self._owns_client:
            await self._client.__aexit__(exc_type, exc, tb)

    async def get_spot_price(self, token_mint: str) -> PriceQuote:
        spec = self.request_factory.build_price_request(token_mint)
        payload = await self._client.request(spec)
        response = _parse_birdeye_response(payload, BirdeyePriceResponse, "price")
        return price_quote_from_birdeye(token_mint, response.data)

    async def get_spot_prices(self, token_mints: List[str]) -> Dict[str, PriceQuote]:
        spec = self.request_factory.build_multi_price_request(token_mints)
        payload = await self._client.request(spec)
        response = _parse_birdeye_response(payload, BirdeyeMultiPriceResponse, "multi_price")
        return {mint: price_quote_from_birdeye(mint, data) for mint, data in response.data.items()}

    async def get_ohlcv(
        self,
        token_mint: str,
        interval: str,
        start_ts: int,
        end_ts: int,
        limit: Optional[int] = None,
    ) -> List[Candle]:
        if interval in SUB_MINUTE_INTERVALS:
            return await self._get_ohlcv_v3(token_mint, interval, start_ts, end_ts, limit)
        return await self._get_ohlcv_v1(token_mint, interval, start_ts, end_ts)

    async def get_token_overview(self, token_mint: str) -> TokenOverview:
        spec = self.request_factory.build_token_overview_request(token_mint)
        payload = await self._client.request(spec)
        response = _parse_birdeye_response(payload, BirdeyeTokenOverviewResponse, "token_overview")
        return token_overview_from_birdeye(token_mint, response.data)

    async def get_trades(
        self,
        token_mint: str,
        start_ts: Optional[int] = None,
        end_ts: Optional[int] = None,
        limit: Optional[int] = None,
    ) -> List[Trade]:
        spec = self.request_factory.build_trades_token_request(token_mint, limit=limit)
        payload = await self._client.request(spec)
        response = _parse_birdeye_response(payload, BirdeyeTradesResponse, "trades")
        trades = [trade_from_birdeye(token_mint, item) for item in response.data.items]
        return trades

    async def _get_ohlcv_v1(
        self, token_mint: str, interval: str, start_ts: int, end_ts: int
    ) -> List[Candle]:
        spec = self.request_factory.build_ohlcv_v1_request(token_mint, interval, start_ts, end_ts)
        payload = await self._client.request(spec)
        response = _parse_birdeye_response(payload, BirdeyeOhlcvResponseV1, "ohlcv_v1")
        return candles_from_birdeye_v1(response.data)

    async def _get_ohlcv_v3(
        self,
        token_mint: str,
        interval: str,
        start_ts: int,
        end_ts: int,
        limit: Optional[int],
    ) -> List[Candle]:
        spec = self.request_factory.build_ohlcv_v3_request(token_mint, interval, start_ts, end_ts, limit=limit)
        payload = await self._client.request(spec)
        response = _parse_birdeye_response(payload, BirdeyeOhlcvResponseV3, "ohlcv_v3")
        return candles_from_birdeye_v3(response.data)


class MockProvider(MarketDataProvider):
    def __init__(self, fixture_dir: Optional[Path] = None) -> None:
        base_dir = fixture_dir or repo_root() / "tests" / "fixtures" / "birdeye"
        self.fixture_dir = base_dir
        self._price = BirdeyePriceResponse.model_validate(self._load("price_success.json"))
        self._multi_price = BirdeyeMultiPriceResponse.model_validate(self._load("multi_price_success.json"))
        self._ohlcv_v3 = BirdeyeOhlcvResponseV3.model_validate(self._load("ohlcv_v3_success.json"))
        self._calibration_candles: Dict[str, List[Candle]] = {}
        self._load_calibration_candles()
        self._token_overview = BirdeyeTokenOverviewResponse.model_validate(self._load("token_overview_success.json"))
        self._trades = BirdeyeTradesResponse.model_validate(self._load("txs_token_success.json"))

    async def get_spot_price(self, token_mint: str) -> PriceQuote:
        return price_quote_from_birdeye(token_mint, self._price.data)

    async def get_spot_prices(self, token_mints: List[str]) -> Dict[str, PriceQuote]:
        data_map = self._multi_price.data
        fallback = next(iter(data_map.values()))
        return {
            mint: price_quote_from_birdeye(mint, data_map.get(mint, fallback)) for mint in token_mints
        }

    async def get_ohlcv(
        self,
        token_mint: str,
        interval: str,
        start_ts: int,
        end_ts: int,
        limit: Optional[int] = None,
    ) -> List[Candle]:
        candles = self._calibration_candles.get(_normalize_calibration_key(token_mint))
        if candles is None:
            candles = candles_from_birdeye_v3(self._ohlcv_v3.data)
        filtered = [c for c in candles if start_ts <= c.t <= end_ts]
        if limit is not None:
            filtered = filtered[-limit:]
        return filtered

    async def get_token_overview(self, token_mint: str) -> TokenOverview:
        return token_overview_from_birdeye(token_mint, self._token_overview.data)

    async def get_trades(
        self,
        token_mint: str,
        start_ts: Optional[int] = None,
        end_ts: Optional[int] = None,
        limit: Optional[int] = None,
    ) -> List[Trade]:
        trades = [trade_from_birdeye(token_mint, item) for item in self._trades.data.items]
        if start_ts is not None:
            trades = [trade for trade in trades if trade.ts is not None and trade.ts >= start_ts]
        if end_ts is not None:
            trades = [trade for trade in trades if trade.ts is not None and trade.ts <= end_ts]
        if limit is not None:
            trades = trades[:limit]
        return trades

    def _load(self, name: str) -> Dict[str, Any]:
        return load_fixture(self.fixture_dir, name)

    def _load_calibration_candles(self) -> None:
        try:
            payload = self._load("ohlcv_3token_calibration.json")
        except FileNotFoundError:
            return
        if not isinstance(payload, dict):
            return
        for key, entry in payload.items():
            candles = entry.get("candles")
            if not isinstance(candles, list):
                continue
            parsed = []
            for row in candles:
                try:
                    parsed.append(Candle(**row))
                except Exception:
                    continue
            if parsed:
                self._calibration_candles[str(key)] = parsed


def _normalize_calibration_key(token_mint: str) -> str:
    if token_mint.startswith("MINT_"):
        return token_mint[5:]
    return token_mint


def get_market_data_provider(
    settings: Optional[BirdeyeSettings] = None, fixture_dir: Optional[Path] = None
) -> MarketDataProvider:
    cfg = settings or BirdeyeSettings.from_env()
    if cfg.live:
        return BirdeyeProvider(cfg)
    return MockProvider(fixture_dir=fixture_dir)


__all__ = [
    "BirdeyeHttpClient",
    "BirdeyeProvider",
    "BirdeyeSettings",
    "MockProvider",
    "get_market_data_provider",
    "candles_from_birdeye_v1",
    "candles_from_birdeye_v3",
    "price_quote_from_birdeye",
    "token_overview_from_birdeye",
    "trade_from_birdeye",
]
