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
    utc_now,
)
from .policy import RiskEngine
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
        status = ProposalStatus.PENDING if risk_check.passed else ProposalStatus.RISK_REJECTED
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
        )
        return self.store.create_proposal(proposal)

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
