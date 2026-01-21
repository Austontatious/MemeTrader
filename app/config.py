from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict

import yaml
from dotenv import load_dotenv

_CONFIG_CACHE: Dict[str, Any] | None = None


def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def load_config(path: str | Path | None = None) -> Dict[str, Any]:
    root = repo_root()
    env_path = root / ".env"
    if env_path.exists():
        load_dotenv(env_path)

    config_path = Path(path) if path else Path(os.getenv("MEMETRADER_CONFIG", root / "config" / "default.yaml"))
    if not config_path.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")

    with config_path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}

    return data


def get_config(refresh: bool = False) -> Dict[str, Any]:
    global _CONFIG_CACHE
    if refresh or _CONFIG_CACHE is None:
        _CONFIG_CACHE = load_config()
    return _CONFIG_CACHE
