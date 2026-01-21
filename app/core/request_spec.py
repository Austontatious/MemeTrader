from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Dict, Iterable, Optional
from urllib.parse import urlencode


def _normalize_base(base_url: str) -> str:
    return base_url.rstrip("/")


def _normalize_path(path: str) -> str:
    if not path:
        return "/"
    if not path.startswith("/"):
        return f"/{path}"
    return path


def canonicalize_headers(headers: Dict[str, str]) -> Dict[str, str]:
    return {key.lower(): value for key, value in headers.items()}


def canonicalize_query(query: Dict[str, Any]) -> Dict[str, str]:
    normalized: Dict[str, str] = {}
    for key, value in query.items():
        if value is None:
            continue
        normalized[key] = str(value)
    return normalized


@dataclass(frozen=True)
class RequestSpec:
    method: str
    base_url: str
    path: str
    query: Dict[str, Any]
    headers: Dict[str, str]
    json: Optional[Dict[str, Any]] = None

    def normalized_headers(self) -> Dict[str, str]:
        return canonicalize_headers(self.headers)

    def normalized_query(self) -> Dict[str, str]:
        return canonicalize_query(self.query)

    def build_url(self, include_query: bool = True) -> str:
        base = _normalize_base(self.base_url)
        path = _normalize_path(self.path)
        url = f"{base}{path}"
        if include_query and self.query:
            query = urlencode(sorted(self.normalized_query().items()))
            if query:
                url = f"{url}?{query}"
        return url

    def fingerprint(self, required_headers: Optional[Iterable[str]] = None) -> str:
        header_keys = required_headers or self.headers.keys()
        header_keys_sorted = ",".join(sorted(key.lower() for key in header_keys))
        query_keys_sorted = ",".join(sorted(self.normalized_query().keys()))
        return f"{self.method} {self.base_url}{_normalize_path(self.path)} q={query_keys_sorted} h={header_keys_sorted}"

    def to_curl(self) -> str:
        parts = ["curl", "-X", self.method, f"'{self.build_url(include_query=True)}'"]
        for key, value in sorted(self.headers.items()):
            parts.append(f"-H '{key}: {value}'")
        if self.json is not None:
            body = json.dumps(self.json, separators=(",", ":"), sort_keys=True)
            parts.append(f"-d '{body}'")
        return " ".join(parts)


@dataclass(frozen=True)
class JsonRpcSpec:
    base_url: str
    path: str
    query: Dict[str, Any]
    headers: Dict[str, str]
    body: Dict[str, Any]

    def to_request_spec(self) -> RequestSpec:
        return RequestSpec(
            method="POST",
            base_url=self.base_url,
            path=self.path,
            query=self.query,
            headers=self.headers,
            json=self.body,
        )

    def canonical_payload(self) -> str:
        return json.dumps(self.body, separators=(",", ":"), sort_keys=True)


__all__ = [
    "JsonRpcSpec",
    "RequestSpec",
    "canonicalize_headers",
    "canonicalize_query",
]
