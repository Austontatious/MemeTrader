from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional, Type, TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


def load_json_fixture(path: Path, expected_version: Optional[str] = None) -> Any:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if expected_version is None:
        return payload
    version = None
    if isinstance(payload, dict):
        version = payload.get("_fixture_version")
    if version is None:
        return payload
    if version != expected_version:
        raise ValueError(f"Fixture version mismatch: expected {expected_version}, got {version}")
    return payload


def load_fixture(base_dir: Path, name: str, expected_version: Optional[str] = None) -> Any:
    return load_json_fixture(base_dir / name, expected_version=expected_version)


def validate_fixture(model: Type[T], payload: Any) -> T:
    return model.model_validate(payload)


__all__ = ["load_fixture", "load_json_fixture", "validate_fixture"]
