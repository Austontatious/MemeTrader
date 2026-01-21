from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field


class HeliusRpcResponse(BaseModel):
    jsonrpc: str
    id: int
    result: Dict[str, Any]

    model_config = ConfigDict(extra="allow")


class HeliusNativeTransfer(BaseModel):
    from_user_account: str = Field(alias="fromUserAccount")
    to_user_account: str = Field(alias="toUserAccount")
    amount: int

    model_config = ConfigDict(populate_by_name=True, extra="allow")


class HeliusTokenAmount(BaseModel):
    amount: float
    decimals: Optional[int] = None
    ui_amount: Optional[float] = Field(default=None, alias="uiAmount")

    model_config = ConfigDict(populate_by_name=True, extra="allow")


class HeliusTokenTransfer(BaseModel):
    from_user_account: str = Field(alias="fromUserAccount")
    to_user_account: str = Field(alias="toUserAccount")
    mint: str
    token_amount: HeliusTokenAmount = Field(alias="tokenAmount")

    model_config = ConfigDict(populate_by_name=True, extra="allow")


class HeliusEnhancedTx(BaseModel):
    signature: str
    timestamp: int
    type: Optional[str] = None
    source: Optional[str] = None
    fee: Optional[int] = None
    fee_payer: Optional[str] = Field(default=None, alias="feePayer")
    native_transfers: List[HeliusNativeTransfer] = Field(default_factory=list, alias="nativeTransfers")
    token_transfers: List[HeliusTokenTransfer] = Field(default_factory=list, alias="tokenTransfers")

    model_config = ConfigDict(populate_by_name=True, extra="allow")


class HeliusTransactionNotificationParams(BaseModel):
    result: HeliusEnhancedTx
    subscription: int

    model_config = ConfigDict(populate_by_name=True, extra="allow")


class HeliusTransactionNotification(BaseModel):
    jsonrpc: str
    method: str
    params: HeliusTransactionNotificationParams

    model_config = ConfigDict(populate_by_name=True, extra="allow")


class HeliusWebhookResponse(BaseModel):
    webhook_id: str = Field(alias="webhookID")
    webhook_url: Optional[str] = Field(default=None, alias="webhookURL")
    account_addresses: List[str] = Field(default_factory=list, alias="accountAddresses")
    transaction_types: List[str] = Field(default_factory=list, alias="transactionTypes")
    webhook_type: Optional[str] = Field(default=None, alias="webhookType")

    model_config = ConfigDict(populate_by_name=True, extra="allow")


__all__ = [
    "HeliusEnhancedTx",
    "HeliusRpcResponse",
    "HeliusTokenAmount",
    "HeliusTokenTransfer",
    "HeliusNativeTransfer",
    "HeliusTransactionNotification",
    "HeliusWebhookResponse",
]
