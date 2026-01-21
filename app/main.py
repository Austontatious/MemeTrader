from __future__ import annotations

import argparse
import asyncio
import os
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx

from app.backtest.hf_download import ensure_dataset
from app.backtest.simulate import run_backtest
from app.composition import build_providers
from app.config import get_config, repo_root
from app.orchestrator.runner import run_engine


def _normalize_provider_choice(choice: str | None, default: str) -> str:
    value = (choice or "").strip().lower()
    return value or default


def _probe_server(base_url: str) -> int | None:
    try:
        resp = httpx.get(f"{base_url}/dex/candidates", timeout=1)
        return resp.status_code
    except Exception:
        return None


def _tail_file(path: Path, max_lines: int = 20) -> str:
    if not path.exists():
        return ""
    try:
        with path.open("r", encoding="utf-8", errors="ignore") as handle:
            lines = handle.readlines()[-max_lines:]
        return "".join(lines).strip()
    except Exception:
        return ""


def _find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _wait_for_server(base_url: str, timeout_sec: int = 15, proc: subprocess.Popen | None = None, log_path: Path | None = None) -> None:
    deadline = time.time() + timeout_sec
    last_status = None
    while time.time() < deadline:
        if proc and proc.poll() is not None:
            break
        try:
            resp = httpx.get(f"{base_url}/dex/candidates", timeout=1)
            last_status = resp.status_code
            if last_status == 200:
                return
        except Exception:
            time.sleep(0.5)
    if proc and proc.poll() is not None:
        message = f"Mock API server exited with code {proc.returncode}"
    elif last_status is not None:
        message = f"Mock API server not ready (HTTP {last_status} from {base_url}/dex/candidates)"
    else:
        message = "Mock API server did not start in time"
    if log_path:
        tail = _tail_file(log_path)
        if tail:
            message = f"{message}\nMock API log tail:\n{tail}"
    raise RuntimeError(message)


def cmd_mock_e2e(market_choice: str | None = None, chain_choice: str | None = None) -> None:
    cfg = get_config(refresh=True)
    market_env = os.getenv("MARKET_DATA", "")
    chain_env = os.getenv("CHAIN_INTEL", "")
    market_mode = _normalize_provider_choice(market_choice or market_env, "birdeye")
    chain_mode = _normalize_provider_choice(chain_choice or chain_env, "helius")
    market_provider, chain_provider = build_providers(
        market_choice=market_mode,
        chain_choice=chain_mode,
    )
    base_url = cfg.get("mock_api_base", "http://127.0.0.1:18080")
    status = _probe_server(base_url)
    if status == 200:
        run_dir = asyncio.run(
            run_engine(
                iterations=240,
                config=cfg,
                sleep=False,
                market_provider=market_provider,
                chain_provider=chain_provider,
                market_mode=market_mode,
                chain_mode=chain_mode,
            )
        )
        print(f"Mock E2E run complete. Trade log: {Path(run_dir) / 'trades.jsonl'}")
        return
    port = 18080
    if status is not None:
        port = _find_free_port()
        base_url = f"http://127.0.0.1:{port}"
        cfg["mock_api_base"] = base_url
        print(f"Port 18080 in use (HTTP {status}); using {base_url} for mock API.")

    root = repo_root()
    env = os.environ.copy()
    env["PYTHONPATH"] = f"{root}{os.pathsep}{env.get('PYTHONPATH', '')}"
    log_file = tempfile.NamedTemporaryFile(prefix="mock_api_", suffix=".log", delete=False)
    log_path = Path(log_file.name)
    log_file.close()
    log_handle = log_path.open("w", encoding="utf-8")

    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "mock_api.server:app", "--host", "127.0.0.1", "--port", str(port)],
        stdout=log_handle,
        stderr=subprocess.STDOUT,
        cwd=str(root),
        env=env,
    )
    success = False
    try:
        _wait_for_server(base_url, proc=proc, log_path=log_path)
        run_dir = asyncio.run(
            run_engine(
                iterations=240,
                config=cfg,
                sleep=False,
                market_provider=market_provider,
                chain_provider=chain_provider,
                market_mode=market_mode,
                chain_mode=chain_mode,
            )
        )
        print(f"Mock E2E run complete. Trade log: {Path(run_dir) / 'trades.jsonl'}")
        success = True
    finally:
        log_handle.close()
        proc.terminate()
        proc.wait(timeout=5)
        if success and log_path.exists():
            log_path.unlink()


def cmd_hf_backtest(max_pairs: int, out_dir: str | None) -> None:
    dataset_dir = ensure_dataset()
    output_base = Path(out_dir) if out_dir else None
    run_dir = run_backtest(Path(dataset_dir), max_pairs=max_pairs, output_base=output_base)
    print(f"Backtest complete. Summary: {Path(run_dir) / 'summary.json'}")


def main() -> None:
    parser = argparse.ArgumentParser(description="MemeTrader CLI")
    parser.add_argument("command", choices=["mock-e2e", "hf-backtest"], help="Command to run")
    parser.add_argument("--max-pairs", type=int, default=25, help="Max pairs for hf-backtest")
    parser.add_argument("--out-dir", type=str, default=None, help="Output directory for hf-backtest")
    parser.add_argument("--market-data", type=str, default=None, help="Market data provider (birdeye|mock)")
    parser.add_argument("--chain-intel", type=str, default=None, help="Chain intel provider (helius|mock)")
    args = parser.parse_args()

    if args.command == "mock-e2e":
        cmd_mock_e2e(market_choice=args.market_data, chain_choice=args.chain_intel)
    elif args.command == "hf-backtest":
        cmd_hf_backtest(args.max_pairs, args.out_dir)


if __name__ == "__main__":
    main()
