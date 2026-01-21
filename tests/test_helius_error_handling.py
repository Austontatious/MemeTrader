import asyncio

import pytest

from app.core.exceptions import UpstreamBadResponse
from app.data.helius.provider import HeliusProvider, HeliusSettings


class DummyClient:
    async def request(self, spec):
        return {"jsonrpc": "2.0", "id": 1, "error": {"code": -32005, "message": "Rate limit"}}


def test_helius_rpc_error_envelope_raises():
    provider = HeliusProvider(
        HeliusSettings(
            api_key="test",
            rpc_url="https://mainnet.helius-rpc.com/",
            enhanced_base="https://api-mainnet.helius-rpc.com",
            ws_url="wss://mainnet.helius-rpc.com/",
            rest_auth_mode="query",
            rest_auth_header="X-API-KEY",
            rest_auth_prefix="",
            webhook_secret="",
            webhook_signature_header="x-helius-signature",
            live=True,
        ),
        http_client=DummyClient(),
    )
    with pytest.raises(UpstreamBadResponse):
        asyncio.run(provider.rpc_call("getTransaction"))
