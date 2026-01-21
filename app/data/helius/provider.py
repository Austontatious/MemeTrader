from __future__ import annotations

import asyncio
import hmac
import os
import time
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any, Dict, List, Optional, Type, TypeVar

import httpx
from pydantic import ValidationError

from app.config import repo_root
from app.core.fixtures import load_fixture
from app.data.chain_provider import ChainIntelProvider
from app.data.chain_types import (
    EnhancedTx,
    NativeTransfer,
    TokenTransfer,
    TransactionStreamEvent,
    WebhookConfig,
    WebhookInfo,
)
from app.core.exceptions import ProviderMisconfigured, UpstreamBadResponse, UpstreamRateLimited
from app.core.request_spec import JsonRpcSpec, RequestSpec
from app.data.helius.request_factory import HeliusRequestFactory
from app.data.helius.schemas import (
    HeliusEnhancedTx,
    HeliusRpcResponse,
    HeliusTransactionNotification,
    HeliusWebhookResponse,
)


class CircuitBreakerOpen(RuntimeError):
    pass


T = TypeVar("T")


@dataclass(frozen=True)
class HeliusSettings:
    api_key: str
    rpc_url: str
    enhanced_base: str
    ws_url: str
    rest_auth_mode: str
    rest_auth_header: str
    rest_auth_prefix: str
    webhook_secret: str
    webhook_signature_header: str
    live: bool

    @classmethod
    def from_env(cls) -> "HeliusSettings":
        api_key = os.getenv("HELIUS_API_KEY", "").strip()
        rpc_url = os.getenv("HELIUS_RPC_URL", "https://mainnet.helius-rpc.com/").strip()
        enhanced_base = os.getenv("HELIUS_ENHANCED_BASE", "https://api-mainnet.helius-rpc.com").strip()
        ws_url = os.getenv("HELIUS_WS_URL", "wss://mainnet.helius-rpc.com/").strip()
        rest_auth_mode = os.getenv("HELIUS_REST_AUTH_MODE", "query").strip()
        rest_auth_header = os.getenv("HELIUS_REST_AUTH_HEADER", "X-API-KEY").strip()
        rest_auth_prefix = os.getenv("HELIUS_REST_AUTH_PREFIX", "").strip()
        webhook_secret = os.getenv("HELIUS_WEBHOOK_SECRET", "").strip()
        signature_header = os.getenv("HELIUS_WEBHOOK_SIGNATURE_HEADER", "x-helius-signature").strip()
        live_flag = os.getenv("HELIUS_LIVE", "0").strip().lower() in {"1", "true", "yes"}
        if live_flag and not api_key:
            raise ProviderMisconfigured("HELIUS_API_KEY is required when HELIUS_LIVE=1")
        return cls(
            api_key=api_key,
            rpc_url=rpc_url,
            enhanced_base=enhanced_base,
            ws_url=ws_url,
            rest_auth_mode=rest_auth_mode,
            rest_auth_header=rest_auth_header,
            rest_auth_prefix=rest_auth_prefix,
            webhook_secret=webhook_secret,
            webhook_signature_header=signature_header.lower(),
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


class HeliusHttpClient:
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

    async def __aenter__(self) -> "HeliusHttpClient":
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self.timeout)
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        if self._owns_client and self._client is not None:
            await self._client.aclose()

    async def request(self, spec: RequestSpec | JsonRpcSpec) -> Dict[str, Any]:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self.timeout)
        if not self._circuit_breaker.allow():
            raise CircuitBreakerOpen("Helius circuit breaker is open")

        request_spec = spec.to_request_spec() if isinstance(spec, JsonRpcSpec) else spec
        last_error: Optional[BaseException] = None
        for attempt in range(self.max_retries + 1):
            await self._rate_limiter.acquire()
            try:
                resp = await self._client.request(
                    request_spec.method,
                    f"{request_spec.base_url}{request_spec.path}",
                    params=request_spec.query,
                    headers=request_spec.headers,
                    json=request_spec.json,
                )
                if resp.status_code == 429:
                    self._circuit_breaker.record_failure()
                    last_error = UpstreamRateLimited("Helius rate limited", status_code=resp.status_code)
                    await self._sleep_backoff(attempt, resp.headers.get("Retry-After"))
                    continue
                if resp.status_code >= 500:
                    self._circuit_breaker.record_failure()
                    last_error = UpstreamBadResponse("Helius upstream error", status_code=resp.status_code)
                    await self._sleep_backoff(attempt, resp.headers.get("Retry-After"))
                    continue
                if resp.status_code >= 400:
                    raise UpstreamBadResponse("Helius request rejected", status_code=resp.status_code)
                try:
                    payload = resp.json()
                except ValueError as exc:
                    raise UpstreamBadResponse("Helius returned invalid JSON") from exc
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
        raise RuntimeError("Helius request failed without a response")

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


