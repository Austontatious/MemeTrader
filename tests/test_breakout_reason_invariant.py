from app.config import get_config
from app.data.mock_schemas import Candle, PairStats, Snapshot
from app.orchestrator.state_machine import TokenState
from app.policies.rules_v0 import propose_action


def test_breakout_strict_excludes_missing_reasons() -> None:
    cfg = get_config(refresh=True)
    candles = [
        Candle(t=1700000000, o=1.0, h=1.02, l=0.99, c=1.01, v=120),
        Candle(t=1700000060, o=1.01, h=1.05, l=1.0, c=1.04, v=180),
    ]
    pair = PairStats(
        pair_id="PAIR_WIN_PERFECT",
        token_mint="MINT_WIN_PERFECT",
        price_usd=1.04,
        liquidity_usd=150000.0,
        volume_5m=300.0,
        txns_5m=3,
    )
    snapshot = Snapshot(
        pair=pair,
        candles=candles,
        features={
            "breakout_strict": True,
            "range_compressed": False,
            "price_expanded": False,
            "chain_override": True,
            "highest_close": 1.02,
        },
        now_ts=1700000060,
        candle_index=1,
        last_close=1.04,
        last_low=1.0,
        last_high=1.05,
    )
    state = TokenState()
    proposal = propose_action(snapshot, state, cfg)
    assert not any(
        reason in {"NO_RANGE_COMPRESSION", "NO_PRICE_EXPANSION", "PROVISIONAL_CHAIN_OVERRIDE"}
        for reason in proposal.reason_codes
    )
