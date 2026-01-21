import pytest

from app.data.birdeye.request_factory import (
    RETENTION_1S_SEC,
    SUBMINUTE_START_TS,
    BirdeyeLimitError,
    BirdeyeRequestFactory,
    BirdeyeRetentionError,
)


def test_multi_price_request_contract():
    factory = BirdeyeRequestFactory(api_key="test-key", base_url="https://public-api.birdeye.so", chain="solana")
    spec = factory.build_multi_price_request(["AAA", "BBB"])
    assert spec.method == "GET"
    assert spec.base_url == "https://public-api.birdeye.so"
    assert spec.path == "/defi/multi_price"
    assert spec.query == {"list_address": "AAA,BBB"}
    assert spec.headers == {"X-API-KEY": "test-key", "x-chain": "solana"}


def test_ohlcv_v3_request_contract():
    factory = BirdeyeRequestFactory(api_key="test-key", base_url="https://public-api.birdeye.so", chain="solana")
    spec = factory.build_ohlcv_v3_request(
        "AAA",
        "1m",
        start_ts=100,
        end_ts=200,
        limit=300,
        now_ts=SUBMINUTE_START_TS + 10,
    )
    assert spec.method == "GET"
    assert spec.path == "/defi/v3/ohlcv"
    assert spec.query == {
        "address": "AAA",
        "type": "1m",
        "time_from": 100,
        "time_to": 200,
        "count_limit": 300,
        "mode": "count",
    }
    assert spec.headers["X-API-KEY"] == "test-key"
    assert spec.headers["x-chain"] == "solana"


def test_token_overview_request_contract():
    factory = BirdeyeRequestFactory(api_key="test-key", base_url="https://public-api.birdeye.so", chain="solana")
    spec = factory.build_token_overview_request("AAA")
    assert spec.method == "GET"
    assert spec.path == "/defi/token_overview"
    assert spec.query == {"address": "AAA"}
    assert spec.headers["X-API-KEY"] == "test-key"
    assert spec.headers["x-chain"] == "solana"


def test_request_spec_fingerprints():
    factory = BirdeyeRequestFactory(api_key="test-key", base_url="https://public-api.birdeye.so", chain="solana")
    required_headers = ["X-API-KEY", "x-chain"]

    price = factory.build_price_request("AAA")
    assert (
        price.fingerprint(required_headers=required_headers)
        == "GET https://public-api.birdeye.so/defi/price q=address h=x-api-key,x-chain"
    )

    multi = factory.build_multi_price_request(["AAA", "BBB"])
    assert (
        multi.fingerprint(required_headers=required_headers)
        == "GET https://public-api.birdeye.so/defi/multi_price q=list_address h=x-api-key,x-chain"
    )

    ohlcv_v1 = factory.build_ohlcv_v1_request("AAA", "1m", start_ts=100, end_ts=200)
    assert (
        ohlcv_v1.fingerprint(required_headers=required_headers)
        == "GET https://public-api.birdeye.so/defi/ohlcv q=address,time_from,time_to,type h=x-api-key,x-chain"
    )

    ohlcv_v3 = factory.build_ohlcv_v3_request(
        "AAA",
        "1m",
        start_ts=100,
        end_ts=200,
        limit=None,
        now_ts=SUBMINUTE_START_TS + 10,
    )
    assert (
        ohlcv_v3.fingerprint(required_headers=required_headers)
        == "GET https://public-api.birdeye.so/defi/v3/ohlcv q=address,time_from,time_to,type h=x-api-key,x-chain"
    )

    overview = factory.build_token_overview_request("AAA")
    assert (
        overview.fingerprint(required_headers=required_headers)
        == "GET https://public-api.birdeye.so/defi/token_overview q=address h=x-api-key,x-chain"
    )

    trades = factory.build_trades_token_request("AAA")
    assert (
        trades.fingerprint(required_headers=required_headers)
        == "GET https://public-api.birdeye.so/defi/txs/token q=address,sort_type,tx_type h=x-api-key,x-chain"
    )


def test_multi_price_limit_enforced():
    factory = BirdeyeRequestFactory(api_key="test-key")
    with pytest.raises(BirdeyeLimitError):
        factory.build_multi_price_request([f"T{i}" for i in range(101)])


def test_ohlcv_v3_limit_enforced():
    factory = BirdeyeRequestFactory(api_key="test-key")
    with pytest.raises(BirdeyeLimitError):
        factory.build_ohlcv_v3_request(
            "AAA",
            "1m",
            start_ts=100,
            end_ts=200,
            limit=5001,
            now_ts=SUBMINUTE_START_TS + 10,
        )


def test_subminute_retention_enforced():
    factory = BirdeyeRequestFactory(api_key="test-key")
    now_ts = SUBMINUTE_START_TS + RETENTION_1S_SEC + 10
    start_ts = SUBMINUTE_START_TS + 1
    with pytest.raises(BirdeyeRetentionError):
        factory.build_ohlcv_v3_request(
            "AAA",
            "1s",
            start_ts=start_ts,
            end_ts=start_ts + 10,
            now_ts=now_ts,
        )
