import json
from pathlib import Path

import httpx
import pytest

from app.config import get_config
from app.data.client import MockApiClient
from app.data.jupiter.provider import MockJupiterProvider
from app.data.jupiter.service import JupiterSwapService, TRADING_MODE_CONFIRM
from app.orchestrator.runner import run_engine
from mock_api.server import app, reset_metrics


@pytest.mark.asyncio
async def test_runner_writes_jupiter_artifacts(tmp_path: Path):
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
        swap_service = JupiterSwapService(
            provider=MockJupiterProvider(),
            trading_mode=TRADING_MODE_CONFIRM,
        )
        run_dir = await run_engine(
            iterations=240,
            config=cfg,
            client=client,
            log_dir=str(tmp_path),
            max_tokens=1,
            swap_service=swap_service,
            sleep=False,
        )

    run_path = Path(run_dir)
    quote_previews = run_path / "quote_previews.jsonl"
    execution_plans = run_path / "execution_plans.jsonl"
    assert quote_previews.exists()
    assert execution_plans.exists()

    with quote_previews.open("r", encoding="utf-8") as handle:
        lines = [json.loads(line) for line in handle if line.strip()]
    assert lines
    assert lines[0]["quote"]

    with execution_plans.open("r", encoding="utf-8") as handle:
        lines = [json.loads(line) for line in handle if line.strip()]
    assert lines
    assert lines[0]["status"] in {"needs_signature", "submitted"}
