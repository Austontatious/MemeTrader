import asyncio

import pytest

from app.core.exceptions import UpstreamBadResponse
from app.data.birdeye.provider import BirdeyeProvider, BirdeyeSettings


class DummyClient:
    async def request(self, spec):
        return {"success": False, "message": "Bad request"}


def test_birdeye_error_envelope_raises():
    provider = BirdeyeProvider(
        BirdeyeSettings(api_key="test", chain="solana", base_url="https://public-api.birdeye.so", live=True),
        http_client=DummyClient(),
    )
    with pytest.raises(UpstreamBadResponse):
        asyncio.run(provider.get_spot_price("So11111111111111111111111111111111111111112"))