def _build_webhook_body(config: WebhookConfig) -> Dict[str, Any]:
    return {
        "webhookURL": config.webhook_url,
        "accountAddresses": config.account_addresses,
        "transactionTypes": config.transaction_types,
        "webhookType": config.webhook_type,
    }


def _validate_model(payload: Any, model: Type[T], context: str) -> T:
    try:
        return model.model_validate(payload)
    except ValidationError as exc:
        raise UpstreamBadResponse(f"Helius {context} response invalid") from exc


def enhanced_tx_from_helius(tx: HeliusEnhancedTx) -> EnhancedTx:
    native_transfers = [
        NativeTransfer(
            from_user=transfer.from_user_account,
            to_user=transfer.to_user_account,
            amount=int(transfer.amount),
        )
        for transfer in tx.native_transfers
    ]
    token_transfers = [
        TokenTransfer(
            from_user=transfer.from_user_account,
            to_user=transfer.to_user_account,
            mint=transfer.mint,
            amount=float(transfer.token_amount.amount),
            decimals=transfer.token_amount.decimals,
            ui_amount=transfer.token_amount.ui_amount,
        )
        for transfer in tx.token_transfers
    ]
    return EnhancedTx(
        signature=tx.signature,
        timestamp=int(tx.timestamp),
        type=tx.type,
        source=tx.source,
        fee=tx.fee,
        fee_payer=tx.fee_payer,
        native_transfers=native_transfers,
        token_transfers=token_transfers,
    )


def transaction_event_from_notification(notification: HeliusTransactionNotification) -> TransactionStreamEvent:
    tx = enhanced_tx_from_helius(notification.params.result)
    return TransactionStreamEvent(subscription=notification.params.subscription, tx=tx)


def webhook_info_from_response(response: HeliusWebhookResponse) -> WebhookInfo:
    return WebhookInfo(
        webhook_id=response.webhook_id,
        webhook_url=response.webhook_url or "",
        account_addresses=response.account_addresses,
        transaction_types=response.transaction_types,
        webhook_type=response.webhook_type,
    )


def _normalize_calibration_key(token_mint: str) -> str:
    if token_mint.startswith("MINT_"):
        return token_mint[5:]
    return token_mint


