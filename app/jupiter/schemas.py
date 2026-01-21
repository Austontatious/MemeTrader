from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field


class JupiterSwapInfo(BaseModel):
    amm_key: str = Field(alias="ammKey")
    label: Optional[str] = None
    input_mint: str = Field(alias="inputMint")
    output_mint: str = Field(alias="outputMint")
    in_amount: str = Field(alias="inAmount")
    out_amount: str = Field(alias="outAmount")
    fee_amount: Optional[str] = Field(default=None, alias="feeAmount")
    fee_mint: Optional[str] = Field(default=None, alias="feeMint")

    model_config = ConfigDict(populate_by_name=True, extra="allow")


class JupiterRoutePlan(BaseModel):
    swap_info: JupiterSwapInfo = Field(alias="swapInfo")
    percent: int

    model_config = ConfigDict(populate_by_name=True, extra="allow")


class JupiterQuoteResponse(BaseModel):
    input_mint: str = Field(alias="inputMint")
    output_mint: str = Field(alias="outputMint")
    in_amount: str = Field(alias="inAmount")
    out_amount: str = Field(alias="outAmount")
    other_amount_threshold: str = Field(alias="otherAmountThreshold")
    swap_mode: str = Field(alias="swapMode")
    slippage_bps: int = Field(alias="slippageBps")
    price_impact_pct: str = Field(alias="priceImpactPct")
    route_plan: List[JupiterRoutePlan] = Field(alias="routePlan")
    context_slot: Optional[int] = Field(default=None, alias="contextSlot")
    time_taken: Optional[float] = Field(default=None, alias="timeTaken")

    model_config = ConfigDict(populate_by_name=True, extra="allow")


class JupiterSwapResponse(BaseModel):
    swap_transaction: str = Field(alias="swapTransaction")
    last_valid_block_height: Optional[int] = Field(default=None, alias="lastValidBlockHeight")
    prioritization_fee_lamports: Optional[int] = Field(default=None, alias="prioritizationFeeLamports")
    compute_unit_price_micro_lamports: Optional[int] = Field(
        default=None, alias="computeUnitPriceMicroLamports"
    )

    model_config = ConfigDict(populate_by_name=True, extra="allow")


__all__ = ["JupiterQuoteResponse", "JupiterSwapResponse", "JupiterRoutePlan", "JupiterSwapInfo"]
