import json
from pathlib import Path

from app.backtest.simulate import run_backtest
from app.config import get_config


def _write_mock_jsonl(path: Path, rows: int = 80) -> None:
    price = 1.0
    with path.open("w", encoding="utf-8") as handle:
        for i in range(rows):
            if i == 40:
                price *= 1.2
            else:
                price *= 1.005
            candle = {
                "t": 1700000000 + i * 60,
                "o": price * 0.99,
                "h": price * 1.01,
                "l": price * 0.98,
                "c": price,
                "v": 1000 + (i * 5),
            }
            handle.write(json.dumps(candle) + "\n")


def test_backtest_smoke(tmp_path: Path):
    data_dir = tmp_path / "dataset"
    data_dir.mkdir()
    file_path = data_dir / "pair1.jsonl"
    _write_mock_jsonl(file_path)

    cfg = get_config(refresh=True)
    out_dir = run_backtest(data_dir, config=cfg, max_pairs=1, output_base=tmp_path / "out")

    summary = out_dir / "summary.json"
    assert summary.exists()

    trades_csv = list(out_dir.glob("trades_*.csv"))
    assert trades_csv
