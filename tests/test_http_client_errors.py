import asyncio

import httpx
import pytest

from app.core.exceptions import UpstreamBadResponse, UpstreamRateLimited
from app.core.request_spec import RequestSpec
from app.data.birdeye.provider import BirdeyeHttpClient
from app.data.helius.provider import HeliusHttpClient


def _make_spec() -> RequestSpec:
    return RequestSpec(
        method="GET",
        base_url="https://example.com",
        path="/test",
        query={},
        headers={},
    )


async def _run_error_case(client_cls, status_code, exc_type):
    transport = httpx.MockTransport(lambda request: httpx.Response(status_code))
    async with httpx.AsyncClient(transport=transport) as async_client:
        client = client_cls(async_client=async_client, max_retries=0)
        with pytest.raises(exc_type):
            await client.request(_make_spec())


def test_birdeye_http_client_rate_limited():
    asyncio.run(_run_error_case(BirdeyeHttpClient, 429, UpstreamRateLimited))


def test_birdeye_http_client_upstream_error():
    asyncio.run(_run_error_case(BirdeyeHttpClient, 500, UpstreamBadResponse))


def test_helius_http_client_rate_limited():
    asyncio.run(_run_error_case(HeliusHttpClient, 429, UpstreamRateLimited))


def test_helius_http_client_upstream_error():
    asyncio.run(_run_error_case(HeliusHttpClient, 500, UpstreamBadResponse))
