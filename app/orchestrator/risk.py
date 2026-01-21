from __future__ import annotations


def estimate_slippage_bps(amount_usd: float, liquidity_usd: float) -> int:
    if liquidity_usd <= 0:
        return 10000
    impact = amount_usd / liquidity_usd
    bps = int(impact * 10000)
    return max(10, min(5000, bps))
