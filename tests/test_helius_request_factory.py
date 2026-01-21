from app.data.helius.request_factory import HeliusRequestFactory


def test_rpc_request_contract():
    factory = HeliusRequestFactory(api_key="test-key", rpc_url="https://mainnet.helius-rpc.com/")
    spec = factory.build_rpc_request("getLatestBlockhash", params=[{"commitment": "processed"}], request_id=7)
    request_spec = spec.to_request_spec()
    assert request_spec.method == "POST"
    assert request_spec.base_url == "https://mainnet.helius-rpc.com"
    assert request_spec.path == "/"
    assert request_spec.query == {"api-key": "test-key"}
    assert request_spec.headers["Content-Type"] == "application/json"
    assert spec.body == {
        "jsonrpc": "2.0",
        "id": 7,
        "method": "getLatestBlockhash",
        "params": [{"commitment": "processed"}],
    }
    assert spec.canonical_payload() == (
        "{\"id\":7,\"jsonrpc\":\"2.0\",\"method\":\"getLatestBlockhash\",\"params\":[{\"commitment\":\"processed\"}]}"
    )


def test_enhanced_txs_request_contract():
    factory = HeliusRequestFactory(api_key="test-key", enhanced_base="https://api-mainnet.helius-rpc.com")
    spec = factory.build_enhanced_txs_request(
        address="Trader111111111111111111111111111111",
        before="sig_before",
        until="sig_until",
        tx_type="SWAP",
        source="JUPITER",
        limit=50,
    )
    assert spec.method == "GET"
    assert spec.base_url == "https://api-mainnet.helius-rpc.com"
    assert spec.path == "/v0/addresses/Trader111111111111111111111111111111/transactions"
    assert spec.query == {
        "before": "sig_before",
        "until": "sig_until",
        "type": "SWAP",
        "source": "JUPITER",
        "limit": 50,
        "api-key": "test-key",
    }


def test_transaction_subscribe_message_contract():
    factory = HeliusRequestFactory(api_key="test-key", ws_url="wss://mainnet.helius-rpc.com/")
    spec = factory.build_transaction_subscribe_message(
        tx_filter={"accountInclude": ["Trader111111111111111111111111111111"]},
        options={"commitment": "processed"},
        request_id=99,
    )
    assert spec["message"]["jsonrpc"] == "2.0"
    assert spec["message"]["id"] == 99
    assert spec["message"]["method"] == "transactionSubscribe"
    assert spec["message"]["params"] == [
        {"accountInclude": ["Trader111111111111111111111111111111"]},
        {"commitment": "processed"},
    ]
    assert "api-key=test-key" in spec["url"]


def test_webhook_create_request_contract():
    factory = HeliusRequestFactory(api_key="test-key", enhanced_base="https://api-mainnet.helius-rpc.com")
    body = {
        "webhookURL": "https://example.com/helius",
        "accountAddresses": ["Trader111111111111111111111111111111"],
        "transactionTypes": ["SWAP"],
        "webhookType": "enhanced",
    }
    spec = factory.build_webhook_create_request(body)
    assert spec.method == "POST"
    assert spec.path == "/v0/webhooks"
    assert spec.base_url == "https://api-mainnet.helius-rpc.com"
    assert spec.json == body
    assert spec.query == {"api-key": "test-key"}
