import pytest

from app.core.exceptions import UpstreamBadResponse
from app.data.jupiter.provider import MockJupiterProvider


@pytest.mark.asyncio
async def test_mock_jupiter_provider_success():
    provider = MockJupiterProvider()
    quote = await provider.get_quote({"input_mint": "AAA", "output_mint": "BBB", "amount": 1, "slippage_bps": 10})
    assert quote.input_mint
    swap = await provider.build_swap_tx(quote.model_dump(by_alias=True), "USER123", {})
    assert swap.swap_transaction


@pytest.mark.asyncio
async def test_mock_jupiter_provider_errors():
    quote_provider = MockJupiterProvider(error_mode="quote")
    with pytest.raises(UpstreamBadResponse):
        await quote_provider.get_quote({"input_mint": "AAA", "output_mint": "BBB", "amount": 1, "slippage_bps": 10})

    swap_provider = MockJupiterProvider(error_mode="swap")
    quote = await swap_provider.get_quote({"input_mint": "AAA", "output_mint": "BBB", "amount": 1, "slippage_bps": 10})
    with pytest.raises(UpstreamBadResponse):
        await swap_provider.build_swap_tx(quote.model_dump(by_alias=True), "USER123", {})
