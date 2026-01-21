from __future__ import annotations

import asyncio
import json
import time
from collections import Counter
from datetime import datetime, timezone
from contextlib import AsyncExitStack
from inspect import isawaitable
from math import log1p, sqrt
from pathlib import Path
from statistics import median
from typing import Dict, Optional

from app.config import get_config
from app.data.client import MockApiClient
from app.data.chain_provider import ChainIntelProvider
from app.data.helius.features import compute_chain_features
from app.data.helius.provider import MockHeliusProvider
from app.data.market_provider import MarketDataProvider
from app.data.birdeye.provider import MockProvider as MockMarketProvider
from app.data.jupiter.service import JupiterSwapService, QuoteParams, SwapOptions
from app.orchestrator.snapshot import build_snapshot
from app.orchestrator.state_machine import TokenState, advance_time, apply_action
from app.orchestrator.trade_log import TradeLogger
from app.orchestrator.validator import validate_action
from app.policies.base import (
    ACTION_ADD_BUY,
    ACTION_EXIT_FULL,
    ACTION_HOLD,
    ACTION_PROBE_BUY,
    ACTION_SCALE_OUT_20,
)
from app.policies.rules_v0 import propose_action


def _action_notional_usd(action: str, state: TokenState, config: dict) -> float:
    positioning = config.get("positioning", {})
    capital = float(positioning.get("capital_usd", 0.0))
    if action == ACTION_PROBE_BUY:
        return capital * float(positioning.get("probe_pct", 0.0))
    if action == ACTION_ADD_BUY:
        return capital * float(positioning.get("add_pct", 0.0))
    if action == ACTION_SCALE_OUT_20:
        if state.scale_out_stage == 0:
            scale_pct = float(positioning.get("tp1_scale_out_pct", 0.0))
        else:
            scale_pct = float(positioning.get("tp2_scale_out_pct", 0.0))
        return state.position_usd * scale_pct
    if action == ACTION_EXIT_FULL:
        return state.position_usd
    return 0.0


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def write_jsonl(path: Path, records: list[Dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record) + "\n")


def write_json(path: Path, obj: Dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, sort_keys=True), encoding="utf-8")


def _rank_entry_proposals(proposals: list, config: dict) -> None:
    rules_cfg = config.get("rules", {})
    top_n = int(rules_cfg.get("top_n_per_tick", 0))
    min_candidates = int(rules_cfg.get("min_candidates_before_rank", 0))
    lookback = int(rules_cfg.get("momentum_lookback", 20))

    entries = [p for p in proposals if p["proposal"].action == ACTION_PROBE_BUY]
    if top_n <= 0 or len(entries) < max(1, min_candidates):
        return

    for entry in entries:
        score_detail = _momentum_score_detail(entry["snapshot"].candles, lookback)
        raw_score = float(score_detail["total"])
        adjusted, adjustments = _apply_score_adjustments(raw_score, entry["snapshot"].features, config)
        entry["momentum_score"] = adjusted
        entry["score_adjustments"] = adjustments

    entries.sort(key=lambda p: p.get("momentum_score", 0.0), reverse=True)
    for entry in entries[top_n:]:
        proposal = entry["proposal"]
        entry["proposal"] = proposal.model_copy(
            update={"action": ACTION_HOLD, "reason_codes": proposal.reason_codes + ["RANKED_OUT"]}
        )


def _build_ranked_summary(proposals: list, config: dict) -> list[Dict[str, object]]:
    ranked = []
    for entry in proposals:
        score = _score_for_entry(entry, config)
        snapshot = entry["snapshot"]
        features = snapshot.features
        ranked.append(
            {
                "symbol": entry.get("symbol") or entry.get("token_mint"),
                "token_mint": entry.get("token_mint"),
                "pair_id": entry.get("pair").pair_id if entry.get("pair") else None,
                "momentum_score": float(score),
                "last_close": float(snapshot.last_close),
                "score_components": {
                    "breakout": bool(features.get("breakout")),
                    "return_pct": float(features.get("return_pct", 0.0)),
                    "volume_accel": float(features.get("volume_accel", 0.0)),
                    "range_ratio": float(features.get("range_ratio", 1.0)),
                },
            }
        )
    ranked.sort(key=lambda item: item["momentum_score"], reverse=True)
    top_n = int(config.get("rules", {}).get("top_n_per_tick", 0))
    if top_n <= 0:
        top_n = 5
    return ranked[: min(top_n, len(ranked))]


