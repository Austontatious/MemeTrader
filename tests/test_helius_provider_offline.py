import asyncio

from app.data.chain_types import WebhookConfig
from app.data.helius.provider import MockHeliusProvider, get_chain_intel_provider


def test_offline_provider_uses_fixtures(monkeypatch):
    monkeypatch.setenv("HELIUS_LIVE", "0")
    monkeypatch.delenv("HELIUS_API_KEY", raising=False)

    provider = get_chain_intel_provider()
    assert isinstance(provider, MockHeliusProvider)

    rpc_result = asyncio.run(provider.rpc_call("getTransaction"))
    assert rpc_result["slot"] == 123456789

    txs = asyncio.run(provider.get_enhanced_txs_by_address("Trader111111111111111111111111111111"))
    assert len(txs) == 1
    assert txs[0].source == "JUPITER"

    message = provider.ws_subscribe_transactions({"accountInclude": ["Trader111111111111111111111111111111"]})
    assert message["method"] == "transactionSubscribe"

    webhook = asyncio.run(
        provider.create_webhook(
            WebhookConfig(
                webhook_url="https://example.com/helius",
                account_addresses=["Trader111111111111111111111111111111"],
                transaction_types=["SWAP"],
                webhook_type="enhanced",
            )
        )
    )
    assert webhook.webhook_id == "wh_123"
    event = provider.next_transaction_event()
    assert event.tx.signature == "5gB1LrYp"