class HeliusProvider(ChainIntelProvider):
    def __init__(self, settings: HeliusSettings, http_client: Optional[HeliusHttpClient] = None) -> None:
        self.settings = settings
        self.request_factory = HeliusRequestFactory(
            api_key=settings.api_key,
            rpc_url=settings.rpc_url,
            enhanced_base=settings.enhanced_base,
            ws_url=settings.ws_url,
            rest_auth_mode=settings.rest_auth_mode,
            rest_auth_header=settings.rest_auth_header,
            rest_auth_prefix=settings.rest_auth_prefix,
        )
        self._client = http_client or HeliusHttpClient()
        self._owns_client = http_client is None

    async def __aenter__(self) -> "HeliusProvider":
        await self._client.__aenter__()
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        if self._owns_client:
            await self._client.__aexit__(exc_type, exc, tb)

    async def rpc_call(self, method: str, params: Optional[List[Any]] = None) -> Dict[str, Any]:
        spec = self.request_factory.build_rpc_request(method, params=params)
        payload = await self._client.request(spec)
        if isinstance(payload, dict) and payload.get("error"):
            raise UpstreamBadResponse("Helius RPC error")
        response = _validate_model(payload, HeliusRpcResponse, "rpc")
        return response.result

    async def get_enhanced_txs_by_address(
        self,
        address: str,
        before: Optional[str] = None,
        until: Optional[str] = None,
        tx_type: Optional[str] = None,
        source: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> List[EnhancedTx]:
        spec = self.request_factory.build_enhanced_txs_request(
            address=address,
            before=before,
            until=until,
            tx_type=tx_type,
            source=source,
            limit=limit,
        )
        payload = await self._client.request(spec)
        try:
            txs = [_validate_model(item, HeliusEnhancedTx, "enhanced_tx") for item in payload]
        except TypeError as exc:
            raise UpstreamBadResponse("Helius enhanced txs response invalid") from exc
        return [enhanced_tx_from_helius(tx) for tx in txs]

    def ws_subscribe_transactions(
        self, tx_filter: Dict[str, Any], options: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        spec = self.request_factory.build_transaction_subscribe_message(tx_filter, options=options)
        return spec["message"]

    async def create_webhook(self, config: WebhookConfig) -> WebhookInfo:
        spec = self.request_factory.build_webhook_create_request(_build_webhook_body(config))
        payload = await self._client.request(spec)
        response = _validate_model(payload, HeliusWebhookResponse, "webhook")
        return webhook_info_from_response(response)

    def verify_webhook_signature(self, headers: Dict[str, str], raw_body: bytes) -> bool:
        secret = self.settings.webhook_secret
        if not secret:
            return True
        header_name = self.settings.webhook_signature_header
        provided = ""
        for key, value in headers.items():
            if key.lower() == header_name:
                provided = value
                break
        if not provided:
            return False
        digest = hmac.new(secret.encode("utf-8"), raw_body, sha256).hexdigest()
        return hmac.compare_digest(digest, provided)


class MockHeliusProvider(ChainIntelProvider):
    def __init__(self, fixture_dir: Optional[Path] = None) -> None:
        base_dir = fixture_dir or repo_root() / "tests" / "fixtures" / "helius"
        self.fixture_dir = base_dir
        self._rpc_tx = HeliusRpcResponse.model_validate(self._load("rpc_getTransaction_success.json"))
        self._enhanced_txs = [
            HeliusEnhancedTx.model_validate(item)
            for item in self._load("enhanced_address_txs_success.json")
        ]
        self._chain_calibration: Dict[str, Dict[str, Any]] = {}
        self._load_chain_calibration()
        self._ws_event = HeliusTransactionNotification.model_validate(
            self._load("transaction_subscribe_event.json")
        )
        self._webhook = HeliusWebhookResponse.model_validate(self._load("create_webhook_response.json"))
        self.request_factory = HeliusRequestFactory(api_key="offline")

    async def rpc_call(self, method: str, params: Optional[List[Any]] = None) -> Dict[str, Any]:
        return self._rpc_tx.result

    async def get_enhanced_txs_by_address(
        self,
        address: str,
        before: Optional[str] = None,
        until: Optional[str] = None,
        tx_type: Optional[str] = None,
        source: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> List[EnhancedTx]:
        txs = [enhanced_tx_from_helius(tx) for tx in self._enhanced_txs]
        if limit is not None:
            txs = txs[:limit]
        return txs

    def ws_subscribe_transactions(
        self, tx_filter: Dict[str, Any], options: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        spec = self.request_factory.build_transaction_subscribe_message(tx_filter, options=options)
        return spec["message"]

    async def create_webhook(self, config: WebhookConfig) -> WebhookInfo:
        return webhook_info_from_response(self._webhook)

    def verify_webhook_signature(self, headers: Dict[str, str], raw_body: bytes) -> bool:
        return True

    def next_transaction_event(self) -> TransactionStreamEvent:
        return transaction_event_from_notification(self._ws_event)

    def get_chain_features(self, token_mint: str) -> Optional[Dict[str, Any]]:
        key = _normalize_calibration_key(token_mint)
        features = self._chain_calibration.get(key)
        if features is None:
            return None
        return dict(features)

    def _load(self, name: str) -> Dict[str, Any]:
        return load_fixture(self.fixture_dir, name)

    def _load_chain_calibration(self) -> None:
        try:
            payload = self._load("chain_3token_calibration.json")
        except FileNotFoundError:
            return
        if isinstance(payload, dict):
            self._chain_calibration = payload


def get_chain_intel_provider(
    settings: Optional[HeliusSettings] = None, fixture_dir: Optional[Path] = None
) -> ChainIntelProvider:
    cfg = settings or HeliusSettings.from_env()
    if cfg.live:
        return HeliusProvider(cfg)
    return MockHeliusProvider(fixture_dir=fixture_dir)


__all__ = [
    "CircuitBreakerOpen",
    "HeliusHttpClient",
    "HeliusProvider",
    "HeliusSettings",
    "MockHeliusProvider",
    "enhanced_tx_from_helius",
    "get_chain_intel_provider",
    "transaction_event_from_notification",
    "webhook_info_from_response",
]