def _build_ranked_from_decisions(decisions: list[Dict[str, object]], config: dict) -> list[Dict[str, object]]:
    if not decisions:
        return []
    top_n = int(config.get("rules", {}).get("top_n_per_tick", 0))
    if top_n <= 0:
        top_n = 5
    ranked = sorted(decisions, key=lambda item: float(item.get("score", 0.0)), reverse=True)
    entries = []
    for record in ranked[:top_n]:
        entries.append(
            {
                "symbol": record.get("symbol"),
                "token_mint": record.get("token_mint"),
                "pair_id": record.get("pair_id"),
                "momentum_score": float(record.get("score", 0.0)),
                "last_close": float(record.get("last_close", 0.0)),
                "score_components": {},
            }
        )
    return entries


def _score_for_entry(entry: Dict[str, object], config: dict) -> float:
    score = entry.get("momentum_score")
    if score is not None:
        return float(score)
    lookback = int(config.get("rules", {}).get("momentum_lookback", 20))
    snapshot = entry["snapshot"]
    score_detail = _momentum_score_detail(snapshot.candles, lookback)
    adjusted, _ = _apply_score_adjustments(float(score_detail["total"]), snapshot.features, config)
    return float(adjusted)


def _compact_features(features: Optional[Dict[str, object]], keep: int = 12) -> Optional[Dict[str, object]]:
    if not isinstance(features, dict):
        return features
    compact: Dict[str, object] = {}
    for key in sorted(features.keys())[:keep]:
        compact[key] = features[key]
    return compact


def _candle_value(candle: object, key: str) -> float:
    if hasattr(candle, key):
        return float(getattr(candle, key))
    return float(candle[key])


def _momentum_score_detail(candles: list, lookback: int) -> Dict[str, object]:
    if lookback <= 0:
        return {"total": 0.0, "components": [], "top_features": []}
    if len(candles) < lookback + 1:
        lookback = max(1, len(candles) - 1)
    if len(candles) < lookback + 1:
        return {"total": 0.0, "components": [], "top_features": []}

    window = candles[-(lookback + 1) :]
    close_now = _candle_value(window[-1], "c")
    close_then = _candle_value(window[0], "c")
    if close_then <= 0:
        return {"total": 0.0, "components": [], "top_features": []}

    ret = (close_now / close_then) - 1.0
    vols = [_candle_value(c, "v") for c in window[:-1]]
    median_vol = median(vols) if vols else 0.0
    vol_mult = (vols[-1] / median_vol) if median_vol > 0 else 1.0

    ranges = []
    for c in window[:-1]:
        close_val = _candle_value(c, "c")
        if close_val <= 0:
            continue
        ranges.append((_candle_value(c, "h") - _candle_value(c, "l")) / close_val)
    median_range = median(ranges) if ranges else 0.0
    range_now = (_candle_value(window[-1], "h") - _candle_value(window[-1], "l")) / max(close_now, 1e-9)
    range_mult = (range_now / median_range) if median_range > 0 else 1.0

    return_contrib = 100.0 * ret
    volume_contrib = 10.0 * log1p(max(0.0, vol_mult - 1.0)) if median_vol > 0 else 0.0
    range_contrib = 5.0 * log1p(max(0.0, range_mult - 1.0)) if median_range > 0 else 0.0

    components = [
        {"feature": "return_pct", "contribution": return_contrib, "value": ret},
        {"feature": "volume_mult", "contribution": volume_contrib, "value": vol_mult},
        {"feature": "range_mult", "contribution": range_contrib, "value": range_mult},
    ]
    components.sort(key=lambda item: abs(float(item.get("contribution", 0.0))), reverse=True)
    total = return_contrib + volume_contrib + range_contrib
    top_features = [item["feature"] for item in components[:2]]

    return {"total": float(total), "components": components, "top_features": top_features}


