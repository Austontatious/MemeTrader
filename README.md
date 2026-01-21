# MemeTrader

Headless memecoin trading engine (Arena-without-Arena) with a local mock API, deterministic signal pipeline, and offline backtest runner. No real trading, keys, or wallet integration.

## Quickstart

```bash
cd /mnt/data/MemeTrader
source .venv/bin/activate

# 1) run tests
pytest -q

# 2) E2E mock run
python -m app.main mock-e2e

# 3) HF backtest (requires token in /mnt/data/Lex/.env)
python -m app.main hf-backtest
```

## Notes

- Mock APIs simulate DexScreener/Birdeye/Jupiter endpoints.
- Engine writes JSONL trade plans to `runs/<timestamp>/trades.jsonl`.
- Backtests write summary metrics to `backtests/<timestamp>/summary.json`.
- No real network calls besides Hugging Face dataset download.
