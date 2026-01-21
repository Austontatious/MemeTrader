from __future__ import annotations

from app.policies.base import (
    ActionProposal,
    ACTION_ADD_BUY,
    ACTION_EXIT_FULL,
    ACTION_HOLD,
    ACTION_PROBE_BUY,
    ACTION_SCALE_OUT_20,
)
from app.orchestrator.state_machine import (
    STATE_COOLDOWN,
    STATE_PROBE,
    STATE_SCOUT,
    STATE_TRADE,
    can_reenter,
    clear_pending_breakout,
    infer_interval_sec,
    update_reentry_lockout,
)


def propose_action(snapshot, state, config: dict) -> ActionProposal:
    engine_cfg = config.get("engine", {})
    rules_cfg = config.get("rules", {})
    risk_cfg = config.get("risk", {})
    reentry_cfg = config.get("reentry", {})
    stops_cfg = config.get("stops", {})

    expires_at = int(snapshot.now_ts + engine_cfg.get("poll_interval_sec", 1))
    guards = {"max_slippage_bps": int(risk_cfg.get("max_slippage_bps", 0))}

    if state.status == STATE_COOLDOWN:
        return ActionProposal(action=ACTION_HOLD, reason_codes=["COOLDOWN"], guards=guards, expires_at=expires_at)

    if state.status == STATE_SCOUT:
        interval_sec = infer_interval_sec(snapshot.candles)
        update_reentry_lockout(
            state,
            snapshot.now_ts,
            config,
            interval_sec,
            now_index=snapshot.candle_index,
        )
        features = snapshot.features
        breakout_strict = bool(features.get("breakout_strict", features.get("breakout")))
        range_compressed = bool(features.get("range_compressed", False))
        price_expanded = bool(features.get("price_expanded", False))
        chain_override = bool(features.get("chain_override", False))
        missing_reasons = []
        if not range_compressed:
            missing_reasons.append("NO_RANGE_COMPRESSION")
        if not price_expanded:
            missing_reasons.append("NO_PRICE_EXPANSION")
        current_index = snapshot.candle_index
        if state.pending_breakout_index is not None:
            if current_index is None:
                clear_pending_breakout(state)
            else:
                expires = state.pending_breakout_expires_index
                if expires is not None and current_index > expires:
                    clear_pending_breakout(state)
                    return ActionProposal(
                        action=ACTION_HOLD,
                        reason_codes=["BREAKOUT_EXPIRED"],
                        guards=guards,
                        expires_at=expires_at,
                    )

                level = state.pending_breakout_level
                if level is None:
                    clear_pending_breakout(state)
                    return ActionProposal(
                        action=ACTION_HOLD,
                        reason_codes=["BREAKOUT_EXPIRED"],
                        guards=guards,
                        expires_at=expires_at,
                    )

                close = snapshot.last_close
                low = snapshot.last_low
                confirm_close_above = float(rules_cfg.get("confirm_min_close_above_pct", 0.01))
                confirm_max_retrace = float(rules_cfg.get("confirm_max_retrace_pct", 0.05))

                confirm_close = close >= level * (1.0 + confirm_close_above)
                confirm_retrace_ok = low >= level * (1.0 - confirm_max_retrace)

                if close > level and confirm_close and confirm_retrace_ok:
                    clear_pending_breakout(state)
                    return ActionProposal(
                        action=ACTION_PROBE_BUY,
                        reason_codes=["BREAKOUT_CONFIRM"],
                        guards=guards,
                        expires_at=expires_at,
                    )

                return ActionProposal(
                    action=ACTION_HOLD,
                    reason_codes=["BREAKOUT_WAIT"],
                    guards=guards,
                    expires_at=expires_at,
                )

        if breakout_strict:
            avg_vol = float(snapshot.features.get("avg_volume", 0.0))
            current_vol = float(snapshot.candles[-1].v) if snapshot.candles else 0.0
            vol_mult = float(reentry_cfg.get("vol_mult_unlock", 0.0))
            vol_ok = False
            if vol_mult > 0 and avg_vol > 0:
                vol_ok = current_vol > (vol_mult * avg_vol)
            if not can_reenter(
                snapshot.now_ts,
                state.last_exit_ts,
                state.last_exit_index,
                state.last_exit_price,
                snapshot.last_close,
                config,
                vol_ok=vol_ok,
                last_exit_was_stop=state.last_exit_was_stop,
                interval_sec=interval_sec,
                now_index=snapshot.candle_index,
            ):
                return ActionProposal(
                    action=ACTION_HOLD,
                    reason_codes=["REENTRY_LOCKOUT"],
                    guards=guards,
                    expires_at=expires_at,
                )
            if current_index is None:
                return ActionProposal(
                    action=ACTION_PROBE_BUY,
                    reason_codes=["BREAKOUT"],
                    guards=guards,
                    expires_at=expires_at,
                )

            state.pending_breakout_index = current_index
            state.pending_breakout_level = float(snapshot.features.get("highest_close", snapshot.last_close))
            state.pending_breakout_expires_index = current_index + 3
            return ActionProposal(
                action=ACTION_HOLD,
                reason_codes=["BREAKOUT_PENDING"],
                guards=guards,
                expires_at=expires_at,
            )
        if chain_override:
            if not can_reenter(
                snapshot.now_ts,
                state.last_exit_ts,
                state.last_exit_index,
                state.last_exit_price,
                snapshot.last_close,
                config,
                vol_ok=False,
                last_exit_was_stop=state.last_exit_was_stop,
                interval_sec=interval_sec,
                now_index=snapshot.candle_index,
            ):
                return ActionProposal(
                    action=ACTION_HOLD,
                    reason_codes=["REENTRY_LOCKOUT"],
                    guards=guards,
                    expires_at=expires_at,
                )
            return ActionProposal(
                action=ACTION_PROBE_BUY,
                reason_codes=missing_reasons + ["PROVISIONAL_CHAIN_OVERRIDE"],
                guards=guards,
                expires_at=expires_at,
            )

        if not missing_reasons:
            missing_reasons = ["NO_PRICE_EXPANSION"]
        return ActionProposal(action=ACTION_HOLD, reason_codes=missing_reasons, guards=guards, expires_at=expires_at)

    if state.status == STATE_PROBE:
        progress_cfg = rules_cfg.get("progress", {})
        entry_price = state.entry_price or state.probe_entry_price
        if entry_price:
            if state.max_favorable_price is None:
                state.max_favorable_price = entry_price
            state.max_favorable_price = max(state.max_favorable_price, snapshot.last_close)

            min_move = float(progress_cfg.get("min_move_pct", 0.0))
            max_wait = int(progress_cfg.get("max_wait_candles", 0))
            if not state.progress_hit and snapshot.last_high >= entry_price * (1.0 + min_move):
                state.progress_hit = True
            if not state.progress_hit:
                deadline = state.progress_deadline_index
                if deadline is None and state.entry_index is not None and max_wait > 0:
                    deadline = state.entry_index + max_wait
                    state.progress_deadline_index = deadline
                if deadline is not None and snapshot.candle_index is not None and snapshot.candle_index >= deadline:
                    return ActionProposal(
                        action=ACTION_EXIT_FULL,
                        reason_codes=["PROGRESS_STOP"],
                        guards=guards,
                        expires_at=expires_at,
                    )
            else:
                stop_level = None
                if bool(progress_cfg.get("breakeven_after_progress", False)):
                    stop_level = entry_price
                if bool(progress_cfg.get("trail_after_progress", False)):
                    lookback_lows = int(progress_cfg.get("trail_lookback_lows", 1))
                    if lookback_lows > 0 and len(snapshot.candles) >= lookback_lows + 1:
                        lows = [float(c.l) for c in snapshot.candles[-(lookback_lows + 1) : -1]]
                        if lows:
                            trail_low = min(lows)
                            stop_level = max(stop_level, trail_low) if stop_level is not None else trail_low
                if stop_level is not None and snapshot.last_close < stop_level:
                    return ActionProposal(
                        action=ACTION_EXIT_FULL,
                        reason_codes=["TRAIL_STOP"],
                        guards=guards,
                        expires_at=expires_at,
                    )

        stop_buffer = float(stops_cfg.get("stop_buffer_pct", 0.0))
        if state.probe_entry_low is not None:
            stop_level = state.probe_entry_low * (1.0 - stop_buffer)
            if snapshot.last_close < stop_level:
                return ActionProposal(
                    action=ACTION_EXIT_FULL,
                    reason_codes=["STRUCT_STOP"],
                    guards=guards,
                    expires_at=expires_at,
                )
        add_trigger = float(rules_cfg.get("add_trigger_up_pct", 0.0))
        if state.probe_entry_price and state.probe_entry_low is not None:
            threshold = state.probe_entry_price * (1.0 + add_trigger)
            if snapshot.last_close >= threshold and snapshot.last_close > state.probe_entry_low:
                return ActionProposal(
                    action=ACTION_ADD_BUY,
                    reason_codes=["ADD_TRIGGER"],
                    guards=guards,
                    expires_at=expires_at,
                )
        return ActionProposal(action=ACTION_HOLD, reason_codes=["WAIT_ADD"], guards=guards, expires_at=expires_at)

    if state.status == STATE_TRADE:
        progress_cfg = rules_cfg.get("progress", {})
        entry_price = state.entry_price or state.probe_entry_price
        if entry_price:
            if state.max_favorable_price is None:
                state.max_favorable_price = entry_price
            state.max_favorable_price = max(state.max_favorable_price, snapshot.last_close)

            min_move = float(progress_cfg.get("min_move_pct", 0.0))
            max_wait = int(progress_cfg.get("max_wait_candles", 0))
            if not state.progress_hit and snapshot.last_high >= entry_price * (1.0 + min_move):
                state.progress_hit = True
            if not state.progress_hit:
                deadline = state.progress_deadline_index
                if deadline is None and state.entry_index is not None and max_wait > 0:
                    deadline = state.entry_index + max_wait
                    state.progress_deadline_index = deadline
                if deadline is not None and snapshot.candle_index is not None and snapshot.candle_index >= deadline:
                    return ActionProposal(
                        action=ACTION_EXIT_FULL,
                        reason_codes=["PROGRESS_STOP"],
                        guards=guards,
                        expires_at=expires_at,
                    )
            else:
                stop_level = None
                if bool(progress_cfg.get("breakeven_after_progress", False)):
                    stop_level = entry_price
                if bool(progress_cfg.get("trail_after_progress", False)):
                    lookback_lows = int(progress_cfg.get("trail_lookback_lows", 1))
                    if lookback_lows > 0 and len(snapshot.candles) >= lookback_lows + 1:
                        lows = [float(c.l) for c in snapshot.candles[-(lookback_lows + 1) : -1]]
                        if lows:
                            trail_low = min(lows)
                            stop_level = max(stop_level, trail_low) if stop_level is not None else trail_low
                if stop_level is not None and snapshot.last_close < stop_level:
                    return ActionProposal(
                        action=ACTION_EXIT_FULL,
                        reason_codes=["TRAIL_STOP"],
                        guards=guards,
                        expires_at=expires_at,
                    )

        stop_buffer = float(stops_cfg.get("stop_buffer_pct", 0.0))
        if state.probe_entry_low is not None:
            stop_level = state.probe_entry_low * (1.0 - stop_buffer)
            if snapshot.last_close < stop_level:
                return ActionProposal(
                    action=ACTION_EXIT_FULL,
                    reason_codes=["STRUCT_STOP"],
                    guards=guards,
                    expires_at=expires_at,
                )
        time_stop = int(rules_cfg.get("time_stop_candles", 0))
        if time_stop:
            if snapshot.candle_index is not None and state.entry_index is not None:
                if (snapshot.candle_index - state.entry_index) >= time_stop:
                    return ActionProposal(
                        action=ACTION_EXIT_FULL,
                        reason_codes=["TIME_STOP"],
                        guards=guards,
                        expires_at=expires_at,
                    )
            elif state.time_in_trade >= time_stop:
                return ActionProposal(
                    action=ACTION_EXIT_FULL,
                    reason_codes=["TIME_STOP"],
                    guards=guards,
                    expires_at=expires_at,
                )

        if snapshot.support_level and snapshot.last_close < snapshot.support_level.low:
            return ActionProposal(
                action=ACTION_EXIT_FULL,
                reason_codes=["SUPPORT_BREAK"],
                guards=guards,
                expires_at=expires_at,
            )

        levels = snapshot.resistance_levels
        if levels:
            if state.scale_out_stage == 0 and len(levels) >= 1 and snapshot.last_close >= levels[0].low:
                return ActionProposal(
                    action=ACTION_SCALE_OUT_20,
                    reason_codes=["R1_TOUCH"],
                    guards=guards,
                    expires_at=expires_at,
                )
            if state.scale_out_stage == 1 and len(levels) >= 2 and snapshot.last_close >= levels[1].low:
                return ActionProposal(
                    action=ACTION_SCALE_OUT_20,
                    reason_codes=["R2_TOUCH"],
                    guards=guards,
                    expires_at=expires_at,
                )
            if state.scale_out_stage >= 2 and len(levels) >= 3 and snapshot.last_close >= levels[2].low:
                return ActionProposal(
                    action=ACTION_EXIT_FULL,
                    reason_codes=["R3_TOUCH"],
                    guards=guards,
                    expires_at=expires_at,
                )

        return ActionProposal(action=ACTION_HOLD, reason_codes=["HOLD_TRADE"], guards=guards, expires_at=expires_at)

    return ActionProposal(action=ACTION_HOLD, reason_codes=["DEFAULT_HOLD"], guards=guards, expires_at=expires_at)
