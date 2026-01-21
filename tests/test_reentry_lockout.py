from app.data.mock_schemas import Candle
from app.orchestrator.state_machine import can_reenter, infer_interval_sec


def test_reentry_lockout_index_based():
    cfg = {"reentry": {"lockout_candles": 10, "min_breakout_pct": 0.10}}
    last_exit_index = 100
    last_exit_price = 100.0

    assert not can_reenter(
        now_ts=0,
        last_exit_ts=None,
        last_exit_index=last_exit_index,
        last_exit_price=last_exit_price,
        current_close=105.0,
        cfg=cfg,
        now_index=105,
    )
    assert can_reenter(
        now_ts=0,
        last_exit_ts=None,
        last_exit_index=last_exit_index,
        last_exit_price=last_exit_price,
        current_close=111.0,
        cfg=cfg,
        now_index=105,
    )
    assert can_reenter(
        now_ts=0,
        last_exit_ts=None,
        last_exit_index=last_exit_index,
        last_exit_price=last_exit_price,
        current_close=101.0,
        cfg=cfg,
        now_index=111,
    )


def test_infer_interval_sec_uses_median_spacing():
    candles = [
        Candle(t=1_000, o=1.0, h=1.0, l=1.0, c=1.0, v=1.0),
        Candle(t=1_300, o=1.0, h=1.0, l=1.0, c=1.0, v=1.0),
        Candle(t=1_600, o=1.0, h=1.0, l=1.0, c=1.0, v=1.0),
    ]
    assert infer_interval_sec(candles) == 300


def test_stop_loss_multiplier_blocks_reentry():
    cfg = {"reentry": {"lockout_candles": 10, "min_breakout_pct": 0.10}}
    last_exit_index = 100
    last_exit_price = 100.0

    assert not can_reenter(
        now_ts=0,
        last_exit_ts=None,
        last_exit_index=last_exit_index,
        last_exit_price=last_exit_price,
        current_close=105.0,
        cfg=cfg,
        now_index=120,
        last_exit_was_stop=True,
    )
    assert can_reenter(
        now_ts=0,
        last_exit_ts=None,
        last_exit_index=last_exit_index,
        last_exit_price=last_exit_price,
        current_close=111.0,
        cfg=cfg,
        now_index=120,
        last_exit_was_stop=True,
    )
    assert can_reenter(
        now_ts=0,
        last_exit_ts=None,
        last_exit_index=last_exit_index,
        last_exit_price=last_exit_price,
        current_close=101.0,
        cfg=cfg,
        now_index=131,
        last_exit_was_stop=True,
    )
