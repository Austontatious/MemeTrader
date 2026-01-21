from pathlib import Path

from app.core.fixtures import load_fixture
from app.data.birdeye.provider import (
    candles_from_birdeye_v3,
    price_quote_from_birdeye,
    token_overview_from_birdeye,
    trade_from_birdeye,
)
from app.data.birdeye.schemas import (
    BirdeyeMultiPriceResponse,
    BirdeyeOhlcvResponseV3,
    BirdeyePriceResponse,
    BirdeyeTokenOverviewResponse,
    BirdeyeTradesResponse,
)


FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "birdeye"


def _load_fixture(name: str) -> dict:
    return load_fixture(FIXTURE_DIR, name)


def test_multi_price_schema_and_mapping():
    payload = _load_fixture("multi_price_success.json")
    response = BirdeyeMultiPriceResponse.model_validate(payload)
    assert response.success is True
    quote = price_quote_from_birdeye(
        "So11111111111111111111111111111111111111112",
        response.data["So11111111111111111111111111111111111111112"],
    )
    assert quote.price_usd == 2.0


def test_ohlcv_v3_schema_and_mapping():
    payload = _load_fixture("ohlcv_v3_success.json")
    response = BirdeyeOhlcvResponseV3.model_validate(payload)
    candles = candles_from_birdeye_v3(response.data)
    assert len(candles) == 5
    assert candles[-1].c == 3.5
    assert candles[0].t == 1000


def test_token_overview_schema_and_mapping():
    payload = _load_fixture("token_overview_success.json")
    response = BirdeyeTokenOverviewResponse.model_validate(payload)
    overview = token_overview_from_birdeye(
        "So11111111111111111111111111111111111111112", response.data
    )
    assert overview.symbol == "TEST"
    assert overview.price_usd == 3.5


def test_trades_schema_and_mapping():
    payload = _load_fixture("txs_token_success.json")
    response = BirdeyeTradesResponse.model_validate(payload)
    trade = trade_from_birdeye("So11111111111111111111111111111111111111112", response.data.items[0])
    assert trade.side == "buy"
    assert trade.price_usd == 3.4


def test_price_timestamp_units():
    payload = _load_fixture("price_success.json")
    response = BirdeyePriceResponse.model_validate(payload)
    quote = price_quote_from_birdeye(
        "So11111111111111111111111111111111111111112", response.data
    )
    assert quote.updated_at == 1710000000


def test_birdeye_error_envelope():
    payload = _load_fixture("price_error.json")
    assert payload["success"] is False
    assert payload["message"] == "Bad request"