def _safe_float(value: object) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _candidate_reject_counts(decisions: list[Dict[str, object]]) -> Counter[str]:
    counts: Counter[str] = Counter()
    for record in decisions:
        if record.get("decision") != ACTION_HOLD:
            continue
        reasons = record.get("reasons") or []
        if not isinstance(reasons, list):
            continue
        unique = {reason for reason in reasons if isinstance(reason, str)}
        counts.update(unique)
    return counts


def _candidate_reason_counts(decisions: list[Dict[str, object]]) -> Counter[str]:
    counts: Counter[str] = Counter()
    for record in decisions:
        reasons = record.get("reasons") or []
        if not isinstance(reasons, list):
            continue
        unique = {reason for reason in reasons if isinstance(reason, str)}
        counts.update(unique)
    return counts


def _apply_score_adjustments(score: float, features: Dict[str, object], config: dict) -> tuple[float, list]:
    breakout_cfg = config.get("breakout", {})
    bonus = float(breakout_cfg.get("chain_override_score_bonus", 0.0))
    penalty = float(breakout_cfg.get("weak_breakout_score_penalty", 0.0))
    adjustments = []

    if features.get("chain_override"):
        score += bonus
        adjustments.append(
            {"feature": "chain_override_bonus", "contribution": bonus, "value": bonus}
        )

    if not features.get("breakout_strict") and features.get("provisional_candidate"):
        score -= penalty
        adjustments.append(
            {"feature": "weak_breakout_penalty", "contribution": -penalty, "value": penalty}
        )

    return score, adjustments


def _apply_chain_risk(proposal, chain_features: Optional[Dict[str, object]]):
    if not chain_features:
        return proposal
    if proposal.action in {ACTION_EXIT_FULL, ACTION_SCALE_OUT_20}:
        return proposal

    reasons: list[str] = []
    net_native = _safe_float(chain_features.get("chain_net_native"))
    net_token = _safe_float(chain_features.get("chain_net_token"))
    if net_native is not None and net_native < 0:
        reasons.append("NET_OUTFLOW")
    if net_token is not None and net_token < 0 and "NET_OUTFLOW" not in reasons:
        reasons.append("NET_OUTFLOW")

    liquidity_events = _safe_float(chain_features.get("chain_liquidity_events"))
    liquidity_removes = _safe_float(chain_features.get("chain_liquidity_remove_events"))
    if liquidity_removes is not None and liquidity_removes > 0:
        reasons.append("LIQUIDITY_RISK")
    elif liquidity_events is not None and liquidity_events < 0:
        reasons.append("LIQUIDITY_RISK")

    tx_count = _safe_float(chain_features.get("chain_tx_count"))
    velocity = _safe_float(chain_features.get("chain_tx_velocity_per_min"))
    if velocity is not None and tx_count is not None:
        if velocity >= 8.0 and tx_count < 40:
            reasons.append("DEAD_AFTER_SPIKE")

    if not reasons:
        return proposal

    merged = list(proposal.reason_codes)
    for reason in reasons:
        if reason not in merged:
            merged.append(reason)

    if proposal.action in {ACTION_PROBE_BUY, ACTION_ADD_BUY}:
        return proposal.model_copy(update={"action": ACTION_HOLD, "reason_codes": merged})
    if proposal.action == ACTION_HOLD:
        return proposal.model_copy(update={"reason_codes": merged})
    return proposal


def _interval_to_seconds(interval: str) -> int:
    mapping = {
        "1s": 1,
        "15s": 15,
        "30s": 30,
        "1m": 60,
        "3m": 180,
        "5m": 300,
        "15m": 900,
        "30m": 1800,
        "1H": 3600,
        "2H": 7200,
        "4H": 14400,
        "6H": 21600,
        "8H": 28800,
        "12H": 43200,
        "1D": 86400,
        "3D": 259200,
        "1W": 604800,
        "1M": 2592000,
    }
    return mapping.get(interval, 60)


