from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional

from app.core.request_spec import RequestSpec


class JupiterRequestError(ValueError):
    pass


@dataclass(frozen=True)
class JupiterRequestFactory:
    api_key: str = ""
    base_url: str = "https://api.jup.ag"
    quote_path: str = "/swap/v1/quote"
    swap_path: str = "/swap/v1"

    def _headers(self) -> Dict[str, str]:
        if self.api_key:
            return {"X-API-KEY": self.api_key}
        return {}

    def build_quote_request(
        self,
        input_mint: str,
        output_mint: str,
        amount: int,
        slippage_bps: int,
        swap_mode: Optional[str] = None,
        only_direct_routes: Optional[bool] = None,
        as_legacy_transaction: Optional[bool] = None,
        max_accounts: Optional[int] = None,
        platform_fee_bps: Optional[int] = None,
    ) -> RequestSpec:
        if not input_mint or not output_mint:
            raise JupiterRequestError("input_mint and output_mint are required")
        if amount <= 0:
            raise JupiterRequestError("amount must be positive")
        if slippage_bps < 0 or slippage_bps > 10_000:
            raise JupiterRequestError("slippage_bps must be between 0 and 10000")

        query: Dict[str, Any] = {
            "inputMint": input_mint,
            "outputMint": output_mint,
            "amount": int(amount),
            "slippageBps": int(slippage_bps),
        }
        if swap_mode:
            query["swapMode"] = swap_mode
        if only_direct_routes is not None:
            query["onlyDirectRoutes"] = str(only_direct_routes).lower()
        if as_legacy_transaction is not None:
            query["asLegacyTransaction"] = str(as_legacy_transaction).lower()
        if max_accounts is not None:
            query["maxAccounts"] = int(max_accounts)
        if platform_fee_bps is not None:
            query["platformFeeBps"] = int(platform_fee_bps)

        return RequestSpec(
            method="GET",
            base_url=self.base_url,
            path=self.quote_path,
            query=query,
            headers=self._headers(),
        )

    def build_swap_request(
        self,
        quote_response: Dict[str, Any],
        user_pubkey: str,
        wrap_and_unwrap_sol: bool = True,
        dynamic_compute_unit_limit: bool = True,
        prioritization_fee_lamports: Optional[int] = None,
        compute_unit_price_micro_lamports: Optional[int] = None,
    ) -> RequestSpec:
        if not isinstance(quote_response, dict):
            raise JupiterRequestError("quote_response must be a dict")
        if not user_pubkey:
            raise JupiterRequestError("user_pubkey is required")

        payload: Dict[str, Any] = {
            "quoteResponse": quote_response,
            "userPublicKey": user_pubkey,
            "wrapAndUnwrapSol": bool(wrap_and_unwrap_sol),
            "dynamicComputeUnitLimit": bool(dynamic_compute_unit_limit),
        }
        if prioritization_fee_lamports is not None:
            payload["prioritizationFeeLamports"] = int(prioritization_fee_lamports)
        if compute_unit_price_micro_lamports is not None:
            payload["computeUnitPriceMicroLamports"] = int(compute_unit_price_micro_lamports)

        return RequestSpec(
            method="POST",
            base_url=self.base_url,
            path=self.swap_path,
            query={},
            headers=self._headers(),
            json=payload,
        )


__all__ = ["JupiterRequestError", "JupiterRequestFactory"]
