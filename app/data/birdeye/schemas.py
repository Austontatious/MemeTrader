from __future__ import annotations

from typing import Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field


class BirdeyePriceData(BaseModel):
    value: float
    update_unix_time: int = Field(alias="updateUnixTime")
    update_human_time: str = Field(alias="updateHumanTime")
    price_change_24h: float = Field(alias="priceChange24h")
    price_in_native: Optional[float] = Field(default=None, alias="priceInNative")
    liquidity: Optional[float] = None
    is_scaled_ui_token: Optional[bool] = Field(default=None, alias="isScaledUiToken")
    scaled_value: Optional[float] = Field(default=None, alias="scaledValue")
    multiplier: Optional[float] = None
    scaled_price_in_native: Optional[float] = Field(default=None, alias="scaledPriceInNative")

    model_config = ConfigDict(populate_by_name=True, extra="allow")


class BirdeyePriceResponse(BaseModel):
    success: bool
    data: BirdeyePriceData


class BirdeyeMultiPriceResponse(BaseModel):
    success: bool
    data: Dict[str, BirdeyePriceData]


class BirdeyeOhlcvItemV1(BaseModel):
    o: float
    h: float
    l: float
    c: float
    v: float
    address: str
    interval: str = Field(alias="type")
    unix_time: int = Field(alias="unixTime")
    currency: str
    scaled_o: Optional[float] = Field(default=None, alias="scaledO")
    scaled_h: Optional[float] = Field(default=None, alias="scaledH")
    scaled_l: Optional[float] = Field(default=None, alias="scaledL")
    scaled_c: Optional[float] = Field(default=None, alias="scaledC")
    scaled_v: Optional[float] = Field(default=None, alias="scaledV")

    model_config = ConfigDict(populate_by_name=True, extra="allow")


class BirdeyeOhlcvDataV1(BaseModel):
    is_scaled_ui_token: Optional[bool] = Field(default=None, alias="isScaledUiToken")
    multiplier: Optional[float] = None
    items: List[BirdeyeOhlcvItemV1]

    model_config = ConfigDict(populate_by_name=True, extra="allow")


class BirdeyeOhlcvResponseV1(BaseModel):
    success: bool
    data: BirdeyeOhlcvDataV1


class BirdeyeOhlcvItemV3(BaseModel):
    o: float
    h: float
    l: float
    c: float
    v: float
    v_usd: float = Field(alias="v_usd")
    address: str
    interval: str = Field(alias="type")
    unix_time: int = Field(alias="unix_time")
    currency: str
    scaled_o: Optional[float] = Field(default=None, alias="scaled_o")
    scaled_h: Optional[float] = Field(default=None, alias="scaled_h")
    scaled_l: Optional[float] = Field(default=None, alias="scaled_l")
    scaled_c: Optional[float] = Field(default=None, alias="scaled_c")
    scaled_v: Optional[float] = Field(default=None, alias="scaled_v")

    model_config = ConfigDict(populate_by_name=True, extra="allow")


class BirdeyeOhlcvDataV3(BaseModel):
    is_scaled_ui_token: Optional[bool] = Field(default=None, alias="is_scaled_ui_token")
    multiplier: Optional[float] = None
    items: List[BirdeyeOhlcvItemV3]

    model_config = ConfigDict(populate_by_name=True, extra="allow")


class BirdeyeOhlcvResponseV3(BaseModel):
    success: bool
    data: BirdeyeOhlcvDataV3


class BirdeyeTokenOverviewData(BaseModel):
    address: Optional[str] = None
    symbol: Optional[str] = None
    name: Optional[str] = None
    price: Optional[float] = None
    liquidity: Optional[float] = None
    volume_24h: Optional[float] = Field(default=None, alias="volume24h")
    trade_24h: Optional[float] = Field(default=None, alias="trade24h")
    market_cap: Optional[float] = Field(default=None, alias="marketCap")
    fdv: Optional[float] = None
    last_trade_unix_time: Optional[int] = Field(default=None, alias="lastTradeUnixTime")

    model_config = ConfigDict(populate_by_name=True, extra="allow")


class BirdeyeTokenOverviewResponse(BaseModel):
    success: bool
    data: BirdeyeTokenOverviewData


class BirdeyeTradeItem(BaseModel):
    tx_hash: Optional[str] = Field(default=None, alias="txHash")
    side: Optional[str] = None
    price: Optional[float] = None
    size: Optional[float] = None
    volume_usd: Optional[float] = Field(default=None, alias="volumeUSD")
    block_unix_time: Optional[int] = Field(default=None, alias="blockUnixTime")

    model_config = ConfigDict(populate_by_name=True, extra="allow")


class BirdeyeTradesData(BaseModel):
    items: List[BirdeyeTradeItem]
    has_next: bool = Field(alias="hasNext")

    model_config = ConfigDict(populate_by_name=True, extra="allow")


class BirdeyeTradesResponse(BaseModel):
    success: bool
    data: BirdeyeTradesData
