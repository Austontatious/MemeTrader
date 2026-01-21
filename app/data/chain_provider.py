from __future__ import annotations

from typing import Any, Dict, List, Optional, Protocol

from app.data.chain_types import EnhancedTx, WebhookConfig, WebhookInfo


class ChainIntelProvider(Protocol):
    async def rpc_call(self, method: str, params: Optional[List[Any]] = None) -> Dict[str, Any]:
        ...

    async def get_enhanced_txs_by_address(
        self,
        address: str,
        before: Optional[str] = None,
        until: Optional[str] = None,
        tx_type: Optional[str] = None,
        source: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> List[EnhancedTx]:
        ...

    def ws_subscribe_transactions(
        self, tx_filter: Dict[str, Any], options: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        ...

    async def create_webhook(self, config: WebhookConfig) -> WebhookInfo:
        ...

    def verify_webhook_signature(self, headers: Dict[str, str], raw_body: bytes) -> bool:
        ...


__all__ = ["ChainIntelProvider"]
