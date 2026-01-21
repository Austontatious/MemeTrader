from __future__ import annotations

from app.data.chain_types import EnhancedTx


def compute_net_native_flow(tx: EnhancedTx, address: str) -> int:
    net = 0
    for transfer in tx.native_transfers:
        if transfer.to_user == address:
            net += transfer.amount
        if transfer.from_user == address:
            net -= transfer.amount
    return net


def compute_net_token_flow(tx: EnhancedTx, address: str, mint: str) -> float:
    net = 0.0
    for transfer in tx.token_transfers:
        if transfer.mint != mint:
            continue
        if transfer.to_user == address:
            net += transfer.amount
        if transfer.from_user == address:
            net -= transfer.amount
    return net


def compute_chain_features(txs: list[EnhancedTx], address: str, mint: str) -> dict:
    net_native = 0
    net_token = 0.0
    swap_count = 0
    liquidity_events = 0
    sources = set()
    timestamps = []

    for tx in txs:
        net_native += compute_net_native_flow(tx, address)
        net_token += compute_net_token_flow(tx, address, mint)
        if tx.type:
            if tx.type.upper() == "SWAP":
                swap_count += 1
            if tx.type.upper() in {"LIQUIDITY_ADD", "LIQUIDITY_REMOVE"}:
                liquidity_events += 1
        if tx.source:
            sources.add(tx.source)
        timestamps.append(tx.timestamp)

    tx_count = len(txs)
    velocity_per_min = 0.0
    if timestamps:
        span = max(timestamps) - min(timestamps)
        velocity_per_min = tx_count / max(span / 60.0, 1.0)

    return {
        "chain_tx_count": tx_count,
        "chain_swap_count": swap_count,
        "chain_liquidity_events": liquidity_events,
        "chain_net_native": net_native,
        "chain_net_token": net_token,
        "chain_sources": sorted(sources),
        "chain_tx_velocity_per_min": velocity_per_min,
    }
