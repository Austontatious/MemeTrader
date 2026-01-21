from __future__ import annotations

from typing import Optional


class ProviderMisconfigured(RuntimeError):
    pass


class ProviderOffline(RuntimeError):
    pass


class UpstreamError(RuntimeError):
    def __init__(self, message: str, status_code: Optional[int] = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class UpstreamRateLimited(UpstreamError):
    pass


class UpstreamBadResponse(UpstreamError):
    pass
