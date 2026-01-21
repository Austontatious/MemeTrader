from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field


class NativeTransfer(BaseModel):
    from_user: str
    to_user: str
    amount: int


class TokenTransfer(BaseModel):
    from_user: str
    to_user: str
    mint: str
    amount: float
    decimals: Optional[int] = None
    ui_amount: Optional[float] = None


class EnhancedTx(BaseModel):
    signature: str
    timestamp: int
    type: Optional[str] = None
    source: Optional[str] = None
    fee: Optional[int] = None
    fee_payer: Optional[str] = None
    native_transfers: List[NativeTransfer] = Field(default_factory=list)
    token_transfers: List[TokenTransfer] = Field(default_factory=list)


class TransactionStreamEvent(BaseModel):
    subscription: Optional[int] = None
    tx: EnhancedTx


class WebhookConfig(BaseModel):
    webhook_url: str
    account_addresses: List[str]
    transaction_types: List[str] = Field(default_factory=list)
    webhook_type: str = "enhanced"


class WebhookInfo(BaseModel):
    webhook_id: str
    webhook_url: str
    account_addresses: List[str] = Field(default_factory=list)
    transaction_types: List[str] = Field(default_factory=list)
    webhook_type: Optional[str] = None


__all__ = [
    "EnhancedTx",
    "NativeTransfer",
    "TokenTransfer",
    "TransactionStreamEvent",
    "WebhookConfig",
    "WebhookInfo",
]
