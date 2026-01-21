from __future__ import annotations

import csv
import gzip
import json
import os
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, List, Optional

import pandas as pd

from app.backtest.metrics import compute_metrics
from app.config import get_config, repo_root
from app.data.mock_schemas import Candle, PairStats
from app.orchestrator.snapshot import build_snapshot
from app.orchestrator.state_machine import TokenState, advance_time, apply_action
from app.orchestrator.validator import validate_action
from app.policies.base import (
    ACTION_ADD_BUY,
    ACTION_EXIT_FULL,
    ACTION_HOLD,
    ACTION_PROBE_BUY,
    ACTION_SCALE_OUT_20,
)
from app.policies.rules_v0 import propose_action
from app.signals.features import momentum_score

CANDLE_ALIASES = {
    "t": ["t", "timestamp", "time", "ts"],
    "o": ["o", "open"],
    "h": ["h", "high"],
    "l": ["l", "low"],
    "c": ["c", "close"],
    "v": ["v", "volume"],
}


def _first_key(row: Dict, keys: List[str]) -> Optional[float]:
    for key in keys:
        if key in row:
            return row[key]
    return None


def _normalize_candle(row: Dict) -> Optional[Candle]:
    values = {}
    for key, aliases in CANDLE_ALIASES.items():
        value = _first_key(row, aliases)
        if value is None:
            return None
        values[key] = value
    return Candle(
        t=int(values["t"]),
        o=float(values["o"]),
        h=float(values["h"]),
        l=float(values["l"]),
        c=float(values["c"]),
        v=float(values["v"]),
    )


def _normalize_sequence(values: Iterable) -> Optional[Candle]:
    values = list(values)
    if len(values) < 6:
        return None
    try:
        return Candle(
            t=int(values[0]),
            o=float(values[1]),
            h=float(values[2]),
            l=float(values[3]),
            c=float(values[4]),
            v=float(values[5]),
        )
    except (TypeError, ValueError):
        return None


def _normalize_any(row) -> Optional[Candle]:
    if isinstance(row, dict):
        return _normalize_candle(row)
    if isinstance(row, (list, tuple)):
        return _normalize_sequence(row)
    return None


def _candles_from_rows(rows: Iterable) -> List[Candle]:
    candles: List[Candle] = []
    for row in rows:
        if isinstance(row, dict):
            for key in ("candles", "data", "ohlcv"):
                if key in row and isinstance(row[key], list):
                    for item in row[key]:
                        candle = _normalize_any(item)
                        if candle:
                            candles.append(candle)
                    break
            else:
                candle = _normalize_any(row)
                if candle:
                    candles.append(candle)
        else:
            candle = _normalize_any(row)
            if candle:
                candles.append(candle)
    return candles


def load_candles_from_jsonl(path: Path, max_rows: Optional[int] = None) -> List[Candle]:
    candles: List[Candle] = []
    if path.name.endswith(".gz"):
        handle = gzip.open(path, "rt", encoding="utf-8")
    else:
        handle = path.open("r", encoding="utf-8")
    with handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            batch = _candles_from_rows([row])
            if max_rows is not None:
                remaining = max_rows - len(candles)
                if remaining <= 0:
                    break
                candles.extend(batch[:remaining])
                if len(candles) >= max_rows:
                    break
            else:
                candles.extend(batch)
    return candles


def load_candles_from_json(path: Path, max_rows: Optional[int] = None) -> List[Candle]:
    with path.open("r", encoding="utf-8") as handle:
        try:
            obj = json.load(handle)
        except json.JSONDecodeError:
            return load_candles_from_jsonl(path, max_rows=max_rows)
    rows = obj if isinstance(obj, list) else [obj]
    candles = _candles_from_rows(rows)
    if max_rows is not None:
        return candles[:max_rows]
    return candles


