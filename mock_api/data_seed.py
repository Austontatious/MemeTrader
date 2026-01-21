from __future__ import annotations

import random
from typing import Dict, List


def _generate_candles(
    rng: random.Random,
    base_price: float,
    start_ts: int,
    interval_sec: int,
    candle_count: int,
) -> List[Dict[str, float]]:
    candles: List[Dict[str, float]] = []
    price = base_price

    for i in range(candle_count):
        if i < 60:
            drift = rng.uniform(-0.002, 0.002)
        elif i < 120:
            drift = 0.002 + rng.uniform(-0.001, 0.001)
        elif i < 180:
            drift = 0.003 + rng.uniform(-0.001, 0.001)
            if i == 140:
                drift = 0.08
        elif i < 240:
            drift = -0.005 + rng.uniform(-0.002, 0.0)
            if i == 220:
                drift = -0.15
        else:
            drift = 0.001 + rng.uniform(-0.001, 0.001)

        price = max(0.01, price * (1.0 + drift))
        open_price = candles[-1]["c"] if candles else price
        high = max(open_price, price) * (1.0 + rng.uniform(0.001, 0.01))
        low = min(open_price, price) * (1.0 - rng.uniform(0.001, 0.01))
        volume = 1000.0 + rng.uniform(0, 500)
        if i in (140, 141):
            volume = 8000.0 + rng.uniform(0, 2000)
        if i in (220, 221):
            volume = 6000.0 + rng.uniform(0, 1500)

        candles.append(
            {
                "t": int(start_ts + i * interval_sec),
                "o": float(open_price),
                "h": float(high),
                "l": float(low),
                "c": float(price),
                "v": float(volume),
            }
        )

    return candles


def _calibration_tokens() -> List[Dict[str, object]]:
    return [
        {
            "symbol": "WIN_PERFECT",
            "token_mint": "MINT_WIN_PERFECT",
            "pair_id": "PAIR_WIN_PERFECT",
            "candles": [
                {"t": 1700000000, "o": 1.00, "h": 1.02, "l": 0.99, "c": 1.01, "v": 120},
                {"t": 1700000060, "o": 1.01, "h": 1.03, "l": 1.00, "c": 1.02, "v": 130},
                {"t": 1700000120, "o": 1.02, "h": 1.05, "l": 1.01, "c": 1.04, "v": 160},
                {"t": 1700000180, "o": 1.04, "h": 1.12, "l": 1.03, "c": 1.10, "v": 200},
                {"t": 1700000240, "o": 1.10, "h": 1.20, "l": 1.09, "c": 1.18, "v": 700},
                {"t": 1700000300, "o": 1.18, "h": 1.28, "l": 1.16, "c": 1.25, "v": 610},
                {"t": 1700000360, "o": 1.25, "h": 1.35, "l": 1.24, "c": 1.33, "v": 740},
                {"t": 1700000420, "o": 1.33, "h": 1.45, "l": 1.31, "c": 1.40, "v": 860},
            ],
        },
        {
            "symbol": "WIN_COMPLEX",
            "token_mint": "MINT_WIN_COMPLEX",
            "pair_id": "PAIR_WIN_COMPLEX",
            "candles": [
                {"t": 1700000000, "o": 1.00, "h": 1.01, "l": 0.97, "c": 0.98, "v": 140},
                {"t": 1700000060, "o": 0.98, "h": 1.00, "l": 0.96, "c": 0.99, "v": 150},
                {"t": 1700000120, "o": 0.99, "h": 1.00, "l": 0.98, "c": 0.995, "v": 110},
                {"t": 1700000180, "o": 0.995, "h": 1.005, "l": 0.99, "c": 1.000, "v": 105},
                {"t": 1700000240, "o": 1.000, "h": 1.015, "l": 0.995, "c": 1.010, "v": 180},
                {"t": 1700000300, "o": 1.010, "h": 1.030, "l": 1.005, "c": 1.020, "v": 240},
                {"t": 1700000360, "o": 1.020, "h": 1.025, "l": 1.000, "c": 1.005, "v": 210},
                {"t": 1700000420, "o": 1.005, "h": 1.050, "l": 1.002, "c": 1.045, "v": 420},
            ],
        },
        {
            "symbol": "FAKE_HEADFAKE",
            "token_mint": "MINT_FAKE_HEADFAKE",
            "pair_id": "PAIR_FAKE_HEADFAKE",
            "candles": [
                {"t": 1700000000, "o": 1.00, "h": 1.02, "l": 0.99, "c": 1.01, "v": 120},
                {"t": 1700000060, "o": 1.01, "h": 1.08, "l": 1.00, "c": 1.07, "v": 900},
                {"t": 1700000120, "o": 1.07, "h": 1.10, "l": 0.92, "c": 0.95, "v": 1100},
                {"t": 1700000180, "o": 0.95, "h": 0.98, "l": 0.80, "c": 0.82, "v": 800},
                {"t": 1700000240, "o": 0.82, "h": 0.85, "l": 0.78, "c": 0.80, "v": 300},
            ],
        },
    ]


def generate_seed(
    num_tokens: int = 10,
    candle_count: int = 300,
    start_ts: int = 1700000000,
    interval_sec: int = 60,
) -> Dict[str, object]:
    tokens: List[Dict[str, str]] = []
    pairs: Dict[str, Dict[str, object]] = {}
    candles_by_token: Dict[str, List[Dict[str, float]]] = {}

    calibration = _calibration_tokens()
    for entry in calibration:
        token_mint = entry["token_mint"]
        pair_id = entry["pair_id"]
        symbol = entry["symbol"]
        candles = entry["candles"]
        candles_by_token[token_mint] = candles

        last_price = candles[-1]["c"]
        volume_5m = sum(c["v"] for c in candles[-5:])
        pairs[pair_id] = {
            "pair_id": pair_id,
            "token_mint": token_mint,
            "price_usd": float(last_price),
            "liquidity_usd": float(150000.0),
            "volume_5m": float(volume_5m),
            "txns_5m": int(volume_5m / 100),
        }
        tokens.append({"pair_id": pair_id, "token_mint": token_mint, "symbol": symbol})

    remaining = max(0, num_tokens - len(calibration))
    for idx in range(remaining):
        token_mint = f"TOKEN{idx:02d}"
        pair_id = f"PAIR{idx:02d}"
        symbol = f"MEME{idx:02d}"
        rng = random.Random(1000 + idx)
        base_price = 0.5 + (idx * 0.12)

        candles = _generate_candles(rng, base_price, start_ts, interval_sec, candle_count)
        candles_by_token[token_mint] = candles

        last_price = candles[-1]["c"]
        volume_5m = sum(c["v"] for c in candles[-5:])

        pairs[pair_id] = {
            "pair_id": pair_id,
            "token_mint": token_mint,
            "price_usd": float(last_price),
            "liquidity_usd": float(50000 + idx * 5000),
            "volume_5m": float(volume_5m),
            "txns_5m": int(volume_5m / 100),
        }

        tokens.append({"pair_id": pair_id, "token_mint": token_mint, "symbol": symbol})

    return {
        "tokens": tokens,
        "pairs": pairs,
        "candles": candles_by_token,
        "token_index": {t["token_mint"]: t for t in tokens},
    }
