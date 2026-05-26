from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import pytest

from invest_agent.catalysts import CatalystCalendarService
from invest_agent.config import Settings
from invest_agent.demo_data import seed_demo_data
from invest_agent.earnings_review import EarningsReviewService
from invest_agent.models import (
    CatalystCompleteRequest,
    CatalystCreate,
    CatalystEventType,
    CatalystExpectedImpact,
    CatalystStatus,
    CatalystThesisDelta,
    EarningsReviewRunRequest,
    FundamentalMetric,
    FundamentalSnapshot,
    ProposalCreate,
    ProposalStatus,
    ResearchEvidenceCreate,
    ResearchGoalCreate,
    Side,
    ThesisCreate,
    ThesisImpact,
    ThesisStatus,
    utc_now,
)
from invest_agent.research_goals import ResearchGoalService
from invest_agent.services import InvestmentService
from invest_agent.store import Store
from invest_agent.thesis_tracker import ThesisTrackerService


def make_stack(tmp_path: Path):
    settings = Settings(db_path=tmp_path / "test.db")
    store = Store(settings.db_path)
    seed_demo_data(store, force=True)
    service = InvestmentService(settings, store)
    return settings, store, service


def make_snapshot(
    symbol: str = "GOOGL",
    *,
    revenue_yoy: float | None = 12.0,
    net_income_yoy: float | None = 18.0,
    operating_income_yoy: float | None = 16.0,
    operating_cash_flow_yoy: float | None = 10.0,
    eps_yoy: float | None = 14.0,
) -> FundamentalSnapshot:
    filed_at = utc_now() - timedelta(days=2)

    def metric(name: str, label: str, yoy: float | None) -> FundamentalMetric:
        return FundamentalMetric(
            name=name,
            label=label,
            concept=label.replace(" ", ""),
            value=100.0,
            unit="USD",
            fiscal_year=2026,
            fiscal_period="Q1",
            end_date="2026-03-31",
            form="10-Q",
            filed_at=filed_at,
            yoy_change_pct=yoy,
        )

    return FundamentalSnapshot(
        symbol=symbol,
        cik="0001652044",
        entity_name="Alphabet Inc.",
        metrics={
            "revenue": metric("revenue", "Revenue", revenue_yoy),
            "net_income": metric("net_income", "Net income", net_income_yoy),
            "operating_income": metric("operating_income", "Operating income", operating_income_yoy),
            "operating_cash_flow": metric("operating_cash_flow", "Operating cash flow", operating_cash_flow_yoy),
            "eps_diluted": metric("eps_diluted", "Diluted EPS", eps_yoy),
        },
    )


def create_passed_goal(store: Store, symbol: str = "GOOGL") -> str:
    research = ResearchGoalService(store)
    goal = research.create_goal(ResearchGoalCreate(symbol=symbol, objective=f"Evaluate {symbol} proposal evidence."))
    research.add_evidence(
        ResearchEvidenceCreate(goal_id=goal.id, symbol=symbol, source_type="google-news", text=f"{symbol} momentum improves")
    )
    research.add_evidence(
        ResearchEvidenceCreate(
            goal_id=goal.id,
            symbol=symbol,
            source_type="sec-companyfacts",
            text=f"{symbol} companyfacts verified",
            verification_status="verified",
        ),
        trusted_source=True,
    )
    research.complete_if_sufficient(goal.id)
    return goal.id


def create_pending_request(goal_id: str) -> ProposalCreate:
    return ProposalCreate(
        symbol="GOOGL",
        side=Side.BUY,
        qty=5,
        limit_price=175.70,
        thesis="Proposal should depend on post-earnings review state.",
        trigger="pytest",
        confidence=0.70,
        research_goal_id=goal_id,
    )


def test_run_earnings_review_creates_review_from_companyfacts(tmp_path) -> None:
    _settings, store, _service = make_stack(tmp_path)
    store.upsert_fundamentals(make_snapshot())

    review = EarningsReviewService(store).run_review(EarningsReviewRunRequest(symbol="GOOGL"))
    goal = store.get_research_goal(review.research_goal_id)

    assert review.thesis_delta == CatalystThesisDelta.STRENGTHENS
    assert review.revenue_yoy == 12.0
    assert review.operating_cash_flow_yoy == 10.0
    assert review.evidence_hash
    assert store.get_earnings_review(review.id).id == review.id
    assert any(item.source_type == "sec-companyfacts" and item.source_verified for item in goal.evidence)


