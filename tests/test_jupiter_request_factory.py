import pytest

from app.jupiter.request_factory import JupiterRequestError, JupiterRequestFactory


def test_quote_request_contract():
    factory = JupiterRequestFactory(api_key="test-key", base_url="https://api.jup.ag")
    spec = factory.build_quote_request(
        input_mint="So11111111111111111111111111111111111111112",
        output_mint="EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
        amount=1000,
        slippage_bps=50,
    )
    assert spec.method == "GET"
    assert spec.base_url == "https://api.jup.ag"
    assert spec.path == "/swap/v1/quote"
    assert spec.query["inputMint"]
    assert spec.query["outputMint"]
    assert spec.query["amount"] == 1000
    assert spec.query["slippageBps"] == 50
    assert spec.headers == {"X-API-KEY": "test-key"}


def test_swap_request_contract():
    factory = JupiterRequestFactory(api_key="test-key", base_url="https://api.jup.ag")
    quote = {"inputMint": "AAA", "outputMint": "BBB", "inAmount": "1", "outAmount": "2"}
    spec = factory.build_swap_request(quote, user_pubkey="USER123")
    assert spec.method == "POST"
    assert spec.path == "/swap/v1"
    assert spec.json["quoteResponse"] == quote
    assert spec.json["userPublicKey"] == "USER123"
    assert spec.json["wrapAndUnwrapSol"] is True
    assert spec.json["dynamicComputeUnitLimit"] is True
    assert spec.headers["X-API-KEY"] == "test-key"


def test_request_spec_fingerprint():
    factory = JupiterRequestFactory(api_key="test-key", base_url="https://api.jup.ag")
    quote = factory.build_quote_request("AAA", "BBB", amount=1, slippage_bps=10)
    assert (
        quote.fingerprint(required_headers=["X-API-KEY"])
        == "GET https://api.jup.ag/swap/v1/quote q=amount,inputMint,outputMint,slippageBps h=x-api-key"
    )

    swap = factory.build_swap_request({"inputMint": "AAA", "outputMint": "BBB", "inAmount": "1"}, "USER")
    assert (
        swap.fingerprint(required_headers=["X-API-KEY"])
        == "POST https://api.jup.ag/swap/v1 q= h=x-api-key"
    )


def test_quote_request_validation():
    factory = JupiterRequestFactory()
    with pytest.raises(JupiterRequestError):
        factory.build_quote_request("", "BBB", amount=1, slippage_bps=10)
    with pytest.raises(JupiterRequestError):
        factory.build_quote_request("AAA", "BBB", amount=0, slippage_bps=10)
    with pytest.raises(JupiterRequestError):
        factory.build_quote_request("AAA", "BBB", amount=1, slippage_bps=-1)
