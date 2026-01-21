from app.data.mock_schemas import Candle, PairStats, Snapshot
from app.orchestrator.state_machine import STATE_PROBE, TokenState
from app.policies.base import ACTION_EXIT_FULL
from app.policies.rules_v0 import propose_action


def test_struct_stop_triggers_exit():
    cfg = {
        "engine": {"poll_interval_sec": 1},
        "rules": {"add_trigger_up_pct": 0.10, "time_stop_candles": 120},
        "risk": {"max_slippage_bps": 150},
        "stops": {"stop_buffer_pct": 0.0},
        "reentry": {"lockout_candles": 480, "min_breakout_pct": 0.10, "vol_mult_unlock": 2.0},
    }

    candle = Candle(t=1_700_000_000, o=1.0, h=1.0, l=0.8, c=0.9, v=1000)
    pair = PairStats(
        pair_id="PAIR1",
        token_mint="TOKEN1",
        price_usd=0.9,
        liquidity_usd=100000.0,
        volume_5m=1000.0,
        txns_5m=10,
    )
    snapshot = Snapshot(
        pair=pair,
        candles=[candle],
        features={"avg_volume": 1000.0, "breakout": False},
        regime_score=50,
        now_ts=candle.t,
        last_close=candle.c,
        last_low=candle.l,
        last_high=candle.h,
    )

    state = TokenState(status=STATE_PROBE, probe_entry_price=1.0, probe_entry_low=1.0)
    proposal = propose_action(snapshot, state, cfg)

    assert proposal.action == ACTION_EXIT_FULL
    assert "STRUCT_STOP" in proposal.reason_codes
