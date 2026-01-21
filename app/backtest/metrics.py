from __future__ import annotations

from typing import Dict, List


def equity_curve(starting_capital: float, trades: List[Dict]) -> List[float]:
    curve = [starting_capital]
    equity = starting_capital
    for trade in trades:
        equity += float(trade.get("pnl_usd", 0.0))
        curve.append(equity)
    return curve


def max_drawdown(curve: List[float]) -> float:
    peak = curve[0] if curve else 0.0
    max_dd = 0.0
    for value in curve:
        if value > peak:
            peak = value
        drawdown = (peak - value) / peak if peak > 0 else 0.0
        if drawdown > max_dd:
            max_dd = drawdown
    return max_dd


def profit_factor(trades: List[Dict]) -> float:
    wins = sum(float(t.get("pnl_usd", 0.0)) for t in trades if t.get("pnl_usd", 0.0) > 0)
    losses = sum(-float(t.get("pnl_usd", 0.0)) for t in trades if t.get("pnl_usd", 0.0) < 0)
    if losses == 0:
        return float("inf") if wins > 0 else 0.0
    return wins / losses


def win_rate(trades: List[Dict]) -> float:
    if not trades:
        return 0.0
    wins = sum(1 for t in trades if t.get("pnl_usd", 0.0) > 0)
    return wins / len(trades)


def avg_trade_return(trades: List[Dict]) -> float:
    if not trades:
        return 0.0
    returns = [float(t.get("return_pct", 0.0)) for t in trades]
    return sum(returns) / len(returns)


def trade_count(trades: List[Dict]) -> int:
    return len(trades)


def compute_metrics(starting_capital: float, trades: List[Dict]) -> Dict[str, float | int]:
    curve = equity_curve(starting_capital, trades)
    return {
        "total_return_pct": ((curve[-1] / starting_capital) - 1.0) if curve else 0.0,
        "max_drawdown_pct": max_drawdown(curve),
        "profit_factor": profit_factor(trades),
        "win_rate": win_rate(trades),
        "avg_trade_return_pct": avg_trade_return(trades),
        "trade_count": trade_count(trades),
    }
