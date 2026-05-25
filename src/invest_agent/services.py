from __future__ import annotations

from datetime import timedelta

from fastapi import HTTPException

from .config import Settings
from .models import (
    ExecutionMode,
    ExecutionRecord,
    Proposal,
    ProposalCreate,
    ProposalStatus,
    ThesisPillarStatus,
    ThesisRiskStatus,
    ThesisSide,
    ThesisStatus,
    utc_now,
)
from .policy import RiskEngine
from .research_goals import compute_evidence_hash, evaluate_research_gate
from .store import Store


class InvestmentService:
    def __init__(self, settings: Settings, store: Store):
        self.settings = settings
        self.store = store
        self.risk = RiskEngine(settings, store)

    def create_proposal(self, request: ProposalCreate) -> Proposal:
        portfolio = self.store.get_portfolio()
        ttl = request.ttl_minutes or self.settings.approval_ttl_minutes
        risk_check = self.risk.check_create(request, portfolio)
        research_goal = None
        invariant_reasons: list[str] = []
        if self.settings.research_gate_required:
            research_goal, invariant_reasons = self._research_invariant_reasons(request)
        thesis_reasons = self._thesis_invariant_reasons(request)
        invariant_reasons.extend(thesis_reasons)
        if invariant_reasons:
            risk_check.passed = False
            risk_check.reasons.extend(invariant_reasons)
        status = ProposalStatus.PENDING if risk_check.passed else ProposalStatus.RISK_REJECTED
        evidence_hash = compute_evidence_hash(
            goal=research_goal,
            proposal_evidence=request.evidence,
            counter_evidence=request.counter_evidence,
            manual_override_reason=request.manual_override_reason,
            thesis_id=request.thesis_id,
        )
        proposal = Proposal(
            symbol=request.symbol,
            side=request.side,
            qty=request.qty,
            limit_price=request.limit_price,
            thesis=request.thesis,
            trigger=request.trigger,
            confidence=request.confidence,
            evidence=request.evidence,
            counter_evidence=request.counter_evidence,
            status=status,
            risk_check=risk_check,
            expires_at=utc_now() + timedelta(minutes=ttl),
            max_slippage_bps=request.max_slippage_bps or self.settings.max_price_drift_bps,
            execution_mode=ExecutionMode.PAPER if self.settings.is_paper else ExecutionMode.LIVE,
            research_goal_id=request.research_goal_id,
            manual_override_reason=request.manual_override_reason,
            evidence_hash=evidence_hash,
            thesis_id=request.thesis_id,
        )
        return self.store.create_proposal(proposal)

    def _research_invariant_reasons(self, request: ProposalCreate) -> tuple[object | None, list[str]]:
        if request.research_goal_id:
            goal = self.store.get_research_goal(request.research_goal_id)
            if not goal:
                return None, [f"research goal not found: {request.research_goal_id}"]
            if goal.symbol and goal.symbol != request.symbol:
                return goal, [f"research goal symbol {goal.symbol} does not match proposal symbol {request.symbol}"]
            gate = evaluate_research_gate(
                goal,
                max_verified_age_days=self.settings.research_gate_max_verified_age_days,
            )
            if not gate.passed:
                return goal, [f"research evidence gate failed: {'; '.join(gate.reasons)}"]
            return goal, []
        if request.manual_override_reason:
            return None, []
        return None, ["research gate required: provide research_goal_id or manual_override_reason"]

    def _thesis_invariant_reasons(self, request: ProposalCreate) -> list[str]:
        if not request.thesis_id:
            return []
        thesis = self.store.get_thesis(request.thesis_id)
        if not thesis:
            return [f"thesis not found: {request.thesis_id}"]
        if thesis.symbol != request.symbol:
            return [f"thesis symbol {thesis.symbol} does not match proposal symbol {request.symbol}"]
        reasons: list[str] = []
        if thesis.status in {ThesisStatus.INVALIDATED, ThesisStatus.ARCHIVED}:
            reasons.append(f"thesis status is {thesis.status.value}; do not create pending proposal from it")
        if thesis.side == ThesisSide.NEUTRAL_WATCH:
            reasons.append("thesis is neutral_watch; proposal requires a directional thesis or manual override")
        triggered_risks = [risk.text for risk in thesis.risks if risk.status == ThesisRiskStatus.TRIGGERED]
        if triggered_risks:
            reasons.append(f"thesis invalidation risk triggered: {'; '.join(triggered_risks[:3])}")
        broken_pillars = [pillar.text for pillar in thesis.pillars if pillar.status == ThesisPillarStatus.BROKEN]
        if broken_pillars:
            reasons.append(f"thesis pillar broken: {'; '.join(broken_pillars[:3])}")
        return reasons

    def approve_proposal(self, proposal_id: str, approved_by: str = "local-user") -> dict:
        proposal = self._get_existing(proposal_id)
        if proposal.status != ProposalStatus.PENDING:
            raise HTTPException(status_code=409, detail=f"proposal is {proposal.status.value}, not PENDING")

        recheck = self.risk.check_approval_revalidation(proposal)
        proposal.risk_check = recheck
        if not recheck.passed:
            if "proposal expired" in recheck.reasons:
                proposal.status = ProposalStatus.EXPIRED
                self.store.update_proposal(proposal, "proposal_expired")
            raise HTTPException(status_code=409, detail={"message": "approval revalidation failed", "risk": recheck.model_dump()})

        proposal.status = ProposalStatus.APPROVED
        proposal.approved_at = utc_now()
        proposal.approved_by = approved_by
        self.store.update_proposal(proposal, "proposal_approved")

        execution = ExecutionRecord(
            proposal_id=proposal.id,
            symbol=proposal.symbol,
            side=proposal.side,
            qty=proposal.qty,
            limit_price=proposal.limit_price,
            mode=ExecutionMode.PAPER if self.settings.is_paper else ExecutionMode.LIVE,
            notes="Paper execution recorded locally. Futu/OpenD live execution is intentionally disabled in the MVP."
            if self.settings.is_paper
            else "Live mode requested; broker adapter is not enabled by this MVP.",
        )
        self.store.create_execution(execution)
        return {"proposal": proposal, "execution": execution}

    def reject_proposal(self, proposal_id: str, reason: str = "Rejected by user") -> Proposal:
        proposal = self._get_existing(proposal_id)
        if proposal.status != ProposalStatus.PENDING:
            raise HTTPException(status_code=409, detail=f"proposal is {proposal.status.value}, not PENDING")
        proposal.status = ProposalStatus.REJECTED
        proposal.rejected_at = utc_now()
        proposal.rejection_reason = reason
        return self.store.update_proposal(proposal, "proposal_rejected")

    def _get_existing(self, proposal_id: str) -> Proposal:
        proposal = self.store.get_proposal(proposal_id)
        if not proposal:
            raise HTTPException(status_code=404, detail="proposal not found")
        return proposal
