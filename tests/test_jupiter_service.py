import pytest

from app.data.jupiter.provider import MockJupiterProvider
from app.data.jupiter.service import (
    ExecutionResult,
    JupiterSwapService,
    QuoteParams,
    SwapOptions,
    TRADING_MODE_AUTO,
    TRADING_MODE_CONFIRM,
)


@pytest.mark.asyncio
async def test_swap_service_confirm_mode():
    provider = MockJupiterProvider()
    service = JupiterSwapService(provider=provider, trading_mode=TRADING_MODE_CONFIRM)
    quote = await service.get_quote(
        QuoteParams(
            input_mint="So11111111111111111111111111111111111111112",
            output_mint="EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
            amount=1000,
            slippage_bps=50,
        )
    )
    result = await service.execute_swap(quote, user_pubkey="USER123", opts=SwapOptions())
    assert isinstance(result, ExecutionResult)
    assert result.status == "needs_signature"
    assert result.swap_transaction


@pytest.mark.asyncio
async def test_swap_service_auto_mode_simulated():
    provider = MockJupiterProvider()
    service = JupiterSwapService(
        provider=provider,
        trading_mode=TRADING_MODE_AUTO,
        signer=None,
        rpc_url="http://localhost:8899",
    )
    quote = await service.get_quote(
        QuoteParams(
            input_mint="So11111111111111111111111111111111111111112",
            output_mint="EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
            amount=1000,
            slippage_bps=50,
        )
    )
    async def _sign_and_send(self, tx, url):
        return f"SIMULATED_{hash(tx) & 0xFFFF:04x}"

    service.signer = type("SimSigner", (), {"sign_and_send": _sign_and_send})()
    result = await service.execute_swap(quote, user_pubkey="USER123", opts=SwapOptions())
    assert result.status == "submitted"
    assert result.signature
