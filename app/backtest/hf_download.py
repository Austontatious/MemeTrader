from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from dotenv import dotenv_values
from huggingface_hub import snapshot_download

from app.config import repo_root

TOKEN_KEYS = ["HF_TOKEN", "HUGGINGFACE_TOKEN", "HUGGINGFACEHUB_API_TOKEN"]
DATA_SUFFIXES = (".jsonl", ".jsonl.gz", ".parquet", ".json", ".csv")


def _has_data_files(path: Path) -> bool:
    for root, _, files in os.walk(path):
        for name in files:
            if name.endswith(DATA_SUFFIXES):
                return True
    return False


def _read_hf_token(env_path: Path) -> str:
    for key in TOKEN_KEYS:
        token = os.getenv(key)
        if token:
            return str(token).strip()

    if env_path.exists():
        values = dotenv_values(env_path)
        for key in TOKEN_KEYS:
            token = values.get(key)
            if token:
                return str(token).strip()

    raise ValueError(
        "Hugging Face token not found. Set HF_TOKEN/HUGGINGFACE_TOKEN/HUGGINGFACEHUB_API_TOKEN "
        "or add one to /mnt/data/Lex/.env"
    )


def ensure_dataset(local_dir: Optional[Path] = None) -> Path:
    root = repo_root()
    target_dir = local_dir or (root / "data" / "hf" / "solana-pairs-history")
    target_dir.mkdir(parents=True, exist_ok=True)

    if _has_data_files(target_dir):
        return target_dir

    token = _read_hf_token(Path("/mnt/data/Lex/.env"))
    snapshot_download(
        repo_id="horenresearch/solana-pairs-history",
        repo_type="dataset",
        token=token,
        local_dir=str(target_dir),
    )
    return target_dir
