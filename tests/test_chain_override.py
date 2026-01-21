from app.data.mock_schemas import Candle, PairStats
from app.orchestrator.runner import _apply_chain_override_flags
from app.orchestrator.snapshot import build_snapshot
from app.orchestrator.state_machine import STATE_SCOUT, TokenState
from app.policies.base import ACTION_PROBE_BUY
from app.policies.rules_v0 import propose_action


def _cfg():
    return {
        "engine": {"poll_interval_sec": 1},
        "rules": {
            "add_trigger_up_pct": 0.10,
            "time_stop_candles": 120,
            "breakout_lookback": 3,
            "confirm_max_retrace_pct": 0.05,
            "confirm_min_close_above_pct": 0.01,
            "momentum_lookback": 3,
        },
        "risk": {"max_slippage_bps": 150},
        "stops": {"stop_buffer_pct": 0.15},
        "reentry": {"lockout_candles": 1500, "min_breakout_pct": 0.10, "vol_mult_unlock": 2.0},
        "breakout": {
            "compression_max_range_ratio": 1.20,
            "compression_lookback_bars": 3,
            "expansion_min_pct": 0.06,
            "expansion_reference": "highest_close",
            "chain_override_enabled": True,
            "chain_override_min_tx_velocity_per_min": 6.0,
            "chain_override_min_swap_count": 20,
            "chain_override_min_net_native": 2.0,
            "chain_override_min_liquidity_events": 1,
        },
    }


def _make_candles(closes):
    candles = []
    for idx, close in enumerate(closes):
        candles.append(
            Candle(
                t=1_700_000_000 + idx * 60,
                o=close * 0.995,
                h=close * 1.01,
                l=close * 0.99,
                c=close,
                v=100.0 + idx,
            )
        )
    return candles


def test_chain_override_allows_provisional_candidate():
    cfg = _cfg()
    candles = _make_candles([1.00, 1.01, 1.02, 1.03])
    pair = PairStats(
        pair_id="PAIR1",
        token_mint="TOKEN1",
        price_usd=1.03,
        liquidity_usd=100000.0,
        volume_5m=1000.0,
        txns_5m=10,
    )
    chain_features = {
        "chain_tx_velocity_per_min": 10.0,
        "chain_swap_count": 30,
        "chain_net_native": 5.0,
        "chain_liquidity_events": 2,
    }
    snapshot = build_snapshot(pair, candles, cfg, candle_index=len(candles) - 1, extra_features=chain_features)
    _apply_chain_override_flags(snapshot, chain_features, cfg)
    state = TokenState(status=STATE_SCOUT)

    proposal = propose_action(snapshot, state, cfg)

    assert proposal.action == ACTION_PROBE_BUY
    assert "PROVISIONAL_CHAIN_OVERRIDE" in proposal.reason_codes
    assert any(reason in {"NO_RANGE_COMPRESSION", "NO_PRICE_EXPANSION"} for reason in proposal.reason_codes)
