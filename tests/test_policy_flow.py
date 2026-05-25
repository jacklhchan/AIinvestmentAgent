from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import HTTPException

from invest_agent.config import Settings
from invest_agent.demo_data import seed_demo_data
from invest_agent.models import ProposalCreate, ProposalStatus, Side
from invest_agent.services import InvestmentService
from invest_agent.store import Store


def make_service(tmp_path: Path) -> InvestmentService:
    settings = Settings(db_path=tmp_path / "test.db")
    store = Store(settings.db_path)
    seed_demo_data(store, force=True)
    return InvestmentService(settings, store)


def test_create_and_approve_paper_proposal(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    proposal = service.create_proposal(
        ProposalCreate(
            symbol="GOOGL",
            side=Side.BUY,
            qty=5,
            limit_price=175.70,
            thesis="Validate a small paper trade through approval and audit flow.",
            trigger="pytest",
            confidence=0.65,
        )
    )

    assert proposal.status == ProposalStatus.PENDING
    assert proposal.risk_check.passed is True

    result = service.approve_proposal(proposal.id, approved_by="pytest")

    assert result["proposal"].status == ProposalStatus.APPROVED
    assert result["execution"].proposal_id == proposal.id
    assert result["execution"].mode.value == "PAPER"


def test_oversized_proposal_is_risk_rejected(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    proposal = service.create_proposal(
        ProposalCreate(
            symbol="NVDA",
            side=Side.BUY,
            qty=1000,
            limit_price=139.50,
            thesis="This proposal should exceed notional and cash limits.",
            trigger="pytest",
            confidence=0.72,
        )
    )

    assert proposal.status == ProposalStatus.RISK_REJECTED
    assert proposal.risk_check.passed is False
    assert proposal.risk_check.reasons


def test_duplicate_pending_proposal_is_blocked(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    request = ProposalCreate(
        symbol="GOOGL",
        side=Side.BUY,
        qty=4,
        limit_price=175.70,
        thesis="First proposal should pass the local policy engine.",
        trigger="pytest",
        confidence=0.58,
    )

    first = service.create_proposal(request)
    second = service.create_proposal(request)

    assert first.status == ProposalStatus.PENDING
    assert second.status == ProposalStatus.RISK_REJECTED
    assert "duplicate pending proposal" in "; ".join(second.risk_check.reasons)


def test_reject_non_pending_fails(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    proposal = service.create_proposal(
        ProposalCreate(
            symbol="GOOGL",
            side=Side.BUY,
            qty=5,
            limit_price=175.70,
            thesis="Validate non-pending state handling after approval.",
            trigger="pytest",
            confidence=0.65,
        )
    )
    service.approve_proposal(proposal.id, approved_by="pytest")

    with pytest.raises(HTTPException):
        service.reject_proposal(proposal.id)
