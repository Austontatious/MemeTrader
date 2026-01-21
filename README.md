# MemeTrader

Headless memecoin trading engine (Arena-without-Arena) with a local mock API, deterministic signal pipeline, and offline backtest runner. No real trading, keys, or wallet integration.

## Quickstart

```bash
cd /mnt/data/MemeTrader
source .venv/bin/activate
pytest -q
```

## Running mock-e2e

```bash
python3 -m app.main mock-e2e --market-data birdeye --chain-intel helius
```

## Artifacts

- `runs/<timestamp>/decisions.jsonl`: per-candidate decisions and features
- `runs/<timestamp>/run_summary.json`: run metadata and reason counts
- `runs/<timestamp>/trades.jsonl`: executed actions (may be empty)

## Modes

- Market provider: `--market-data birdeye|mock` or `MARKET_DATA=birdeye|mock`
- Chain provider: `--chain-intel helius|mock` or `CHAIN_INTEL=helius|mock`
- Trading mode: `TRADING_MODE=confirm|auto` (auto requires server signer config)

## Notes

- Mock APIs simulate DexScreener/Birdeye/Jupiter endpoints.
- Local-only data lives in `data/`, `runs/`, and `backtests/` (not committed).
- No real network calls besides Hugging Face dataset download.
