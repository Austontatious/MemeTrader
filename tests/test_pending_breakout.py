from app.data.mock_schemas import Candle, PairStats, Snapshot
from app.orchestrator.state_machine import STATE_SCOUT, TokenState
from app.policies.base import ACTION_HOLD, ACTION_PROBE_BUY
from app.policies.rules_v0 import propose_action


def _make_snapshot(
    index: int,
    close: float,
    low: float,
    high: float,
    breakout: bool,
    highest_close: float,
    candles=None,
) -> Snapshot:
    candle = Candle(t=1_700_000_000 + index * 60, o=close, h=high, l=low, c=close, v=1000)
    candles = candles or [candle]
    pair = PairStats(
        pair_id="PAIR1",
        token_mint="TOKEN1",
        price_usd=close,
        liquidity_usd=100000.0,
        volume_5m=1000.0,
        txns_5m=10,
    )
    return Snapshot(
        pair=pair,
        candles=candles,
        features={"breakout": breakout, "highest_close": highest_close, "avg_volume": 1000.0},
        regime_score=50,
        now_ts=candle.t,
        candle_index=index,
        last_close=close,
        last_low=low,
        last_high=high,
    )


def _cfg():
    return {
        "engine": {"poll_interval_sec": 1},
        "rules": {
            "add_trigger_up_pct": 0.10,
            "time_stop_candles": 120,
            "breakout_lookback": 3,
            "confirm_max_retrace_pct": 0.05,
            "confirm_min_close_above_pct": 0.01,
        },
        "risk": {"max_slippage_bps": 150},
        "stops": {"stop_buffer_pct": 0.15},
        "reentry": {"lockout_candles": 1500, "min_breakout_pct": 0.10, "vol_mult_unlock": 2.0},
    }


def test_pending_breakout_sets_on_breakout_and_holds():
    cfg = _cfg()
    state = TokenState(status=STATE_SCOUT)
    snapshot = _make_snapshot(index=10, close=1.2, low=1.1, high=1.25, breakout=True, highest_close=1.0)

    proposal = propose_action(snapshot, state, cfg)

    assert proposal.action == ACTION_HOLD
    assert "BREAKOUT_PENDING" in proposal.reason_codes
    assert state.pending_breakout_index == 10
    assert state.pending_breakout_level == 1.0
    assert state.pending_breakout_expires_index == 13


def test_confirm_breakout_enters_on_next_bar():
    cfg = _cfg()
    state = TokenState(status=STATE_SCOUT)
    state.pending_breakout_index = 10
    state.pending_breakout_level = 1.0
    state.pending_breakout_expires_index = 13

    snapshot = _make_snapshot(
        index=11,
        close=1.08,
        low=0.97,
        high=1.1,
        breakout=False,
        highest_close=1.0,
    )
    proposal = propose_action(snapshot, state, cfg)

    assert proposal.action == ACTION_PROBE_BUY
    assert "BREAKOUT_CONFIRM" in proposal.reason_codes
    assert state.pending_breakout_index is None
    assert state.pending_breakout_level is None
    assert state.pending_breakout_expires_index is None


def test_pending_expires_if_no_confirm():
    cfg = _cfg()
    state = TokenState(status=STATE_SCOUT)
    state.pending_breakout_index = 10
    state.pending_breakout_level = 1.0
    state.pending_breakout_expires_index = 12

    snapshot = _make_snapshot(index=13, close=0.99, low=0.95, high=1.0, breakout=False, highest_close=1.0)
    proposal = propose_action(snapshot, state, cfg)

    assert proposal.action == ACTION_HOLD
    assert "BREAKOUT_EXPIRED" in proposal.reason_codes
    assert state.pending_breakout_index is None
    assert state.pending_breakout_level is None
    assert state.pending_breakout_expires_index is None


def test_confirm_fails_when_retrace_too_deep():
    cfg = _cfg()
    state = TokenState(status=STATE_SCOUT)
    state.pending_breakout_index = 10
    state.pending_breakout_level = 1.0
    state.pending_breakout_expires_index = 13

    snapshot = _make_snapshot(
        index=11,
        close=1.08,
        low=0.92,
        high=1.1,
        breakout=False,
        highest_close=1.0,
    )
    proposal = propose_action(snapshot, state, cfg)

    assert proposal.action == ACTION_HOLD
    assert "BREAKOUT_WAIT" in proposal.reason_codes
    assert state.pending_breakout_index == 10
