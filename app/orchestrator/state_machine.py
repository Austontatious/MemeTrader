from __future__ import annotations

from dataclasses import dataclass
from statistics import median
from typing import Optional

from app.config import get_config

STATE_SCOUT = "SCOUT"
STATE_PROBE = "PROBE"
STATE_TRADE = "TRADE"
STATE_COOLDOWN = "COOLDOWN"


@dataclass
class TokenState:
    status: str = STATE_SCOUT
    probe_entry_price: Optional[float] = None
    probe_entry_low: Optional[float] = None
    add_entry_price: Optional[float] = None
    position_usd: float = 0.0
    time_in_trade: int = 0
    cooldown_left: int = 0
    scale_out_stage: int = 0
    last_exit_ts: Optional[int] = None
    last_exit_price: Optional[float] = None
    last_exit_index: Optional[int] = None
    entry_index: Optional[int] = None
    last_exit_was_stop: bool = False
    pending_breakout_index: Optional[int] = None
    pending_breakout_level: Optional[float] = None
    pending_breakout_expires_index: Optional[int] = None
    entry_price: Optional[float] = None
    max_favorable_price: Optional[float] = None
    progress_hit: bool = False
    progress_deadline_index: Optional[int] = None


def infer_interval_sec(candles) -> int:
    diffs = []
    for idx in range(1, len(candles)):
        try:
            diff = int(candles[idx].t) - int(candles[idx - 1].t)
        except Exception:
            continue
        if diff > 0:
            diffs.append(diff)
    if not diffs:
        return 60
    return int(median(diffs))


def _lockout_candles(cfg: dict, last_exit_was_stop: bool) -> int:
    lockout = int(cfg.get("reentry", {}).get("lockout_candles", 0))
    if last_exit_was_stop:
        lockout *= 3
    return lockout


def _lockout_expired(
    now_ts: int,
    last_exit_ts: Optional[int],
    now_index: Optional[int],
    last_exit_index: Optional[int],
    cfg: dict,
    interval_sec: int,
    last_exit_was_stop: bool,
) -> bool:
    lockout_candles = _lockout_candles(cfg, last_exit_was_stop)
    if lockout_candles <= 0:
        return True
    if now_index is not None and last_exit_index is not None:
        return (now_index - last_exit_index) >= lockout_candles
    if last_exit_ts is None:
        return True
    return now_ts >= last_exit_ts + lockout_candles * interval_sec


def update_reentry_lockout(
    state: TokenState,
    now_ts: int,
    cfg: dict,
    interval_sec: int,
    now_index: Optional[int] = None,
) -> None:
    if not state.last_exit_was_stop:
        return
    if _lockout_expired(
        now_ts,
        state.last_exit_ts,
        now_index,
        state.last_exit_index,
        cfg,
        interval_sec,
        last_exit_was_stop=True,
    ):
        state.last_exit_was_stop = False


def clear_pending_breakout(state: TokenState) -> None:
    state.pending_breakout_index = None
    state.pending_breakout_level = None
    state.pending_breakout_expires_index = None


def can_reenter(
    now_ts: int,
    last_exit_ts: Optional[int],
    last_exit_index: Optional[int],
    last_exit_price: Optional[float],
    current_close: float,
    cfg: dict,
    vol_ok: bool = False,
    last_exit_was_stop: bool = False,
    interval_sec: Optional[int] = None,
    now_index: Optional[int] = None,
) -> bool:
    if last_exit_price is None:
        return True

    if last_exit_ts is None and last_exit_index is None:
        return True

    reentry_cfg = cfg.get("reentry", {})
    lockout_candles = _lockout_candles(cfg, last_exit_was_stop)
    min_breakout = float(reentry_cfg.get("min_breakout_pct", 0.0))
    candle_seconds = int(interval_sec if interval_sec else reentry_cfg.get("candle_seconds", 60))

    if lockout_candles <= 0:
        return True

    if now_index is not None and last_exit_index is not None:
        if (now_index - last_exit_index) < lockout_candles:
            if current_close >= last_exit_price * (1.0 + min_breakout):
                return True
            if vol_ok:
                return True
            return False
        return True

    if last_exit_ts is None:
        return True

    lockout_until = last_exit_ts + lockout_candles * candle_seconds
    if now_ts < lockout_until:
        if current_close >= last_exit_price * (1.0 + min_breakout):
            return True
        if vol_ok:
            return True
        return False
    return True


def advance_time(state: TokenState) -> None:
    if state.status in {STATE_PROBE, STATE_TRADE}:
        state.time_in_trade += 1
    if state.status == STATE_COOLDOWN and state.cooldown_left > 0:
        state.cooldown_left -= 1
        if state.cooldown_left <= 0:
            state.status = STATE_SCOUT
            state.cooldown_left = 0


def apply_action(
    state: TokenState,
    action: str,
    snapshot,
    config: dict | None = None,
    exit_reason_codes: Optional[list[str]] = None,
) -> None:
    cfg = config or get_config()
    positioning = cfg.get("positioning", {})
    engine_cfg = cfg.get("engine", {})
    progress_cfg = cfg.get("rules", {}).get("progress", {})

    if action == "PROBE_BUY":
        clear_pending_breakout(state)
        state.status = STATE_PROBE
        state.probe_entry_price = snapshot.last_close
        state.probe_entry_low = snapshot.last_low
        state.position_usd = positioning.get("capital_usd", 0.0) * positioning.get("probe_pct", 0.0)
        state.time_in_trade = 0
        state.scale_out_stage = 0
        state.entry_index = snapshot.candle_index
        state.entry_price = snapshot.last_close
        state.max_favorable_price = snapshot.last_close
        state.progress_hit = False
        max_wait = int(progress_cfg.get("max_wait_candles", 0))
        if state.entry_index is not None and max_wait > 0:
            state.progress_deadline_index = state.entry_index + max_wait
        else:
            state.progress_deadline_index = None
    elif action == "ADD_BUY":
        clear_pending_breakout(state)
        state.status = STATE_TRADE
        state.add_entry_price = snapshot.last_close
        state.position_usd += positioning.get("capital_usd", 0.0) * positioning.get("add_pct", 0.0)
        if state.entry_index is None:
            state.entry_index = snapshot.candle_index
        if state.entry_price is None:
            state.entry_price = snapshot.last_close
    elif action == "SCALE_OUT_20":
        stage = state.scale_out_stage
        if stage == 0:
            scale_pct = positioning.get("tp1_scale_out_pct", 0.0)
        else:
            scale_pct = positioning.get("tp2_scale_out_pct", 0.0)
        state.position_usd = max(0.0, state.position_usd * (1.0 - scale_pct))
        state.scale_out_stage += 1
    elif action == "EXIT_FULL":
        clear_pending_breakout(state)
        state.status = STATE_COOLDOWN
        state.cooldown_left = int(engine_cfg.get("cooldown_candles", 0))
        state.probe_entry_price = None
        state.probe_entry_low = None
        state.add_entry_price = None
        state.position_usd = 0.0
        state.time_in_trade = 0
        state.scale_out_stage = 0
        state.entry_index = None
        state.entry_price = None
        state.max_favorable_price = None
        state.progress_hit = False
        state.progress_deadline_index = None
        state.last_exit_ts = int(snapshot.now_ts)
        state.last_exit_price = float(snapshot.last_close)
        state.last_exit_index = snapshot.candle_index
        state.last_exit_was_stop = bool(exit_reason_codes and "STRUCT_STOP" in exit_reason_codes)
    else:
        return