def _amount_to_base_units(amount: float, decimals: int) -> int:
    return max(int(round(amount * (10**decimals))), 1)


def _compute_chain_velocity_baseline(
    proposals: list,
    velocity_history: Dict[str, list[float]],
    window_bars: int,
) -> Dict[str, Dict[str, float]]:
    baseline: Dict[str, Dict[str, float]] = {}
    for item in proposals:
        token_mint = item.get("token_mint")
        if not token_mint:
            continue
        features = item.get("chain_features") or {}
        velocity = _safe_float(features.get("chain_tx_velocity_per_min"))
        if velocity is None:
            continue
        history = velocity_history.get(token_mint, [])
        recent = history[-window_bars:]
        if len(recent) >= 2:
            mean = sum(recent) / len(recent)
            variance = sum((value - mean) ** 2 for value in recent) / len(recent)
            std = sqrt(variance)
            baseline[token_mint] = {
                "z": (velocity - mean) / std if std > 0 else 0.0,
                "mean": mean,
                "std": std,
            }
        updated = recent + [velocity]
        velocity_history[token_mint] = updated[-window_bars:]
    return baseline


async def _get_candles(
    api: MockApiClient,
    market_provider: Optional[MarketDataProvider],
    token_mint: str,
    config: dict,
    limit: int = 300,
) -> list:
    if market_provider is None:
        return await api.get_ohlcv(token_mint, limit=limit)

    interval = str(config.get("market", {}).get("interval", "1m"))
    now_ts = int(time.time())
    if isinstance(market_provider, MockMarketProvider):
        start_ts = 0
    else:
        interval_sec = _interval_to_seconds(interval)
        start_ts = now_ts - (interval_sec * max(limit, 1))
    return await market_provider.get_ohlcv(
        token_mint,
        interval,
        start_ts=start_ts,
        end_ts=now_ts,
        limit=limit,
    )


async def _get_chain_features(
    chain_provider: ChainIntelProvider,
    token_mint: str,
    config: dict,
) -> dict:
    chain_cfg = config.get("chain", {})
    if chain_cfg.get("enabled", True) is False:
        return {}
    direct = getattr(chain_provider, "get_chain_features", None)
    if callable(direct):
        try:
            result = direct(token_mint)
            if isawaitable(result):
                result = await result
            if isinstance(result, dict):
                return result
        except Exception:
            return {}

    limit = int(chain_cfg.get("tx_limit", 25))
    try:
        txs = await chain_provider.get_enhanced_txs_by_address(token_mint, limit=limit)
    except Exception:
        return {}
    return compute_chain_features(txs, token_mint, token_mint)


def _apply_chain_override_flags(snapshot, chain_features: Dict[str, object], config: dict) -> None:
    breakout_cfg = config.get("breakout", {})
    breakout_strict = bool(snapshot.features.get("breakout_strict", snapshot.features.get("breakout")))

    chain_confirmed = False
    if chain_features:
        min_velocity = float(breakout_cfg.get("chain_override_min_tx_velocity_per_min", 0.0))
        min_swaps = float(breakout_cfg.get("chain_override_min_swap_count", 0.0))
        min_net_native = float(breakout_cfg.get("chain_override_min_net_native", 0.0))
        min_liquidity_events = float(breakout_cfg.get("chain_override_min_liquidity_events", 0.0))

        velocity = _safe_float(chain_features.get("chain_tx_velocity_per_min")) or 0.0
        swap_count = _safe_float(chain_features.get("chain_swap_count")) or 0.0
        net_native = _safe_float(chain_features.get("chain_net_native")) or 0.0
        liquidity_events = _safe_float(chain_features.get("chain_liquidity_events")) or 0.0

        chain_confirmed = (
            velocity >= min_velocity
            and swap_count >= min_swaps
            and net_native >= min_net_native
            and liquidity_events >= min_liquidity_events
        )

    chain_override_enabled = bool(breakout_cfg.get("chain_override_enabled", True))
    chain_override = (not breakout_strict) and chain_override_enabled and chain_confirmed
    provisional_candidate = breakout_strict or chain_override

    snapshot.features["breakout_strict"] = breakout_strict
    snapshot.features["chain_confirmed"] = chain_confirmed
    snapshot.features["chain_override"] = chain_override
    snapshot.features["provisional_candidate"] = provisional_candidate


