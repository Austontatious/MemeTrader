import json
from pathlib import Path

import httpx
import pytest

from app.config import get_config
from app.data.client import MockApiClient
from app.data.helius.provider import MockHeliusProvider
from app.orchestrator.runner import run_engine
from mock_api.server import app, reset_metrics


@pytest.mark.asyncio
async def test_e2e_mock_api(tmp_path: Path):
    reset_metrics()
    cfg = get_config(refresh=True)
    cfg["mock_api_base"] = "http://test"
    cfg["rules"]["breakout_lookback"] = 1
    cfg["rules"]["add_trigger_up_pct"] = 0.01
    cfg["rules"]["time_stop_candles"] = 3
    cfg["rules"]["confirm_min_close_above_pct"] = 0.0
    cfg["rules"]["confirm_max_retrace_pct"] = 0.10
    cfg["rules"]["momentum_lookback"] = 1
    cfg["engine"]["cooldown_candles"] = 5

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as async_client:
        client = MockApiClient(base_url="http://test", async_client=async_client)
        chain_provider = MockHeliusProvider()
        run_dir = await run_engine(
            iterations=240,
            config=cfg,
            client=client,
            log_dir=str(tmp_path),
            max_tokens=3,
            chain_provider=chain_provider,
            sleep=False,
        )

    metrics = app.state.metrics
    assert metrics["dex_candidates"] > 0
    assert metrics["dex_pair"] > 0
    assert metrics["birdeye_ohlcv"] > 0
    assert metrics["jupiter_quote"] > 0
    assert metrics["jupiter_build"] > 0

    trade_log = Path(run_dir) / "trades.jsonl"
    assert trade_log.exists()
    decisions_log = Path(run_dir) / "decisions.jsonl"
    summary_path = Path(run_dir) / "run_summary.json"
    assert decisions_log.exists()
    assert decisions_log.stat().st_size > 0
    assert summary_path.exists()
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    assert summary["candidate_count"] > 0
    assert summary["top_ranked"]

    decisions_by_symbol = {}
    with decisions_log.open("r", encoding="utf-8") as handle:
        for line in handle:
            record = json.loads(line)
            symbol = record.get("symbol")
            if symbol:
                decisions_by_symbol.setdefault(symbol, []).append(record)

    for symbol in ("WIN_PERFECT", "WIN_COMPLEX", "FAKE_HEADFAKE"):
        assert symbol in decisions_by_symbol

    win_perfect_actions = {record.get("decision") for record in decisions_by_symbol["WIN_PERFECT"]}
    assert win_perfect_actions.intersection({"PROBE_BUY", "ADD_BUY"})

    fake_actions = {record.get("decision") for record in decisions_by_symbol["FAKE_HEADFAKE"]}
    assert not fake_actions.intersection({"PROBE_BUY", "ADD_BUY"})
    assert any(
        any(reason in {"LIQUIDITY_RISK", "NET_OUTFLOW", "DEAD_AFTER_SPIKE"} for reason in record.get("reasons", []))
        for record in decisions_by_symbol["FAKE_HEADFAKE"]
    )
    assert any(
        "PROVISIONAL_CHAIN_OVERRIDE" in record.get("reasons", [])
        for record in decisions_by_symbol["WIN_COMPLEX"]
    )
    assert not any(
        "PROVISIONAL_CHAIN_OVERRIDE" in record.get("reasons", [])
        for record in decisions_by_symbol["FAKE_HEADFAKE"]
    )

    last_records = {symbol: records[-1] for symbol, records in decisions_by_symbol.items()}
    assert last_records["WIN_COMPLEX"]["score"] > last_records["FAKE_HEADFAKE"]["score"]
    assert "LIQUIDITY_RISK" not in last_records["WIN_COMPLEX"].get("reasons", [])
    for symbol in ("WIN_PERFECT", "WIN_COMPLEX", "FAKE_HEADFAKE"):
        assert last_records[symbol].get("token_mint")
        assert last_records[symbol].get("pair_id")

    actions = []
    with trade_log.open("r", encoding="utf-8") as handle:
        for line in handle:
            record = json.loads(line)
            actions.append(record.get("action"))
            assert "pair_id" in record
            assert "token_mint" in record
            assert "price_usd" in record
            assert "reason_codes" in record

    assert "PROBE_BUY" in actions
