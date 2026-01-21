from __future__ import annotations

from typing import Dict, List

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from mock_api.data_seed import generate_seed

app = FastAPI()
seed = generate_seed()

app.state.seed = seed
app.state.metrics = {
    "dex_candidates": 0,
    "dex_pair": 0,
    "birdeye_ohlcv": 0,
    "jupiter_quote": 0,
    "jupiter_build": 0,
}


def reset_metrics() -> None:
    app.state.metrics = {
        "dex_candidates": 0,
        "dex_pair": 0,
        "birdeye_ohlcv": 0,
        "jupiter_quote": 0,
        "jupiter_build": 0,
    }


class QuoteRequest(BaseModel):
    token_in: str
    token_out: str
    amount_in: float
    slippage_bps: int


class BuildSwapRequest(BaseModel):
    quote: Dict
    user_pubkey: str


def _get_token_price(token_mint: str) -> float:
    for pair in seed["pairs"].values():
        if pair["token_mint"] == token_mint:
            return float(pair["price_usd"])
    raise KeyError(token_mint)


def _get_token_liquidity(token_mint: str) -> float:
    for pair in seed["pairs"].values():
        if pair["token_mint"] == token_mint:
            return float(pair["liquidity_usd"])
    raise KeyError(token_mint)


@app.get("/dex/candidates")
async def dex_candidates() -> List[Dict[str, str]]:
    app.state.metrics["dex_candidates"] += 1
    return seed["tokens"]


@app.get("/dex/pair/{pair_id}")
async def dex_pair(pair_id: str) -> Dict:
    app.state.metrics["dex_pair"] += 1
    pair = seed["pairs"].get(pair_id)
    if not pair:
        raise HTTPException(status_code=404, detail="Pair not found")
    return pair


@app.get("/birdeye/ohlcv/{token_mint}")
async def birdeye_ohlcv(token_mint: str, tf: str = "1m", limit: int = 300) -> List[Dict]:
    app.state.metrics["birdeye_ohlcv"] += 1
    candles = seed["candles"].get(token_mint)
    if candles is None:
        raise HTTPException(status_code=404, detail="Token not found")
    limit = max(1, min(limit, len(candles)))
    return candles[-limit:]


@app.post("/jupiter/quote")
async def jupiter_quote(request: QuoteRequest) -> Dict:
    app.state.metrics["jupiter_quote"] += 1
    token_in = request.token_in
    token_out = request.token_out
    amount_in = float(request.amount_in)

    if amount_in <= 0:
        raise HTTPException(status_code=400, detail="amount_in must be positive")

    try:
        if token_in in {"USDC", "USDT"} and token_out not in {"USDC", "USDT"}:
            price = _get_token_price(token_out)
            amount_out = amount_in / price
            liquidity = _get_token_liquidity(token_out)
        elif token_out in {"USDC", "USDT"} and token_in not in {"USDC", "USDT"}:
            price = _get_token_price(token_in)
            amount_out = amount_in * price
            liquidity = _get_token_liquidity(token_in)
        else:
            price_in = _get_token_price(token_in)
            price_out = _get_token_price(token_out)
            amount_out = amount_in * (price_in / price_out)
            liquidity = min(_get_token_liquidity(token_in), _get_token_liquidity(token_out))
    except KeyError:
        raise HTTPException(status_code=404, detail="Unknown token")

    price_impact_pct = min(10.0, (amount_in / max(liquidity, 1.0)) * 100.0)
    min_out = amount_out * (1.0 - (request.slippage_bps / 10000.0))

    return {
        "token_in": token_in,
        "token_out": token_out,
        "amount_in": amount_in,
        "amount_out": amount_out,
        "min_out": min_out,
        "price_impact_pct": price_impact_pct,
        "slippage_bps": request.slippage_bps,
    }


@app.post("/jupiter/build_swap_tx")
async def jupiter_build_swap_tx(request: BuildSwapRequest) -> Dict:
    app.state.metrics["jupiter_build"] += 1
    return {
        "serialized_tx_base64": "AAAAFAKEBASE64TX==",
        "quote": request.quote,
        "user_pubkey": request.user_pubkey,
    }
