from pathlib import Path

from app.core.fixtures import load_fixture
from app.data.helius.features import compute_net_native_flow, compute_net_token_flow
from app.data.helius.provider import (
    enhanced_tx_from_helius,
    transaction_event_from_notification,
    webhook_info_from_response,
)
from app.data.helius.schemas import (
    HeliusEnhancedTx,
    HeliusRpcResponse,
    HeliusTransactionNotification,
    HeliusWebhookResponse,
)


FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "helius"


def _load_fixture(name: str) -> object:
    return load_fixture(FIXTURE_DIR, name)


def test_rpc_response_schema():
    payload = _load_fixture("rpc_getTransaction_success.json")
    response = HeliusRpcResponse.model_validate(payload)
    assert response.result["slot"] == 123456789


def test_rpc_error_envelope_fixture():
    payload = _load_fixture("rpc_error.json")
    assert payload["error"]["message"] == "Rate limit"


def test_enhanced_txs_schema_and_features():
    payload = _load_fixture("enhanced_address_txs_success.json")
    tx = HeliusEnhancedTx.model_validate(payload[0])
    mapped = enhanced_tx_from_helius(tx)
    assert mapped.signature == "5gB1LrYp"

    trader = "Trader111111111111111111111111111111"
    net_sol = compute_net_native_flow(mapped, trader)
    net_token = compute_net_token_flow(mapped, trader, "So11111111111111111111111111111111111111112")
    assert net_sol == -100000000
    assert net_token == 250.0


def test_transaction_notification_schema():
    payload = _load_fixture("transaction_subscribe_event.json")
    event = HeliusTransactionNotification.model_validate(payload)
    mapped = transaction_event_from_notification(event)
    assert mapped.subscription == 1
    assert mapped.tx.signature == "5gB1LrYp"


def test_webhook_response_schema():
    payload = _load_fixture("create_webhook_response.json")
    response = HeliusWebhookResponse.model_validate(payload)
    info = webhook_info_from_response(response)
    assert info.webhook_id == "wh_123"
    assert info.webhook_url == "https://example.com/helius"
