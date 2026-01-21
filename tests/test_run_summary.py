import asyncio
import json
from pathlib import Path

import httpx
from app.config import get_config
from app.data.client import MockApiClient
from app.orchestrator.runner import run_engine
from mock_api.server import app, reset_metrics


def test_run_summary_written_with_no_trades(tmp_path: Path):
    reset_metrics()
    cfg = get_config(refresh=True)
    cfg["mock_api_base"] = "http://test"

    async def _run() -> str:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as async_client:
            client = MockApiClient(base_url="http://test", async_client=async_client)
            return await run_engine(
                iterations=1,
                config=cfg,
                client=client,
                log_dir=str(tmp_path),
                max_tokens=0,
                sleep=False,
            )

    run_dir = asyncio.run(_run())
    summary_path = Path(run_dir) / "run_summary.json"
    assert summary_path.exists()

    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    assert summary["run_id"]
    assert summary["timestamp"]
    assert summary["provider_modes"]["market"] == "mock"
    assert summary["provider_modes"]["chain"] == "mock"
    assert summary["universe_size"] >= summary["candidate_count"]
    assert summary["candidate_count"] == 0
    assert summary["action_counts"] == {}
    assert summary["why_no_trades"]["no_actions"] is True
