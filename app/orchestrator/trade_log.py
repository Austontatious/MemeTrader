from __future__ import annotations

import json
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from rich.console import Console
from rich.table import Table

from app.config import repo_root


class TradeLogger:
    def __init__(self, base_dir: Optional[Path] = None) -> None:
        root = repo_root()
        base = Path(base_dir) if base_dir else root / "runs"
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        self.run_dir = base / timestamp
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self.path = self.run_dir / "trades.jsonl"
        self._file = self.path.open("a", encoding="utf-8")
        self._entries: List[Dict[str, Any]] = []

    def log(self, entry: Dict[str, Any]) -> None:
        self._entries.append(entry)
        self._file.write(json.dumps(entry) + "\n")
        self._file.flush()

    def summarize(self) -> None:
        counts = Counter(entry.get("action") for entry in self._entries)
        table = Table(title="Trade Plan Summary")
        table.add_column("Action")
        table.add_column("Count", justify="right")
        for action, count in counts.most_common():
            table.add_row(str(action), str(count))
        console = Console()
        console.print(table)

    def action_counts(self) -> Dict[str, int]:
        return dict(Counter(entry.get("action") for entry in self._entries))

    def close(self) -> None:
        self._file.close()
