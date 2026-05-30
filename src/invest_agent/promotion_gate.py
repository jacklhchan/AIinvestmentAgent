from __future__ import annotations

from datetime import timedelta
from typing import Any

from .config import Settings
from .models import InvestorCommitteeRun, Signal, SignalSide, SignalStatus, utc_now
from .store import Store


BLOCKING_COMMITTEE_STANCES = {"blocked", "research_more", "oppose", "watch"}
PROMOTABLE_SIGNAL_SIDES = {
    SignalSide.BUY_SIGNAL,
    SignalSide.ADD_SIGNAL,
    SignalSide.SELL_SIGNAL,
    SignalSide.REDUCE_SIGNAL,
}


class PromotionGateService:
    """Single promotion gate shared by API, CLI, MCP, dashboard and SignalEngine."""

    def __init__(self, settings: Settings, store: Store):
        self.settings = settings
        self.store = store

    def evaluate(self, signal: Signal, committee: InvestorCommitteeRun | None = None) -> dict[str, Any]:
        reasons: list[str] = []
        if signal.status != SignalStatus.ACTIVE:
            reasons.append(f"signal is {signal.status.value}, not active")
        if signal.side not in PROMOTABLE_SIGNAL_SIDES:
            blocked_action = signal.gates.get("blocked_action")
            detail = f" for {blocked_action}" if blocked_action else ""
            reasons.append(f"signal is {signal.side.value}{detail}; it cannot be promoted until gates pass")
        if signal.suggested_qty <= 0 or not signal.suggested_limit_price:
            reasons.append("signal has no promotable quantity or limit price")
        if signal.gates.get("proposal_allowed") is False or signal.gates.get("blocking_reasons"):
            reasons.extend(str(item) for item in signal.gates.get("blocking_reasons", [])[:6])

        committee = committee or self._latest_committee(signal)
        committee_fresh = False
        if committee is None:
            reasons.append("fresh investor committee run required before promotion")
        else:
            max_age = timedelta(minutes=max(1, self.settings.paper_advice_committee_freshness_minutes))
            committee_fresh = utc_now() - committee.created_at <= max_age
            if not committee_fresh:
                reasons.append("fresh investor committee run required before promotion; latest run is stale")
            if committee.committee_blocked:
                reasons.append(f"committee blocked promotion: {', '.join(committee.vetoes) or committee.final_stance}")
            if committee.final_stance in BLOCKING_COMMITTEE_STANCES:
                reasons.append(f"committee final stance {committee.final_stance} blocks promotion")
            threshold = directional_threshold(self.settings, signal)
            if committee.committee_adjusted_score < threshold:
                reasons.append(
                    f"committee adjusted score {committee.committee_adjusted_score:.1f} below directional threshold {threshold}"
                )

        return {
            "ok": not reasons,
            "reasons": list(dict.fromkeys(reasons)),
            "committee_run_id": committee.id if committee else None,
            "committee_fresh": committee_fresh,
            "committee_adjusted_score": committee.committee_adjusted_score if committee else None,
            "committee_final_stance": committee.final_stance if committee else None,
            "directional_threshold": directional_threshold(self.settings, signal),
        }

    def require(self, signal: Signal, committee: InvestorCommitteeRun | None = None) -> InvestorCommitteeRun:
        result = self.evaluate(signal, committee)
        if not result["ok"]:
            raise ValueError("; ".join(result["reasons"]))
        committee_id = result["committee_run_id"]
        selected = committee if committee and committee.id == committee_id else self._latest_committee(signal)
        if selected is None:
            raise ValueError("fresh investor committee run required before promotion")
        return selected

    def _latest_committee(self, signal: Signal) -> InvestorCommitteeRun | None:
        runs = self.store.list_investor_committee_runs(signal_id=signal.id, limit=1)
        return runs[0] if runs else None


def directional_threshold(settings: Settings, signal: Signal) -> int:
    action = signal.gates.get("blocked_action") or signal.side.value
    if action in {SignalSide.SELL_SIGNAL.value, SignalSide.REDUCE_SIGNAL.value}:
        return settings.signal_sell_threshold
    return settings.signal_buy_threshold
