from __future__ import annotations

import asyncio
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

import httpx
from pydantic import ValidationError

from app.config import repo_root
from app.core.exceptions import ProviderMisconfigured, UpstreamBadResponse, UpstreamRateLimited
from app.core.fixtures import load_fixture
from app.core.request_spec import RequestSpec
from app.data.jupiter.request_factory import JupiterRequestFactory
from app.data.jupiter.schemas import JupiterQuoteResponse, JupiterSwapResponse


class CircuitBreakerOpen(RuntimeError):
    pass


@dataclass(frozen=True)
class JupiterSettings:
    api_key: str
    base_url: str
    quote_path: str
    swap_path: str
    live: bool

    @classmethod
    def from_env(cls) -> "JupiterSettings":
        api_key = os.getenv("JUPITER_API_KEY", "").strip()
        base_url = os.getenv("JUPITER_BASE_URL", "https://api.jup.ag").strip().rstrip("/")
        quote_path = os.getenv("JUPITER_QUOTE_PATH", "/swap/v1/quote").strip()
        swap_path = os.getenv("JUPITER_SWAP_PATH", "/swap/v1").strip()
        live_flag = os.getenv("JUPITER_LIVE", "0").strip().lower() in {"1", "true", "yes"}
        if live_flag and not api_key:
            raise ProviderMisconfigured("JUPITER_API_KEY is required when JUPITER_LIVE=1")
        return cls(
            api_key=api_key,
            base_url=base_url,
            quote_path=quote_path,
            swap_path=swap_path,
            live=live_flag and bool(api_key),
        )


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


class JupiterHttpClient:
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

    async def __aenter__(self) -> "JupiterHttpClient":
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
            raise CircuitBreakerOpen("Jupiter circuit breaker is open")

        last_error: Optional[BaseException] = None
        for attempt in range(self.max_retries + 1):
            await self._rate_limiter.acquire()
            try:
                resp = await self._client.request(
                    spec.method,
                    f"{spec.base_url}{spec.path}",
                    params=spec.query,
                    headers=spec.headers,
                    json=spec.json,
                )
                if resp.status_code == 429:
                    self._circuit_breaker.record_failure()
                    last_error = UpstreamRateLimited("Jupiter rate limited", status_code=resp.status_code)
                    await self._sleep_backoff(attempt, resp.headers.get("Retry-After"))
                    continue
                if resp.status_code >= 500:
                    self._circuit_breaker.record_failure()
                    last_error = UpstreamBadResponse("Jupiter upstream error", status_code=resp.status_code)
                    await self._sleep_backoff(attempt, resp.headers.get("Retry-After"))
                    continue
                if resp.status_code >= 400:
                    raise UpstreamBadResponse("Jupiter request rejected", status_code=resp.status_code)
                try:
                    payload = resp.json()
                except ValueError as exc:
                    raise UpstreamBadResponse("Jupiter returned invalid JSON") from exc
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
        raise RuntimeError("Jupiter request failed without a response")

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


def _parse_jupiter_response(payload: Dict[str, Any], model, context: str):
    if isinstance(payload, dict) and payload.get("error"):
        message = payload.get("error") or f"Jupiter {context} response error"
        raise UpstreamBadResponse(message)
    try:
        return model.model_validate(payload)
    except ValidationError as exc:
        raise UpstreamBadResponse(f"Jupiter {context} response invalid") from exc


class JupiterProvider:
    def __init__(self, settings: JupiterSettings, http_client: Optional[JupiterHttpClient] = None) -> None:
        self.settings = settings
        self.request_factory = JupiterRequestFactory(
            api_key=settings.api_key,
            base_url=settings.base_url,
            quote_path=settings.quote_path,
            swap_path=settings.swap_path,
        )
        self._client = http_client or JupiterHttpClient()
        self._owns_client = http_client is None

    async def __aenter__(self) -> "JupiterProvider":
        await self._client.__aenter__()
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        if self._owns_client:
            await self._client.__aexit__(exc_type, exc, tb)

    async def get_quote(self, params: Dict[str, Any]) -> JupiterQuoteResponse:
        spec = self.request_factory.build_quote_request(**params)
        payload = await self._client.request(spec)
        return _parse_jupiter_response(payload, JupiterQuoteResponse, "quote")

    async def build_swap_tx(self, quote_response: Dict[str, Any], user_pubkey: str, opts: Dict[str, Any]) -> JupiterSwapResponse:
        spec = self.request_factory.build_swap_request(quote_response, user_pubkey, **opts)
        payload = await self._client.request(spec)
        return _parse_jupiter_response(payload, JupiterSwapResponse, "swap")


class MockJupiterProvider:
    def __init__(self, fixture_dir: Optional[Path] = None, error_mode: Optional[str] = None) -> None:
        base_dir = fixture_dir or repo_root() / "tests" / "fixtures" / "jupiter"
        self.fixture_dir = base_dir
        self._quote_ok = self._load("quote_ok.json")
        self._swap_ok = self._load("swap_ok.json")
        self._quote_error = self._load("quote_error.json")
        self._swap_error = self._load("swap_error.json")
        self.error_mode = error_mode
        self.request_factory = JupiterRequestFactory(api_key="offline")

    async def get_quote(self, params: Dict[str, Any]) -> JupiterQuoteResponse:
        payload = self._quote_error if self.error_mode == "quote" else self._quote_ok
        return _parse_jupiter_response(payload, JupiterQuoteResponse, "quote")

    async def build_swap_tx(self, quote_response: Dict[str, Any], user_pubkey: str, opts: Dict[str, Any]) -> JupiterSwapResponse:
        payload = self._swap_error if self.error_mode == "swap" else self._swap_ok
        return _parse_jupiter_response(payload, JupiterSwapResponse, "swap")

    def _load(self, name: str) -> Dict[str, Any]:
        return load_fixture(self.fixture_dir, name)


def get_jupiter_provider(settings: Optional[JupiterSettings] = None, fixture_dir: Optional[Path] = None):
    cfg = settings or JupiterSettings.from_env()
    if cfg.live:
        return JupiterProvider(cfg)
    return MockJupiterProvider(fixture_dir=fixture_dir)


__all__ = [
    "CircuitBreakerOpen",
    "JupiterHttpClient",
    "JupiterProvider",
    "JupiterSettings",
    "MockJupiterProvider",
    "get_jupiter_provider",
]
