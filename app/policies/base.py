from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

ACTION_HOLD = "HOLD"
ACTION_PROBE_BUY = "PROBE_BUY"
ACTION_ADD_BUY = "ADD_BUY"
ACTION_SCALE_OUT_20 = "SCALE_OUT_20"
ACTION_EXIT_FULL = "EXIT_FULL"


class ActionProposal(BaseModel):
    action: str
    reason_codes: List[str] = Field(default_factory=list)
    guards: Dict[str, Any] = Field(default_factory=dict)
    expires_at: Optional[int] = None


def hold(reason: str = "HOLD") -> ActionProposal:
    return ActionProposal(action=ACTION_HOLD, reason_codes=[reason])