def load_candles_from_csv(path: Path, max_rows: Optional[int] = None) -> List[Candle]:
    with path.open("r", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        candles = _candles_from_rows(list(reader))
        if max_rows is not None:
            return candles[:max_rows]
        return candles


def load_candles_from_parquet(path: Path, max_rows: Optional[int] = None) -> List[Candle]:
    frame = pd.read_parquet(path)
    candles = _candles_from_rows(frame.to_dict(orient="records"))
    if max_rows is not None:
        return candles[:max_rows]
    return candles


def load_candles_from_path(path: Path, max_rows: Optional[int] = None) -> List[Candle]:
    name = path.name
    if name.endswith(".jsonl.gz") or path.suffix == ".jsonl":
        return load_candles_from_jsonl(path, max_rows=max_rows)
    if path.suffix == ".json":
        return load_candles_from_json(path, max_rows=max_rows)
    if path.suffix == ".csv":
        return load_candles_from_csv(path, max_rows=max_rows)
    if path.suffix == ".parquet":
        return load_candles_from_parquet(path, max_rows=max_rows)
    return []


def _pair_name_from_path(path: Path) -> str:
    name = path.name
    for suffix in reversed(path.suffixes):
        if name.endswith(suffix):
            name = name[: -len(suffix)]
    return name


def _is_data_file(name: str) -> bool:
    return name.endswith((".jsonl", ".jsonl.gz", ".parquet", ".json", ".csv"))


def _find_data_files(data_dir: Path, limit: int) -> List[Path]:
    matches: List[Path] = []
    for root, _, files in os.walk(data_dir):
        for name in files:
            if not _is_data_file(name):
                continue
            matches.append(Path(root) / name)
            if len(matches) >= limit:
                return sorted(matches)
    return sorted(matches)


def _apply_costs(price: float, side: str, costs: dict) -> float:
    fee = float(costs.get("fee_bps_per_side", 0.0)) / 10000.0
    slip = float(costs.get("slippage_bps", 0.0)) / 10000.0
    if side == "buy":
        return price * (1.0 + fee + slip)
    return price * (1.0 - fee - slip)


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


def _rank_entry_proposals(proposals: List[Dict[str, object]], config: dict, ranked_out_counts: Counter) -> None:
    rules_cfg = config.get("rules", {})
    top_n = int(rules_cfg.get("top_n_per_tick", 0))
    min_candidates = int(rules_cfg.get("min_candidates_before_rank", 0))
    lookback = int(rules_cfg.get("momentum_lookback", 20))

    entries = [p for p in proposals if p["proposal"].action == ACTION_PROBE_BUY]
    if top_n <= 0 or len(entries) < max(1, min_candidates):
        return

    for entry in entries:
        entry["momentum_score"] = momentum_score(entry["snapshot"].candles, lookback)

    entries.sort(key=lambda p: p.get("momentum_score", 0.0), reverse=True)
    for entry in entries[top_n:]:
        proposal = entry["proposal"]
        entry["proposal"] = proposal.model_copy(
            update={"action": ACTION_HOLD, "reason_codes": proposal.reason_codes + ["RANKED_OUT"]}
        )
        ranked_out_counts["RANKED_OUT"] += 1


def simulate_pair(pair_id: str, token_mint: str, candles: List[Candle], config: dict) -> Dict[str, object]:
    positioning = config.get("positioning", {})
    costs = config.get("costs", {})
    risk_cfg = config.get("risk", {})
    backtest_cfg = config.get("backtest", {})

    capital = float(positioning.get("capital_usd", 1000.0))
    cash = capital
    position_qty = 0.0
    position_cost_usd = 0.0

    trades: List[Dict[str, object]] = []
    state = TokenState()

    lookback = int(config.get("rules", {}).get("breakout_lookback", 20))
    max_window = int(backtest_cfg.get("max_window_candles", 200))
    max_window = max(max_window, lookback + 5)
    start_index = max(lookback + 5, 10)

    for i in range(start_index, len(candles)):
        window = candles[max(0, i + 1 - max_window) : i + 1]
        last = window[-1]
        liquidity = max(float(risk_cfg.get("min_liquidity_usd", 0.0)) * 2, 100000.0)
        pair = PairStats(
            pair_id=pair_id,
            token_mint=token_mint,
            price_usd=float(last.c),
            liquidity_usd=liquidity,
            volume_5m=float(sum(c.v for c in window[-5:])),
            txns_5m=int(sum(c.v for c in window[-5:]) / 100),
        )

        advance_time(state)
        snapshot = build_snapshot(pair, window, config, candle_index=i)
        proposal = propose_action(snapshot, state, config)
        validated = validate_action(proposal, snapshot, state, config)

        if validated.action == ACTION_HOLD:
            continue

        notional_usd = _action_notional_usd(validated.action, state, config)
        price = float(last.c)

        if validated.action in {ACTION_PROBE_BUY, ACTION_ADD_BUY}:
            if cash < notional_usd:
                continue
            exec_price = _apply_costs(price, "buy", costs)
            qty = notional_usd / max(exec_price, 1e-9)
            cash -= notional_usd
            position_qty += qty
            position_cost_usd += notional_usd
            trades.append(
                {
                    "ts": int(last.t),
                    "action": validated.action,
                    "price": exec_price,
                    "qty": qty,
                    "notional_usd": notional_usd,
                    "pnl_usd": 0.0,
                    "return_pct": 0.0,
                    "reason_codes": ",".join(validated.reason_codes),
                }
            )
        else:
            if position_qty <= 0:
                continue
            if validated.action == ACTION_SCALE_OUT_20:
                if state.scale_out_stage == 0:
                    scale_pct = float(positioning.get("tp1_scale_out_pct", 0.0))
                else:
                    scale_pct = float(positioning.get("tp2_scale_out_pct", 0.0))
            else:
                scale_pct = 1.0

            sell_qty = position_qty * scale_pct
            exec_price = _apply_costs(price, "sell", costs)
            proceeds = sell_qty * exec_price
            cost_basis = position_cost_usd * (sell_qty / position_qty)
            pnl = proceeds - cost_basis
            return_pct = pnl / cost_basis if cost_basis > 0 else 0.0

            cash += proceeds
            position_qty -= sell_qty
            position_cost_usd -= cost_basis

            trades.append(
                {
                    "ts": int(last.t),
                    "action": validated.action,
                    "price": exec_price,
                    "qty": sell_qty,
                    "notional_usd": proceeds,
                    "pnl_usd": pnl,
                    "return_pct": return_pct,
                    "reason_codes": ",".join(validated.reason_codes),
                }
            )

        apply_action(state, validated.action, snapshot, config, exit_reason_codes=validated.reason_codes)
        state.position_usd = position_cost_usd

    if position_qty > 0:
        last = candles[-1]
        exec_price = _apply_costs(float(last.c), "sell", costs)
        proceeds = position_qty * exec_price
        cost_basis = position_cost_usd
        pnl = proceeds - cost_basis
        return_pct = pnl / cost_basis if cost_basis > 0 else 0.0
        trades.append(
            {
                "ts": int(last.t),
                "action": ACTION_EXIT_FULL,
                "price": exec_price,
                "qty": position_qty,
                "notional_usd": proceeds,
                "pnl_usd": pnl,
                "return_pct": return_pct,
                "reason_codes": "FORCED_EXIT",
            }
        )
        cash += proceeds
        position_qty = 0.0
        position_cost_usd = 0.0

    metrics = compute_metrics(capital, trades)
    return {"metrics": metrics, "trades": trades}


def run_backtest(
    data_dir: Path,
    config: Optional[dict] = None,
    max_pairs: int = 5,
    output_base: Optional[Path] = None,
) -> Path:
    cfg = config or get_config()
    output_root = output_base or (repo_root() / "backtests")
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    run_dir = output_root / timestamp
    run_dir.mkdir(parents=True, exist_ok=True)

    files = _find_data_files(data_dir, max_pairs)
    if not files:
        raise FileNotFoundError(f"No supported data files found in {data_dir}")

    per_pair: Dict[str, Dict[str, float]] = {}
    all_trades: List[Dict[str, object]] = []

    backtest_cfg = cfg.get("backtest", {})
    max_candles = backtest_cfg.get("max_candles_per_pair", 1000)
    max_candles = int(max_candles) if max_candles else None

    series: Dict[str, List[Candle]] = {}
    for file_path in files:
        pair_name = _pair_name_from_path(file_path)
        candles = load_candles_from_path(file_path, max_rows=max_candles)
        if len(candles) < 30:
            continue
        series[pair_name] = candles

    if not series:
        raise FileNotFoundError(f"No valid pair files found in {data_dir}")

    capital = float(cfg.get("positioning", {}).get("capital_usd", 1000.0))
    costs = cfg.get("costs", {})
    risk_cfg = cfg.get("risk", {})
    rules_cfg = cfg.get("rules", {})
    lookback = int(rules_cfg.get("breakout_lookback", 20))
    max_window = int(backtest_cfg.get("max_window_candles", 200))
    max_window = max(max_window, lookback + 5)
    start_index = max(lookback + 5, 10)

    states = {pair_name: TokenState() for pair_name in series}
    portfolios = {
        pair_name: {"cash": capital, "position_qty": 0.0, "position_cost_usd": 0.0} for pair_name in series
    }
    trades_by_pair: Dict[str, List[Dict[str, object]]] = {pair_name: [] for pair_name in series}

    entry_reason_counts: Counter = Counter()
    exit_reason_counts: Counter = Counter()
    ranked_out_counts: Counter = Counter()

    max_len = max(len(candles) for candles in series.values())
    for i in range(start_index, max_len):
        proposals: List[Dict[str, object]] = []
        for pair_name, candles in series.items():
            if i >= len(candles):
                continue
            window = candles[max(0, i + 1 - max_window) : i + 1]
            if len(window) < 5:
                continue

            last = window[-1]
            liquidity = max(float(risk_cfg.get("min_liquidity_usd", 0.0)) * 2, 100000.0)
            pair = PairStats(
                pair_id=pair_name,
                token_mint=pair_name,
                price_usd=float(last.c),
                liquidity_usd=liquidity,
                volume_5m=float(sum(c.v for c in window[-5:])),
                txns_5m=int(sum(c.v for c in window[-5:]) / 100),
            )

            state = states[pair_name]
            advance_time(state)
            snapshot = build_snapshot(pair, window, cfg, candle_index=i)
            proposal = propose_action(snapshot, state, cfg)
            proposals.append(
                {
                    "pair_name": pair_name,
                    "snapshot": snapshot,
                    "proposal": proposal,
                    "state": state,
                }
            )

        _rank_entry_proposals(proposals, cfg, ranked_out_counts)

        for item in proposals:
            pair_name = item["pair_name"]
            snapshot = item["snapshot"]
            proposal = item["proposal"]
            state = item["state"]
            portfolio = portfolios[pair_name]

            validated = validate_action(proposal, snapshot, state, cfg)
            if validated.action == ACTION_HOLD:
                continue

            notional_usd = _action_notional_usd(validated.action, state, cfg)
            price = float(snapshot.last_close)

            if validated.action in {ACTION_PROBE_BUY, ACTION_ADD_BUY}:
                if portfolio["cash"] < notional_usd:
                    continue
                exec_price = _apply_costs(price, "buy", costs)
                qty = notional_usd / max(exec_price, 1e-9)
                portfolio["cash"] -= notional_usd
                portfolio["position_qty"] += qty
                portfolio["position_cost_usd"] += notional_usd
                trade = {
                    "ts": int(snapshot.now_ts),
                    "action": validated.action,
                    "price": exec_price,
                    "qty": qty,
                    "notional_usd": notional_usd,
                    "pnl_usd": 0.0,
                    "return_pct": 0.0,
                    "reason_codes": ",".join(validated.reason_codes),
                }
                trades_by_pair[pair_name].append(trade)
                all_trades.append(trade)
                for reason in validated.reason_codes:
                    entry_reason_counts[reason] += 1
            else:
                if portfolio["position_qty"] <= 0:
                    continue
                if validated.action == ACTION_SCALE_OUT_20:
                    if state.scale_out_stage == 0:
                        scale_pct = float(cfg.get("positioning", {}).get("tp1_scale_out_pct", 0.0))
                    else:
                        scale_pct = float(cfg.get("positioning", {}).get("tp2_scale_out_pct", 0.0))
                else:
                    scale_pct = 1.0

                sell_qty = portfolio["position_qty"] * scale_pct
                exec_price = _apply_costs(price, "sell", costs)
                proceeds = sell_qty * exec_price
                cost_basis = portfolio["position_cost_usd"] * (sell_qty / portfolio["position_qty"])
                pnl = proceeds - cost_basis
                return_pct = pnl / cost_basis if cost_basis > 0 else 0.0

                portfolio["cash"] += proceeds
                portfolio["position_qty"] -= sell_qty
                portfolio["position_cost_usd"] -= cost_basis

                trade = {
                    "ts": int(snapshot.now_ts),
                    "action": validated.action,
                    "price": exec_price,
                    "qty": sell_qty,
                    "notional_usd": proceeds,
                    "pnl_usd": pnl,
                    "return_pct": return_pct,
                    "reason_codes": ",".join(validated.reason_codes),
                }
                trades_by_pair[pair_name].append(trade)
                all_trades.append(trade)
                if validated.action == ACTION_EXIT_FULL:
                    for reason in validated.reason_codes:
                        exit_reason_counts[reason] += 1

            apply_action(state, validated.action, snapshot, cfg, exit_reason_codes=validated.reason_codes)
            state.position_usd = portfolio["position_cost_usd"]

    for pair_name, portfolio in portfolios.items():
        if portfolio["position_qty"] <= 0:
            continue
        candles = series[pair_name]
        last = candles[-1]
        exec_price = _apply_costs(float(last.c), "sell", costs)
        proceeds = portfolio["position_qty"] * exec_price
        cost_basis = portfolio["position_cost_usd"]
        pnl = proceeds - cost_basis
        return_pct = pnl / cost_basis if cost_basis > 0 else 0.0
        trade = {
            "ts": int(last.t),
            "action": ACTION_EXIT_FULL,
            "price": exec_price,
            "qty": portfolio["position_qty"],
            "notional_usd": proceeds,
            "pnl_usd": pnl,
            "return_pct": return_pct,
            "reason_codes": "FORCED_EXIT",
        }
        trades_by_pair[pair_name].append(trade)
        all_trades.append(trade)
        exit_reason_counts["FORCED_EXIT"] += 1
        portfolio["cash"] += proceeds
        portfolio["position_qty"] = 0.0
        portfolio["position_cost_usd"] = 0.0

    for pair_name, trades in trades_by_pair.items():
        metrics = compute_metrics(capital, trades)
        per_pair[pair_name] = metrics

        csv_path = run_dir / f"trades_{pair_name}.csv"
        with csv_path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(
                handle,
                fieldnames=[
                    "ts",
                    "action",
                    "price",
                    "qty",
                    "notional_usd",
                    "pnl_usd",
                    "return_pct",
                    "reason_codes",
                ],
            )
            writer.writeheader()
            for row in trades:
                writer.writerow(row)

    combined_metrics = compute_metrics(capital * max(len(per_pair), 1), all_trades)

    summary = {
        "pair_count": len(per_pair),
        "pairs": per_pair,
        "combined": combined_metrics,
    }

    summary_path = run_dir / "summary.json"
    with summary_path.open("w", encoding="utf-8") as handle:
        json.dump(summary, handle, indent=2)

    (run_dir / "exit_reason_counts.json").write_text(json.dumps(exit_reason_counts, indent=2))
    (run_dir / "entry_reason_counts.json").write_text(json.dumps(entry_reason_counts, indent=2))
    (run_dir / "ranked_out_counts.json").write_text(json.dumps(ranked_out_counts, indent=2))

    return run_dir
