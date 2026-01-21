from __future__ import annotations

from typing import Any, Dict, Optional
from urllib.parse import urlencode, urlparse, urlunparse, parse_qsl


from app.core.request_spec import JsonRpcSpec, RequestSpec


class HeliusRequestFactory:
    def __init__(
        self,
        api_key: str,
        rpc_url: str = "https://mainnet.helius-rpc.com/",
        enhanced_base: str = "https://api-mainnet.helius-rpc.com",
        ws_url: str = "wss://mainnet.helius-rpc.com/",
        rest_auth_mode: str = "query",
        rest_auth_header: str = "X-API-KEY",
        rest_auth_prefix: str = "",
    ) -> None:
        self.api_key = (api_key or "").strip()
        self.rpc_url = rpc_url.rstrip("/")
        self.enhanced_base = enhanced_base.rstrip("/")
        self.ws_url = ws_url.rstrip("/")
        self.rest_auth_mode = rest_auth_mode.strip().lower() or "query"
        self.rest_auth_header = rest_auth_header.strip() or "X-API-KEY"
        self.rest_auth_prefix = rest_auth_prefix

    def build_rpc_request(self, method: str, params: Optional[list] = None, request_id: int = 1) -> JsonRpcSpec:
        body = {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": method,
            "params": params or [],
        }
        return JsonRpcSpec(
            base_url=self.rpc_url,
            path="/",
            query={"api-key": self.api_key},
            headers={"Content-Type": "application/json"},
            body=body,
        )

    def build_enhanced_txs_request(
        self,
        address: str,
        before: Optional[str] = None,
        until: Optional[str] = None,
        tx_type: Optional[str] = None,
        source: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> RequestSpec:
        query: Dict[str, Any] = {}
        if before is not None:
            query["before"] = before
        if until is not None:
            query["until"] = until
        if tx_type is not None:
            query["type"] = tx_type
        if source is not None:
            query["source"] = source
        if limit is not None:
            query["limit"] = int(limit)
        headers: Dict[str, str] = {}
        self._apply_rest_auth(query, headers)
        return RequestSpec(
            method="GET",
            base_url=self.enhanced_base,
            path=f"/v0/addresses/{address}/transactions",
            query=query,
            headers=headers,
        )

    def build_webhook_create_request(self, config: Dict[str, Any]) -> RequestSpec:
        query: Dict[str, Any] = {}
        headers: Dict[str, str] = {"Content-Type": "application/json"}
        self._apply_rest_auth(query, headers)
        return RequestSpec(
            method="POST",
            base_url=self.enhanced_base,
            path="/v0/webhooks",
            query=query,
            headers=headers,
            json=config,
        )

    def build_transaction_subscribe_message(
        self, tx_filter: Dict[str, Any], options: Optional[Dict[str, Any]] = None, request_id: int = 1
    ) -> Dict[str, Any]:
        params = [tx_filter]
        if options is not None:
            params.append(options)
        message = {"jsonrpc": "2.0", "id": request_id, "method": "transactionSubscribe", "params": params}
        url = self._build_ws_url()
        return {"url": url, "message": message}

    def _apply_rest_auth(self, query: Dict[str, Any], headers: Dict[str, str]) -> None:
        if not self.api_key:
            return
        if self.rest_auth_mode == "header":
            value = f"{self.rest_auth_prefix}{self.api_key}"
            headers[self.rest_auth_header] = value
            return
        query["api-key"] = self.api_key

    def _build_ws_url(self) -> str:
        if not self.api_key:
            return self.ws_url
        parts = urlparse(self.ws_url)
        query = dict(parse_qsl(parts.query))
        query["api-key"] = self.api_key
        new_query = urlencode(query)
        return urlunparse((parts.scheme, parts.netloc, parts.path, parts.params, new_query, parts.fragment))


__all__ = ["HeliusRequestFactory", "JsonRpcSpec", "RequestSpec"]