def _provider_mode(
    market_provider: Optional[MarketDataProvider],
    chain_provider: Optional[ChainIntelProvider],
    market_mode: Optional[str] = None,
    chain_mode: Optional[str] = None,
) -> Dict[str, str]:
    if market_mode:
        market_mode = market_mode.strip().lower()
    if chain_mode:
        chain_mode = chain_mode.strip().lower()

    if market_mode:
        market = market_mode
    elif market_provider is None or isinstance(market_provider, MockMarketProvider):
        market = "mock"
    else:
        market = "birdeye"

    if chain_mode:
        chain = chain_mode
    elif chain_provider is None or isinstance(chain_provider, MockHeliusProvider):
        chain = "mock"
    else:
        chain = "helius"

    return {"market": market, "chain": chain}


def _format_run_footer(
    candidate_count: int,
    action_counts: Dict[str, int],
    candidate_reject_counts: Counter[str],
) -> str:
    total_trades = sum(action_counts.values())
    top_reject = "none"
    if candidate_reject_counts and candidate_count > 0:
        reason, count = candidate_reject_counts.most_common(1)[0]
        pct = (count / candidate_count) * 100
        top_reject = f"{reason} ({pct:.0f}%)"
    return f"{candidate_count} candidates | {total_trades} trades | top reject: {top_reject}"


def _build_run_summary(
    run_id: str,
    market_provider: Optional[MarketDataProvider],
    chain_provider: Optional[ChainIntelProvider],
    universe_size: int,
    filtered_counts: Counter[str],
    action_counts: Dict[str, int],
    proposal_reason_counts: Counter[str],
    candidate_reason_counts: Counter[str],
    candidate_reject_counts: Counter[str],
    candidate_count: int,
    ranked_entries: list[Dict[str, object]],
    market_mode: Optional[str] = None,
    chain_mode: Optional[str] = None,
) -> Dict[str, object]:
    total_actions = sum(action_counts.values())
    why_no_trades = None
    if total_actions == 0:
        why_no_trades = {
            "no_actions": True,
            "top_filter_reasons": filtered_counts.most_common(5),
            "top_candidate_rejects": candidate_reject_counts.most_common(5),
            "top_candidate_reasons": candidate_reason_counts.most_common(5),
            "top_reason_occurrences": proposal_reason_counts.most_common(5),
            "note": "No executed actions; review breakout rules, ranking thresholds, and candidate quality.",
        }

    override_counts = {
        "PROVISIONAL_CHAIN_OVERRIDE": int(candidate_reason_counts.get("PROVISIONAL_CHAIN_OVERRIDE", 0))
    }

    return {
        "run_id": run_id,
        "timestamp": _utc_now_iso(),
        "provider_modes": _provider_mode(
            market_provider, chain_provider, market_mode=market_mode, chain_mode=chain_mode
        ),
        "universe_size": int(universe_size),
        "candidate_count": int(candidate_count),
        "filtered_counts": dict(filtered_counts),
        "candidate_reject_counts": dict(candidate_reject_counts),
        "top_candidate_rejects": candidate_reject_counts.most_common(5),
        "candidate_reason_counts": dict(candidate_reason_counts),
        "top_candidate_reasons": candidate_reason_counts.most_common(5),
        "reason_occurrences": dict(proposal_reason_counts),
        "top_reason_occurrences": proposal_reason_counts.most_common(5),
        "override_counts": override_counts,
        "action_count": int(total_actions),
        "action_counts": action_counts,
        "top_ranked": ranked_entries,
        "why_no_trades": why_no_trades,
    }


