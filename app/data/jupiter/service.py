from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional, Protocol

from app.core.exceptions import ProviderMisconfigured
from app.data.jupiter.provider import JupiterSettings, get_jupiter_provider
from app.data.jupiter.schemas import JupiterQuoteResponse, JupiterSwapResponse


TRADING_MODE_CONFIRM = "confirm"
TRADING_MODE_AUTO = "auto"


@dataclass(frozen=True)
class QuoteParams:
    input_mint: str
    output_mint: str
    amount: int
    slippage_bps: int
    swap_mode: str = "ExactIn"
    only_direct_routes: Optional[bool] = None
    as_legacy_transaction: Optional[bool] = None
    max_accounts: Optional[int] = None
    platform_fee_bps: Optional[int] = None

    def as_dict(self) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "input_mint": self.input_mint,
            "output_mint": self.output_mint,
            "amount": int(self.amount),
            "slippage_bps": int(self.slippage_bps),
            "swap_mode": self.swap_mode,
        }
        if self.only_direct_routes is not None:
            payload["only_direct_routes"] = self.only_direct_routes
        if self.as_legacy_transaction is not None:
            payload["as_legacy_transaction"] = self.as_legacy_transaction
        if self.max_accounts is not None:
            payload["max_accounts"] = self.max_accounts
        if self.platform_fee_bps is not None:
            payload["platform_fee_bps"] = self.platform_fee_bps
        return payload


@dataclass(frozen=True)
class SwapOptions:
    wrap_and_unwrap_sol: bool = True
    dynamic_compute_unit_limit: bool = True
    prioritization_fee_lamports: Optional[int] = None
    compute_unit_price_micro_lamports: Optional[int] = None

    def as_dict(self) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "wrap_and_unwrap_sol": self.wrap_and_unwrap_sol,
            "dynamic_compute_unit_limit": self.dynamic_compute_unit_limit,
        }
        if self.prioritization_fee_lamports is not None:
            payload["prioritization_fee_lamports"] = self.prioritization_fee_lamports
        if self.compute_unit_price_micro_lamports is not None:
            payload["compute_unit_price_micro_lamports"] = self.compute_unit_price_micro_lamports
        return payload


@dataclass(frozen=True)
class ExecutionResult:
    mode: str
    status: str
    message: str
    swap_transaction: Optional[str] = None
    signature: Optional[str] = None


class ServerSigner(Protocol):
    async def sign_and_send(self, swap_transaction: str, rpc_url: str) -> str:
        ...


@dataclass(frozen=True)
class TradingModeSettings:
    trading_mode: str
    server_signer_keypair_path: str
    rpc_url: str

    @classmethod
    def from_env(cls) -> "TradingModeSettings":
        trading_mode = os.getenv("TRADING_MODE", TRADING_MODE_CONFIRM).strip().lower()
        keypair_path = os.getenv("SERVER_SIGNER_KEYPAIR_PATH", "").strip()
        rpc_url = os.getenv("SOLANA_RPC_URL", "").strip()
        if trading_mode not in {TRADING_MODE_CONFIRM, TRADING_MODE_AUTO}:
            raise ProviderMisconfigured(f"Unknown TRADING_MODE: {trading_mode}")
        if trading_mode == TRADING_MODE_AUTO:
            if not keypair_path:
                raise ProviderMisconfigured("SERVER_SIGNER_KEYPAIR_PATH is required when TRADING_MODE=auto")
            if not rpc_url:
                raise ProviderMisconfigured("SOLANA_RPC_URL is required when TRADING_MODE=auto")
        return cls(trading_mode=trading_mode, server_signer_keypair_path=keypair_path, rpc_url=rpc_url)


class ServerKeypairSigner:
    def __init__(self, keypair_path: str, simulate: bool = False) -> None:
        self.keypair_path = keypair_path
        self.simulate = simulate

    async def sign_and_send(self, swap_transaction: str, rpc_url: str) -> str:
        if self.simulate:
            digest = json.dumps({"tx": swap_transaction}, sort_keys=True).encode("utf-8")
            return f"SIMULATED_{hash(digest) & 0xFFFFFFFF:08x}"
        raise ProviderMisconfigured(
            "Server signer requires a Solana signing library; run in mock mode or add signer support."
        )

    def load_keypair(self) -> list[int]:
        path = Path(self.keypair_path)
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, list):
            raise ProviderMisconfigured("SERVER_SIGNER_KEYPAIR_PATH must point to a keypair JSON array")
        return data


class JupiterSwapService:
    def __init__(
        self,
        provider,
        trading_mode: str,
        signer: Optional[ServerSigner] = None,
        rpc_url: str = "",
    ) -> None:
        self.provider = provider
        self.trading_mode = trading_mode
        self.signer = signer
        self.rpc_url = rpc_url

    @classmethod
    def from_env(cls) -> "JupiterSwapService":
        jupiter_settings = JupiterSettings.from_env()
        trading_settings = TradingModeSettings.from_env()
        provider = get_jupiter_provider(settings=jupiter_settings)
        signer: Optional[ServerSigner] = None
        if trading_settings.trading_mode == TRADING_MODE_AUTO:
            signer = ServerKeypairSigner(
                trading_settings.server_signer_keypair_path,
                simulate=not jupiter_settings.live,
            )
        return cls(
            provider=provider,
            trading_mode=trading_settings.trading_mode,
            signer=signer,
            rpc_url=trading_settings.rpc_url,
        )

    async def get_quote(self, params: QuoteParams) -> JupiterQuoteResponse:
        return await self.provider.get_quote(params.as_dict())

    async def build_swap_tx(
        self, quote: JupiterQuoteResponse, user_pubkey: str, opts: Optional[SwapOptions] = None
    ) -> JupiterSwapResponse:
        options = opts.as_dict() if opts else {}
        quote_payload = quote.model_dump(by_alias=True)
        return await self.provider.build_swap_tx(quote_payload, user_pubkey, options)

    async def execute_swap(
        self, quote: JupiterQuoteResponse, user_pubkey: str, opts: Optional[SwapOptions] = None
    ) -> ExecutionResult:
        swap = await self.build_swap_tx(quote, user_pubkey, opts=opts)
        if self.trading_mode == TRADING_MODE_CONFIRM:
            return ExecutionResult(
                mode=TRADING_MODE_CONFIRM,
                status="needs_signature",
                message="User confirmation required",
                swap_transaction=swap.swap_transaction,
            )
        if not self.signer:
            raise ProviderMisconfigured("Server signer unavailable for auto trading mode")
        signature = await self.signer.sign_and_send(swap.swap_transaction, self.rpc_url)
        return ExecutionResult(
            mode=TRADING_MODE_AUTO,
            status="submitted",
            message="Swap signed and submitted",
            swap_transaction=swap.swap_transaction,
            signature=signature,
        )


__all__ = [
    "ExecutionResult",
    "JupiterSwapService",
    "QuoteParams",
    "SwapOptions",
    "TradingModeSettings",
    "TRADING_MODE_AUTO",
    "TRADING_MODE_CONFIRM",
]
