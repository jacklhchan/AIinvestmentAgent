from __future__ import annotations

from datetime import timedelta
from pathlib import Path

from invest_agent.catalysts import CatalystCalendarService, mcp_catalyst_request
from invest_agent.config import Settings
from invest_agent.demo_data import seed_demo_data
from invest_agent.models import (
    CatalystCompleteRequest,
    CatalystCreate,
    CatalystEventType,
    CatalystExpectedImpact,
    CatalystReviewCreate,
    CatalystSourceType,
    CatalystStatus,
    CatalystThesisDelta,
    CatalystVerificationStatus,
    ProposalCreate,
    ProposalStatus,
    ResearchEvidenceCreate,
    ResearchGoalCreate,
    Side,
    ThesisActionBias,
    ThesisCreate,
    ThesisImpact,
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


def create_passed_goal(store: Store, symbol: str = "GOOGL") -> str:
    research = ResearchGoalService(store)
    goal = research.create_goal(
        ResearchGoalCreate(
            symbol=symbol,
            objective=f"Evaluate {symbol} event evidence before proposal creation.",
        )
    )
    research.add_evidence(
        ResearchEvidenceCreate(goal_id=goal.id, symbol=symbol, source_type="google-news", text=f"{symbol} growth beats expectations")
    )
    research.add_evidence(
        ResearchEvidenceCreate(
            goal_id=goal.id,
            symbol=symbol,
            source_type="sec-edgar",
            text=f"{symbol} filed 10-Q",
            verification_status="verified",
        ),
        trusted_source=True,
    )
    research.complete_if_sufficient(goal.id)
    return goal.id


def create_pending_request(goal_id: str, *, confidence: float = 0.65) -> ProposalCreate:
    return ProposalCreate(
        symbol="GOOGL",
        side=Side.BUY,
        qty=5,
        limit_price=175.70,
        thesis="Validate catalyst policy before a pending paper proposal is created.",
        trigger="pytest",
        confidence=confidence,
        research_goal_id=goal_id,
    )


def test_create_catalyst_and_list_upcoming(tmp_path) -> None:
    _settings, store, _service = make_stack(tmp_path)
    catalyst = CatalystCalendarService(store).create_catalyst(
        CatalystCreate(
            symbol="GOOGL",
            title="Alphabet earnings",
            event_date=utc_now() + timedelta(days=5),
            expected_impact=CatalystExpectedImpact.HIGH,
            verification_status=CatalystVerificationStatus.HUMAN_VERIFIED,
        ),
        human_verified=True,
    )

    upcoming = CatalystCalendarService(store).list_upcoming(days=14)

    assert upcoming[0].id == catalyst.id
    assert upcoming[0].verification_status == CatalystVerificationStatus.HUMAN_VERIFIED


def test_mcp_created_catalyst_is_unverified_by_default(tmp_path) -> None:
    _settings, store, _service = make_stack(tmp_path)
    request = mcp_catalyst_request(
        symbol="GOOGL",
        event_type="earnings",
        title="MCP submitted earnings date",
        event_date=utc_now() + timedelta(days=3),
        expected_impact="high",
    )

    catalyst = CatalystCalendarService(store).create_catalyst(request)

    assert catalyst.created_via == "mcp"
    assert catalyst.verification_status == CatalystVerificationStatus.UNVERIFIED
    assert catalyst.source_verified is False


def test_source_verified_catalyst_requires_official_source_type(tmp_path) -> None:
    _settings, store, _service = make_stack(tmp_path)
    manual = CatalystCalendarService(store).create_catalyst(
        CatalystCreate(
            symbol="GOOGL",
            title="Manual event pretending to be source verified",
            event_date=utc_now() + timedelta(days=4),
            source_type=CatalystSourceType.MANUAL,
            verification_status=CatalystVerificationStatus.SOURCE_VERIFIED,
        ),
        trusted_source=True,
    )
    official = CatalystCalendarService(store).create_catalyst(
        CatalystCreate(
            symbol="GOOGL",
            title="SEC source event",
            event_date=utc_now() + timedelta(days=4),
            source_type=CatalystSourceType.SEC_EDGAR,
            verification_status=CatalystVerificationStatus.SOURCE_VERIFIED,
        ),
        trusted_source=True,
    )

    assert manual.source_verified is False
    assert manual.verification_status == CatalystVerificationStatus.UNVERIFIED
    assert official.source_verified is True
    assert official.verification_status == CatalystVerificationStatus.SOURCE_VERIFIED


def test_high_impact_earnings_window_blocks_new_pending_buy(tmp_path) -> None:
    _settings, store, service = make_stack(tmp_path)
    goal_id = create_passed_goal(store)
    CatalystCalendarService(store).create_catalyst(
        CatalystCreate(
            symbol="GOOGL",
            event_type="earnings",
            title="Alphabet earnings tomorrow",
            event_date=utc_now() + timedelta(hours=30),
            expected_impact=CatalystExpectedImpact.HIGH,
        ),
        human_verified=True,
    )

    proposal = service.create_proposal(create_pending_request(goal_id))

    assert proposal.status == ProposalStatus.RISK_REJECTED
    assert any("high-impact catalyst" in reason for reason in proposal.risk_check.reasons)


def test_high_impact_macro_catalyst_blocks_symbol_proposal(tmp_path) -> None:
    _settings, store, service = make_stack(tmp_path)
    goal_id = create_passed_goal(store)
    CatalystCalendarService(store).create_catalyst(
        CatalystCreate(
            symbol=None,
            event_type=CatalystEventType.MACRO,
            title="FOMC decision",
            event_date=utc_now() + timedelta(hours=10),
            expected_impact=CatalystExpectedImpact.HIGH,
        ),
        human_verified=True,
    )

    proposal = service.create_proposal(create_pending_request(goal_id))

    assert proposal.status == ProposalStatus.RISK_REJECTED
    assert any("FOMC decision" in reason for reason in proposal.risk_check.reasons)


def test_medium_impact_catalyst_adds_policy_warning(tmp_path) -> None:
    _settings, store, service = make_stack(tmp_path)
    goal_id = create_passed_goal(store)
    CatalystCalendarService(store).create_catalyst(
        CatalystCreate(
            symbol="GOOGL",
            title="Alphabet investor conference",
            event_date=utc_now() + timedelta(hours=12),
            expected_impact=CatalystExpectedImpact.MEDIUM,
        ),
        human_verified=True,
    )

    proposal = service.create_proposal(create_pending_request(goal_id, confidence=0.70))

    assert proposal.status == ProposalStatus.PENDING
    assert any("medium-impact catalyst" in warning for warning in proposal.risk_check.warnings)
    assert proposal.risk_check.metrics["catalyst_effective_confidence"] == 0.6


def test_completed_catalyst_creates_post_event_research_goal_candidate(tmp_path) -> None:
    _settings, store, _service = make_stack(tmp_path)
    catalyst = CatalystCalendarService(store).create_catalyst(
        CatalystCreate(
            symbol="GOOGL",
            title="Alphabet earnings completed",
            event_date=utc_now() - timedelta(hours=1),
            expected_impact=CatalystExpectedImpact.HIGH,
        ),
        human_verified=True,
    )

    completed = CatalystCalendarService(store).complete_catalyst(
        catalyst.id,
        CatalystCompleteRequest(actual_outcome_summary="Earnings released; post-event review is required."),
    )

    assert completed.status == CatalystStatus.COMPLETED
    assert completed.linked_research_goal_id
    assert store.get_research_goal(completed.linked_research_goal_id) is not None


def test_catalyst_review_can_update_thesis_delta(tmp_path) -> None:
    _settings, store, _service = make_stack(tmp_path)
    thesis = ThesisTrackerService(store).create_thesis(
        ThesisCreate(
            symbol="GOOGL",
            thesis_statement="Alphabet thesis depends on post-earnings fundamentals staying healthy.",
        )
    )
    goal_id = create_passed_goal(store)
    catalyst = CatalystCalendarService(store).create_catalyst(
        CatalystCreate(
            symbol="GOOGL",
            title="Alphabet earnings completed",
            event_date=utc_now() - timedelta(hours=1),
            expected_impact=CatalystExpectedImpact.HIGH,
            linked_thesis_id=thesis.id,
        ),
        human_verified=True,
    )

    review = CatalystCalendarService(store).create_review(
        catalyst.id,
        CatalystReviewCreate(
            research_goal_id=goal_id,
            actual_outcome_summary="Earnings weakened the thesis.",
            thesis_delta=CatalystThesisDelta.WEAKENS,
            action_bias="watch_only",
        ),
    )
    updated_thesis = store.get_thesis(thesis.id)

    assert review.evidence_hash
    assert store.get_catalyst(catalyst.id).thesis_delta == CatalystThesisDelta.WEAKENS
    assert updated_thesis.updates[0].impact == ThesisImpact.WEAKENS
    assert updated_thesis.updates[0].action_bias == ThesisActionBias.WATCH_ONLY
