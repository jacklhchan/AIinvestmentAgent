from __future__ import annotations

from pathlib import Path

from invest_agent.config import Settings
from invest_agent.demo_data import seed_demo_data
from invest_agent.models import (
    NewsItem,
    ProposalCreate,
    ProposalStatus,
    CreatedBy,
    CreatedVia,
    ResearchEvidenceCreate,
    ResearchGoalCreate,
    Side,
    ThesisActionBias,
    ThesisCreate,
    ThesisImpact,
    ThesisPillarInput,
    ThesisRiskInput,
    ThesisUpdateCreate,
    ThesisStatus,
    utc_now,
)
from invest_agent.proposal_drafts import ProposalDraftEngine
from invest_agent.research_goals import ResearchGoalService
from invest_agent.services import InvestmentService
from invest_agent.store import Store
from invest_agent.thesis_tracker import ThesisTrackerService


def make_stack(tmp_path: Path, *, watchlist: str = "GOOGL"):
    settings = Settings(db_path=tmp_path / "test.db", watchlist_symbols=watchlist, draft_notional_usd=1000)
    store = Store(settings.db_path)
    seed_demo_data(store, force=True)
    service = InvestmentService(settings, store)
    return settings, store, service


def create_passed_goal(store: Store, symbol: str = "GOOGL") -> str:
    research = ResearchGoalService(store)
    goal = research.create_goal(
        ResearchGoalCreate(
            symbol=symbol,
            objective=f"Evaluate {symbol} evidence before thesis/proposal update.",
            claims=[f"{symbol} evidence supports a small paper proposal."],
            criteria=["Attach directional evidence.", "Attach verified primary-source evidence."],
        )
    )
    research.add_evidence(
        ResearchEvidenceCreate(
            goal_id=goal.id,
            symbol=symbol,
            source_type="google-news",
            text=f"{symbol} demand growth beats expectations",
        )
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


def create_sample_thesis(store: Store, symbol: str = "GOOGL"):
    return ThesisTrackerService(store).create_thesis(
        ThesisCreate(
            symbol=symbol,
            thesis_statement=f"{symbol} can keep compounding if primary-source fundamentals support growth.",
            pillars=[
                ThesisPillarInput(text="Revenue and cash flow stay aligned with the growth thesis."),
                ThesisPillarInput(text="Primary-source evidence does not contradict the core claim."),
            ],
            risks=[
                ThesisRiskInput(
                    text="Growth thesis weakens after filings.",
                    invalidation_condition="SEC or IR evidence shows multiple-period deterioration.",
                )
            ],
        )
    )


def test_create_thesis_persists_pillars_and_risks(tmp_path) -> None:
    _settings, store, _service = make_stack(tmp_path)

    thesis = create_sample_thesis(store)
    saved = store.get_thesis(thesis.id)

    assert saved is not None
    assert saved.symbol == "GOOGL"
    assert len(saved.pillars) == 2
    assert len(saved.risks) == 1
    assert store.get_active_thesis_for_symbol("GOOGL").id == thesis.id


def test_thesis_update_from_research_goal_hashes_evidence_and_invalidates(tmp_path) -> None:
    _settings, store, _service = make_stack(tmp_path)
    thesis = create_sample_thesis(store)
    goal_id = create_passed_goal(store)

    updated = ThesisTrackerService(store).add_update(
        thesis.id,
        ThesisUpdateCreate(
            research_goal_id=goal_id,
            impact=ThesisImpact.INVALIDATES,
            summary="Verified evidence invalidates the growth thesis.",
            action_bias=ThesisActionBias.EXIT,
        ),
    )

    assert updated.status == "invalidated"
    assert updated.conviction == "low"
    assert len(updated.updates) == 1
    assert len(updated.updates[0].evidence_hash) == 64


def test_invalidated_thesis_blocks_pending_proposal(tmp_path) -> None:
    _settings, store, service = make_stack(tmp_path)
    thesis = create_sample_thesis(store)
    goal_id = create_passed_goal(store)
    thesis = ThesisTrackerService(store).add_update(
        thesis.id,
        ThesisUpdateCreate(
            research_goal_id=goal_id,
            impact=ThesisImpact.INVALIDATES,
            summary="Thesis is no longer valid.",
            action_bias=ThesisActionBias.EXIT,
        ),
    )

    proposal = service.create_proposal(
        ProposalCreate(
            symbol="GOOGL",
            side=Side.BUY,
            qty=5,
            limit_price=175.70,
            thesis="Try to create a proposal from an invalidated thesis.",
            trigger="pytest",
            confidence=0.65,
            research_goal_id=goal_id,
            thesis_id=thesis.id,
        )
    )

    assert proposal.status == ProposalStatus.RISK_REJECTED
    assert any("thesis status" in reason for reason in proposal.risk_check.reasons)


def test_unconfirmed_mcp_style_thesis_is_watch_only_context(tmp_path) -> None:
    _settings, store, service = make_stack(tmp_path)
    goal_id = create_passed_goal(store)
    thesis = ThesisTrackerService(store).create_thesis(
        ThesisCreate(
            symbol="GOOGL",
            thesis_statement="Hermes drafted thesis should wait for human confirmation.",
            status=ThesisStatus.WATCH,
            created_via=CreatedVia.MCP,
            created_by=CreatedBy.HERMES,
            human_confirmed=False,
            confirmed_by="",
        )
    )

    proposal = service.create_proposal(
        ProposalCreate(
            symbol="GOOGL",
            side=Side.BUY,
            qty=5,
            limit_price=175.70,
            thesis="Try to use an unconfirmed MCP thesis in a proposal.",
            trigger="pytest",
            confidence=0.65,
            research_goal_id=goal_id,
            thesis_id=thesis.id,
        )
    )

    assert store.get_active_thesis_for_symbol("GOOGL") is None
    assert proposal.status == ProposalStatus.RISK_REJECTED
    assert any("not human-confirmed" in reason for reason in proposal.risk_check.reasons)


def test_proposal_draft_attaches_active_thesis(tmp_path) -> None:
    settings, store, service = make_stack(tmp_path)
    thesis = create_sample_thesis(store)
    store.upsert_news(
        NewsItem(
            symbol="GOOGL",
            title="Alphabet raises guidance after record cloud growth",
            source="finnhub",
            published_at=utc_now(),
            summary="Growth and demand remain strong.",
        )
    )
    store.upsert_news(
        NewsItem(
            symbol="GOOGL",
            title="SEC 10-Q filed for GOOGL",
            source="sec-edgar",
            published_at=utc_now(),
            tags=["primary-source", "sec-edgar", "10-q"],
            summary="Primary-source SEC EDGAR filing.",
        )
    )

    result = ProposalDraftEngine(settings, store, service).draft_from_watchlist(
        symbols=["GOOGL"],
        create_proposals=True,
    )

    assert result.drafts[0].thesis_id == thesis.id
    assert result.created[0].thesis_id == thesis.id
    assert any("thesis-tracker" in item for item in result.drafts[0].evidence)