async def run_engine(
    iterations: int = 200,
    config: Optional[dict] = None,
    client: Optional[MockApiClient] = None,
    market_provider: Optional[MarketDataProvider] = None,
    chain_provider: Optional[ChainIntelProvider] = None,
    swap_service: Optional[JupiterSwapService] = None,
    log_dir: Optional[str] = None,
    max_tokens: Optional[int] = None,
    market_mode: Optional[str] = None,
    chain_mode: Optional[str] = None,
    sleep: bool = False,
) -> str:
    cfg = config or get_config()
    logger = TradeLogger(base_dir=log_dir)
    states: Dict[str, TokenState] = {}
    cursors: Dict[str, int] = {}
    filtered_counts: Counter[str] = Counter()
    proposal_reason_counts: Counter[str] = Counter()
    last_ranked: list[Dict[str, object]] = []
    decision_records: list[Dict[str, object]] = []
    last_decisions: list[Dict[str, object]] = []
    universe_size = 0
    quote_previews: list[Dict[str, object]] = []
    execution_plans: list[Dict[str, object]] = []
    velocity_history: Dict[str, list[float]] = {}

    if client is None:
        client = MockApiClient(base_url=cfg.get("mock_api_base"))

    async with AsyncExitStack() as stack:
        api = await stack.enter_async_context(client)
        if market_provider and hasattr(market_provider, "__aenter__"):
            market_provider = await stack.enter_async_context(market_provider)
        if chain_provider and hasattr(chain_provider, "__aenter__"):
            chain_provider = await stack.enter_async_context(chain_provider)

        candidates = await api.get_candidates()
        if max_tokens is not None:
            candidates = candidates[:max_tokens]
        universe_size = len(candidates)

        lookback = int(cfg.get("rules", {}).get("breakout_lookback", 20))
        momentum_lookback = int(cfg.get("rules", {}).get("momentum_lookback", 20))
        start_index = max(lookback + 5, 10)
        market_cfg = cfg.get("market", {})
        candle_limit = int(market_cfg.get("limit", 300))
        interval_sec = _interval_to_seconds(str(market_cfg.get("interval", "1m")))
        baseline_window_sec = int(cfg.get("chain", {}).get("baseline_window_sec", 86400))
        baseline_window_bars = max(1, int(baseline_window_sec / max(interval_sec, 1)))

        for _ in range(iterations):
            proposals = []
            iteration_decisions: list[Dict[str, object]] = []
            for candidate in candidates:
                pair_id = candidate.get("pair_id")
                token_mint = candidate.get("token_mint")
                symbol = candidate.get("symbol")
                if not pair_id or not token_mint:
                    if not pair_id:
                        filtered_counts["missing_pair_id"] += 1
                    if not token_mint:
                        filtered_counts["missing_token_mint"] += 1
                    continue

                pair = await api.get_pair(pair_id)
                candles_full = await _get_candles(
                    api, market_provider, token_mint, cfg, limit=candle_limit
                )
                if not candles_full:
                    filtered_counts["no_candles"] += 1
                    continue

                cursor = cursors.get(token_mint)
                if cursor is None:
                    if len(candles_full) < start_index:
                        min_start = max(2, lookback + 2)
                        cursor = min(len(candles_full), min_start)
                    else:
                        cursor = start_index
                if cursor < len(candles_full):
                    cursor += 1
                cursor = min(cursor, len(candles_full))
                cursors[token_mint] = cursor

                candles = candles_full[:cursor]
                if len(candles) < 5:
                    filtered_counts["insufficient_candles"] += 1
                    continue

                state = states.get(token_mint, TokenState())
                advance_time(state)

                chain_features = {}
                if chain_provider is not None:
                    chain_features = await _get_chain_features(chain_provider, token_mint, cfg)

                snapshot = build_snapshot(
                    pair,
                    candles,
                    cfg,
                    candle_index=cursor - 1,
                    extra_features=chain_features,
                )
                _apply_chain_override_flags(snapshot, chain_features, cfg)
                proposal = propose_action(snapshot, state, cfg)
                proposals.append(
                    {
                        "pair": pair,
                        "symbol": symbol,
                        "token_mint": token_mint,
                        "state": state,
                        "snapshot": snapshot,
                        "chain_features": chain_features,
                        "proposal": proposal,
                    }
                )

            _rank_entry_proposals(proposals, cfg)
            last_ranked = _build_ranked_summary(proposals, cfg)
            velocity_baseline = _compute_chain_velocity_baseline(
                proposals, velocity_history, baseline_window_bars
            )

            for item in proposals:
                pair = item["pair"]
                token_mint = item["token_mint"]
                state = item["state"]
                snapshot = item["snapshot"]
                proposal = item["proposal"]
                symbol = item.get("symbol") or token_mint

                validated = validate_action(proposal, snapshot, state, cfg)
                validated = _apply_chain_risk(validated, item.get("chain_features"))
                proposal_reason_counts.update(validated.reason_codes)
                score_diff = _momentum_score_detail(snapshot.candles, momentum_lookback)
                adjusted_score, adjustments = _apply_score_adjustments(
                    float(score_diff["total"]), snapshot.features, cfg
                )
                if adjustments:
                    score_diff["components"].extend(adjustments)
                    score_diff["components"].sort(
                        key=lambda item: abs(float(item.get("contribution", 0.0))), reverse=True
                    )
                    score_diff["top_features"] = [
                        item["feature"] for item in score_diff["components"][:2]
                    ]
                score_diff["total"] = float(adjusted_score)
                score_value = float(adjusted_score)

                baseline_entry = None
                baseline_note = None
                baseline_stats = velocity_baseline.get(token_mint)
                if baseline_stats:
                    z = baseline_stats.get("z")
                    mean = baseline_stats.get("mean")
                    std = baseline_stats.get("std")
                    if z is not None and mean is not None and std is not None:
                        baseline_entry = {
                            "z": float(z),
                            "mean": float(mean),
                            "std": float(std),
                            "window_sec": baseline_window_sec,
                            "scope": "rolling_token",
                        }
                        baseline_note = f"chain_tx_velocity_per_min {z:+.2f} sigma vs last_24h"
                decision_record = {
                    "ts": _utc_now_iso(),
                    "symbol": symbol,
                    "token_mint": token_mint,
                    "pair_id": pair.pair_id,
                    "score": score_value,
                    "last_close": float(snapshot.last_close),
                    "score_feature_diff": score_diff,
                    "breakout_strict": bool(snapshot.features.get("breakout_strict")),
                    "range_compressed": bool(snapshot.features.get("range_compressed")),
                    "price_expanded": bool(snapshot.features.get("price_expanded")),
                    "expansion_pct": float(snapshot.features.get("expansion_pct", 0.0)),
                    "chain_confirmed": bool(snapshot.features.get("chain_confirmed")),
                    "chain_override": bool(snapshot.features.get("chain_override")),
                    "provisional_candidate": bool(snapshot.features.get("provisional_candidate")),
                    "decision": validated.action,
                    "reasons": validated.reason_codes,
                    "features": {
                        "market": _compact_features(snapshot.features),
                        "chain": _compact_features(item.get("chain_features")),
                    },
                }
                if baseline_entry:
                    decision_record["baseline"] = {"chain_tx_velocity_per_min": baseline_entry}
                    decision_record["baseline_note"] = baseline_note
                iteration_decisions.append(decision_record)

                if validated.action != ACTION_HOLD:
                    notional_usd = _action_notional_usd(validated.action, state, cfg)
                    if validated.action in {ACTION_PROBE_BUY, ACTION_ADD_BUY}:
                        token_in = "USDC"
                        token_out = token_mint
                        amount_in = notional_usd
                    else:
                        token_in = token_mint
                        token_out = "USDC"
                        amount_in = notional_usd / max(snapshot.last_close, 1e-9)

                    execution = None
                    quote_payload = None
                    swap_payload = None
                    if swap_service is not None:
                        amount_base = _amount_to_base_units(amount_in, decimals=6)
                        quote_params = QuoteParams(
                            input_mint=token_in,
                            output_mint=token_out,
                            amount=amount_base,
                            slippage_bps=int(cfg.get("risk", {}).get("max_slippage_bps", 0)),
                        )
                        quote = await swap_service.get_quote(quote_params)
                        quote_payload = quote.model_dump(by_alias=True)
                        quote_previews.append(
                            {
                                "ts": _utc_now_iso(),
                                "token_in": token_in,
                                "token_out": token_out,
                                "amount_in": amount_in,
                                "amount_base": amount_base,
                                "slippage_bps": int(cfg.get("risk", {}).get("max_slippage_bps", 0)),
                                "quote": quote_payload,
                                "action": validated.action,
                                "symbol": symbol,
                                "token_mint": token_mint,
                            }
                        )
                        execution = await swap_service.execute_swap(
                            quote, user_pubkey="FAKE_USER_PUBKEY", opts=SwapOptions()
                        )
                        swap_payload = {
                            "swap_transaction": execution.swap_transaction,
                            "signature": execution.signature,
                            "status": execution.status,
                            "mode": execution.mode,
                        }
                        execution_plans.append(
                            {
                                "ts": _utc_now_iso(),
                                "action": validated.action,
                                "token_mint": token_mint,
                                "symbol": symbol,
                                "status": execution.status,
                                "mode": execution.mode,
                                "signature": execution.signature,
                                "swap_transaction": execution.swap_transaction,
                            }
                        )
                    else:
                        quote = await api.quote(
                            token_in=token_in,
                            token_out=token_out,
                            amount_in=amount_in,
                            slippage_bps=int(cfg.get("risk", {}).get("max_slippage_bps", 0)),
                        )
                        swap = await api.build_swap_tx(quote=quote, user_pubkey="FAKE_USER_PUBKEY")
                        quote_payload = {
                            "amount_in": quote.get("amount_in"),
                            "amount_out": quote.get("amount_out"),
                            "min_out": quote.get("min_out"),
                            "price_impact_pct": quote.get("price_impact_pct"),
                        }
                        swap_payload = {"serialized_tx_base64": swap.get("serialized_tx_base64")}

                    entry = {
                        "ts": snapshot.now_ts,
                        "pair_id": pair.pair_id,
                        "token_mint": pair.token_mint,
                        "action": validated.action,
                        "price_usd": snapshot.last_close,
                        "reason_codes": validated.reason_codes,
                        "state": state.status,
                        "notional_usd": notional_usd,
                        "quote": quote_payload,
                        "swap": swap_payload,
                    }
                    if execution is not None:
                        entry["execution"] = {
                            "status": execution.status,
                            "mode": execution.mode,
                            "signature": execution.signature,
                        }
                    logger.log(entry)
                    apply_action(state, validated.action, snapshot, cfg, exit_reason_codes=validated.reason_codes)

                states[token_mint] = state

            decision_records.extend(iteration_decisions)
            last_decisions = iteration_decisions

            if sleep:
                await asyncio.sleep(float(cfg.get("engine", {}).get("poll_interval_sec", 1)))

    candidate_reject_counts = _candidate_reject_counts(last_decisions)
    candidate_reason_counts = _candidate_reason_counts(last_decisions)
    if not last_ranked and last_decisions:
        last_ranked = _build_ranked_from_decisions(last_decisions, cfg)

    run_dir = Path(logger.run_dir)
    decisions_path = run_dir / "decisions.jsonl"
    summary_path = logger.run_dir / "run_summary.json"
    summary = _build_run_summary(
        run_id=logger.run_dir.name,
        market_provider=market_provider,
        chain_provider=chain_provider,
        universe_size=universe_size,
        filtered_counts=filtered_counts,
        action_counts=logger.action_counts(),
        proposal_reason_counts=proposal_reason_counts,
        candidate_reason_counts=candidate_reason_counts,
        candidate_reject_counts=candidate_reject_counts,
        candidate_count=len(last_decisions),
        ranked_entries=last_ranked,
        market_mode=market_mode,
        chain_mode=chain_mode,
    )
    write_jsonl(decisions_path, decision_records)
    write_json(summary_path, summary)
    if swap_service is not None:
        write_jsonl(run_dir / "quote_previews.jsonl", quote_previews)
        write_jsonl(run_dir / "execution_plans.jsonl", execution_plans)
    logger.summarize()
    print(_format_run_footer(summary["candidate_count"], summary["action_counts"], candidate_reject_counts))
    logger.close()
    return str(logger.run_dir)
