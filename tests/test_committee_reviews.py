from __future__ import annotations

from pathlib import Path

from invest_agent.advisor_orchestrator import AdvisorOrchestrator
from invest_agent.api import DASHBOARD_HTML
from invest_agent.committee_reviews import CommitteeReviewService
from invest_agent.config import Settings
from invest_agent.demo_data import seed_demo_data
from invest_agent.models import (
    AdvisorQuestionRequest,
    CommitteeConclusion,
    CommitteeFindingSeverity,
    CommitteeFindingType,
    CommitteeMemberRole,
    CommitteeReviewRunRequest,
    PortfolioSnapshot,
    Position,
    Quote,
    RunCardActor,
    RunCardType,
    utc_now,
)
from invest_agent.store import Store


def make_store(tmp_path: Path) -> Store:
    settings = Settings(db_path=tmp_path / "test.db")
    store = Store(settings.db_path)
    seed_demo_data(store, force=True)
    return store


def test_committee_review_creates_frozen_data_pack_and_run_card_without_proposal(tmp_path) -> None:
    store = make_store(tmp_path)
    before = len(store.list_proposals(limit=100))

    review = CommitteeReviewService(store, settings=Settings(db_path=tmp_path / "test.db")).run_review(
        CommitteeReviewRunRequest(topic="MU investment committee", symbols=["MU"]),
        actor=RunCardActor.CLI,
    )

    assert review.run_card_id
    assert review.data_pack_hash
    assert review.output_hash
    assert review.members_json
    assert review.findings_json
    assert store.get_run_card(review.run_card_id).run_type == RunCardType.COMMITTEE_REVIEW
    assert len(store.list_proposals(limit=100)) == before


def test_committee_review_for_unknown_symbol_returns_research_needed(tmp_path) -> None:
    store = make_store(tmp_path)

    review = CommitteeReviewService(store, settings=Settings(db_path=tmp_path / "test.db")).run_review(
        CommitteeReviewRunRequest(topic="SNDK committee review", symbols=["SNDK"])
    )

    assert review.conclusion == CommitteeConclusion.RESEARCH_NEEDED
    assert review.data_pack_json["symbols_context"][0]["known_universe_status"] == "unknown"
    assert any("unknown" in item["text"].lower() for item in review.findings_json)


def test_committee_evidence_auditor_flags_missing_source_verified_evidence(tmp_path) -> None:
    store = make_store(tmp_path)

    review = CommitteeReviewService(store, settings=Settings(db_path=tmp_path / "test.db")).run_review(
        CommitteeReviewRunRequest(topic="AAPL bull bear committee", symbols=["AAPL"])
    )

    assert any(item["role"] == CommitteeMemberRole.EVIDENCE_AUDITOR.value for item in review.members_json)
    assert any(
        item["finding_type"] == CommitteeFindingType.MISSING_EVIDENCE.value
        and "source-verified" in item["text"]
        for item in review.findings_json
    )


def test_committee_risk_manager_flags_concentration(tmp_path) -> None:
    store = make_store(tmp_path)
    now = utc_now()
    store.upsert_portfolio(
        PortfolioSnapshot(
            cash_usd=5000,
            total_value_usd=100000,
            positions=[
                Position(symbol="NVDA", qty=100, market_value=45000, last_price=450),
                Position(symbol="AMD", qty=100, market_value=20000, last_price=200),
                Position(symbol="QQQM", qty=100, market_value=15000, last_price=150),
            ],
            updated_at=now,
            source="test",
        )
    )
    store.upsert_quote(Quote(symbol="NVDA", last_price=450, previous_close=440, change_pct=2.27, updated_at=now))

    review = CommitteeReviewService(store, settings=Settings(db_path=tmp_path / "test.db")).run_review(
        CommitteeReviewRunRequest(topic="NVDA investment committee", symbols=["NVDA"])
    )

    assert review.conclusion == CommitteeConclusion.BLOCKED
    assert any(
        item["severity"] == CommitteeFindingSeverity.BLOCKING.value
        and item["finding_type"] == CommitteeFindingType.PORTFOLIO_FIT.value
        for item in review.findings_json
    )


def test_ask_advisor_committee_question_runs_committee_without_proposal(tmp_path) -> None:
    store = make_store(tmp_path)
    before = len(store.list_proposals(limit=100))

    answer = AdvisorOrchestrator(store, settings=Settings(db_path=tmp_path / "test.db")).answer_user_question(
        AdvisorQuestionRequest(question="Can you run bull/bear committee debate for AAPL?", symbol="AAPL")
    )

    assert answer.provenance_json["committee_review_run"] is True
    assert answer.provenance_json["committee_review_id"]
    assert "committee_review" in answer.provenance_json["executed_layers"]
    assert not any(item == "committee_review" for item in answer.provenance_json["not_run"])
    assert any(item.get("type") == "committee_review" for item in answer.linked_artifacts_json)
    assert len(store.list_committee_reviews(limit=10)) == 1
    assert len(store.list_proposals(limit=100)) == before


def test_dashboard_contains_traditional_chinese_committee_panel() -> None:
    assert "投資委員會備忘" in DASHBOARD_HTML
    assert "committee-reviews" in DASHBOARD_HTML
    assert "不能 approve" in DASHBOARD_HTML