def test_earnings_review_requires_local_companyfacts_snapshot(tmp_path) -> None:
    _settings, store, _service = make_stack(tmp_path)

    with pytest.raises(ValueError, match="fundamental snapshot not found"):
        EarningsReviewService(store).run_review(EarningsReviewRunRequest(symbol="GOOGL"))


def test_completed_earnings_catalyst_review_unblocks_post_event_proposal(tmp_path) -> None:
    _settings, store, service = make_stack(tmp_path)
    goal_id = create_passed_goal(store)
    store.upsert_fundamentals(make_snapshot())
    catalyst = CatalystCalendarService(store).create_catalyst(
        CatalystCreate(
            symbol="GOOGL",
            event_type=CatalystEventType.EARNINGS,
            title="Alphabet earnings completed",
            event_date=utc_now() - timedelta(hours=1),
            expected_impact=CatalystExpectedImpact.HIGH,
        ),
        human_verified=True,
    )
    completed = CatalystCalendarService(store).complete_catalyst(
        catalyst.id,
        CatalystCompleteRequest(actual_outcome_summary="Earnings released; review required."),
    )

    blocked = service.create_proposal(create_pending_request(goal_id))
    review = EarningsReviewService(store).run_review(EarningsReviewRunRequest(symbol="GOOGL", catalyst_id=completed.id))
    allowed = service.create_proposal(create_pending_request(goal_id))

    assert blocked.status == ProposalStatus.RISK_REJECTED
    assert any("completed catalyst lacks post-event review" in reason for reason in blocked.risk_check.reasons)
    assert review.catalyst_review_id
    assert store.get_catalyst(completed.id).status == CatalystStatus.COMPLETED
    assert allowed.status == ProposalStatus.PENDING


def test_earnings_review_strengthens_thesis_when_growth_metrics_are_positive(tmp_path) -> None:
    _settings, store, _service = make_stack(tmp_path)
    store.upsert_fundamentals(make_snapshot())
    thesis = ThesisTrackerService(store).create_thesis(
        ThesisCreate(symbol="GOOGL", thesis_statement="Alphabet thesis depends on durable earnings growth.")
    )

    review = EarningsReviewService(store).run_review(EarningsReviewRunRequest(symbol="GOOGL", thesis_id=thesis.id))
    updated = EarningsReviewService(store).apply_to_thesis(review.id)

    assert review.thesis_delta == CatalystThesisDelta.STRENGTHENS
    assert updated.updates[0].impact == ThesisImpact.STRENGTHENS
    assert updated.status == ThesisStatus.ACTIVE


def test_earnings_review_weakens_thesis_when_ocf_contradicts_net_income(tmp_path) -> None:
    _settings, store, _service = make_stack(tmp_path)
    store.upsert_fundamentals(
        make_snapshot(revenue_yoy=8.0, net_income_yoy=20.0, operating_cash_flow_yoy=-20.0, eps_yoy=-8.0)
    )

    review = EarningsReviewService(store).run_review(EarningsReviewRunRequest(symbol="GOOGL"))

    assert review.thesis_delta == CatalystThesisDelta.WEAKENS
    assert "net income improved while operating cash flow deteriorated" in review.warnings


def test_severe_earnings_review_delta_requires_human_confirmation_before_thesis_apply(tmp_path) -> None:
    _settings, store, _service = make_stack(tmp_path)
    store.upsert_fundamentals(
        make_snapshot(revenue_yoy=-12.0, net_income_yoy=-20.0, operating_cash_flow_yoy=-30.0, eps_yoy=-18.0)
    )
    thesis = ThesisTrackerService(store).create_thesis(
        ThesisCreate(symbol="GOOGL", thesis_statement="Alphabet thesis should be invalidated only with human confirmation.")
    )

    review = EarningsReviewService(store).run_review(EarningsReviewRunRequest(symbol="GOOGL", thesis_id=thesis.id))

    assert review.thesis_delta == CatalystThesisDelta.INVALIDATES
    with pytest.raises(ValueError, match="human confirmation required"):
        EarningsReviewService(store).apply_to_thesis(review.id)
    updated = EarningsReviewService(store).apply_to_thesis(review.id, human_confirmed=True)
    assert updated.status == ThesisStatus.INVALIDATED
