from __future__ import annotations

from typing import List

from app.orchestrator.risk import estimate_slippage_bps
from app.policies.base import ActionProposal, ACTION_ADD_BUY, ACTION_EXIT_FULL, ACTION_HOLD, ACTION_PROBE_BUY, ACTION_SCALE_OUT_20


def _action_notional_usd(action: str, state, config: dict) -> float:
    positioning = config.get("positioning", {})
    capital = float(positioning.get("capital_usd", 0.0))
    if action == ACTION_PROBE_BUY:
        return capital * float(positioning.get("probe_pct", 0.0))
    if action == ACTION_ADD_BUY:
        return capital * float(positioning.get("add_pct", 0.0))
    if action == ACTION_SCALE_OUT_20:
        if state.scale_out_stage == 0:
            scale_pct = float(positioning.get("tp1_scale_out_pct", 0.0))
        else:
            scale_pct = float(positioning.get("tp2_scale_out_pct", 0.0))
        return state.position_usd * scale_pct
    if action == ACTION_EXIT_FULL:
        return state.position_usd
    return 0.0


def validate_action(proposal: ActionProposal, snapshot, state, config: dict) -> ActionProposal:
    if proposal.action == ACTION_HOLD:
        return proposal

    rejected: List[str] = []
    risk_cfg = config.get("risk", {})

    if state.status == "COOLDOWN":
        rejected.append("COOLDOWN")

    liquidity = float(snapshot.pair.liquidity_usd)
    min_liquidity = float(risk_cfg.get("min_liquidity_usd", 0.0))
    if liquidity < min_liquidity:
        rejected.append("LOW_LIQUIDITY")

    if proposal.action in {ACTION_SCALE_OUT_20, ACTION_EXIT_FULL} and state.position_usd <= 0:
        rejected.append("NO_POSITION")

    notional = _action_notional_usd(proposal.action, state, config)
    slippage_bps = estimate_slippage_bps(notional, liquidity)
    max_slippage = float(risk_cfg.get("max_slippage_bps", 0.0))
    if slippage_bps > max_slippage:
        rejected.append("SLIPPAGE_TOO_HIGH")

    if rejected:
        return ActionProposal(
            action=ACTION_HOLD,
            reason_codes=[f"REJECT_{code}" for code in rejected],
            guards=proposal.guards,
            expires_at=proposal.expires_at,
        )

    return proposal
