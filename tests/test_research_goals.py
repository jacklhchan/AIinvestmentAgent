from __future__ import annotations

from datetime import timedelta

import pytest

from invest_agent.config import Settings
from invest_agent.demo_data import seed_demo_data
from invest_agent.models import (
    ResearchEvidenceCreate,
    ResearchGoalCreate,
    ResearchGoalStatus,
)
from invest_agent.research_goals import ResearchGoalService, evaluate_research_gate
from invest_agent.store import Store


def make_service(tmp_path):
    settings = Settings(db_path=tmp_path / "test.db")
    store = Store(settings.db_path)
    seed_demo_data(store, force=True)
    return ResearchGoalService(store), store


def test_create_goal_and_add_evidence_rows(tmp_path) -> None:
    service, store = make_service(tmp_path)
    goal = service.create_goal(
        ResearchGoalCreate(
            symbol="AAPL",
            objective="Evaluate whether recent AAPL evidence supports a watchlist proposal.",
            claims=["AAPL news flow supports a small proposal."],
            criteria=["Attach directional news.", "Attach verified primary-source evidence."],
        )
    )

    service.add_evidence(
        ResearchEvidenceCreate(
            goal_id=goal.id,
            symbol="AAPL",
            source_type="gdelt",
            text="AAPL demand growth beats expectations",
            verification_status="unverified",
        )
    )
    service.add_evidence(
        ResearchEvidenceCreate(
            goal_id=goal.id,
            symbol="AAPL",
            source_type="sec-edgar",
            text="AAPL filed 10-Q",
            verification_status="verified",
        ),
        trusted_source=True,
    )

    saved = store.get_research_goal(goal.id)
    assert saved is not None
    assert saved.evidence_count == 2
    assert evaluate_research_gate(saved).passed is True


def test_research_goal_rejects_execution_objective(tmp_path) -> None:
    service, _store = make_service(tmp_path)

    with pytest.raises(ValueError):
        service.create_goal(
            ResearchGoalCreate(
                symbol="AAPL",
                objective="Place_order for AAPL after this research.",
            )
        )


def test_complete_if_sufficient_marks_insufficient_without_verified_evidence(tmp_path) -> None:
    service, _store = make_service(tmp_path)
    goal = service.create_goal(
        ResearchGoalCreate(
            symbol="MSFT",
            objective="Evaluate MSFT directional news before proposal drafting.",
        )
    )
    service.add_evidence(
        ResearchEvidenceCreate(
            goal_id=goal.id,
            symbol="MSFT",
            source_type="google-news",
            text="MSFT cloud demand growth is strong",
        )
    )

    completed = service.complete_if_sufficient(goal.id)

    assert completed.status == ResearchGoalStatus.INSUFFICIENT
    assert completed.evidence_count == 1
    assert "verified" in completed.summary


def test_mcp_added_verified_text_does_not_count_as_source_verified(tmp_path) -> None:
    service, store = make_service(tmp_path)
    goal = service.create_goal(
        ResearchGoalCreate(
            symbol="AAPL",
            objective="Evaluate AAPL evidence submitted through a remote agent.",
        )
    )
    service.add_evidence(
        ResearchEvidenceCreate(goal_id=goal.id, symbol="AAPL", source_type="gdelt", text="AAPL demand growth beats expectations")
    )
    service.add_evidence(
        ResearchEvidenceCreate(
            goal_id=goal.id,
            symbol="AAPL",
            source_type="sec-edgar",
            text="Agent pasted text that claims it is an SEC filing.",
            verification_status="verified",
            added_via="mcp",
        )
    )

    completed = service.complete_if_sufficient(goal.id)
    evidence = store.list_research_evidence(goal.id)

    assert completed.status == ResearchGoalStatus.INSUFFICIENT
    assert any(item.added_via == "mcp" and not item.source_verified for item in evidence)


def test_verified_evidence_must_match_symbol(tmp_path) -> None:
    service, _store = make_service(tmp_path)
    goal = service.create_goal(
        ResearchGoalCreate(symbol="AAPL", objective="Evaluate AAPL evidence with mismatched primary source.")
    )
    service.add_evidence(
        ResearchEvidenceCreate(goal_id=goal.id, symbol="AAPL", source_type="google-news", text="AAPL growth beats expectations")
    )
    service.add_evidence(
        ResearchEvidenceCreate(
            goal_id=goal.id,
            symbol="MSFT",
            source_type="sec-edgar",
            text="MSFT filed 10-Q",
            verification_status="verified",
        ),
        trusted_source=True,
    )

    completed = service.complete_if_sufficient(goal.id)

    assert completed.status == ResearchGoalStatus.INSUFFICIENT
    assert "symbol" in completed.summary or "verified" in completed.summary


def test_stale_primary_source_does_not_pass_gate(tmp_path) -> None:
    service, _store = make_service(tmp_path)
    goal = service.create_goal(ResearchGoalCreate(symbol="AAPL", objective="Evaluate AAPL with stale primary source."))
    service.add_evidence(
        ResearchEvidenceCreate(goal_id=goal.id, symbol="AAPL", source_type="google-news", text="AAPL growth beats expectations")
    )
    service.add_evidence(
        ResearchEvidenceCreate(
            goal_id=goal.id,
            symbol="AAPL",
            source_type="sec-edgar",
            text="AAPL old 10-Q filing",
            data_as_of=goal.created_at - timedelta(days=365),
            verification_status="verified",
        ),
        trusted_source=True,
    )

    completed = service.complete_if_sufficient(goal.id, max_verified_age_days=120)

    assert completed.status == ResearchGoalStatus.INSUFFICIENT
    assert "verified" in completed.summary


def test_contradicting_evidence_blocks_gate_or_marks_mixed(tmp_path) -> None:
    service, _store = make_service(tmp_path)
    goal = service.create_goal(
        ResearchGoalCreate(
            symbol="AAPL",
            objective="Evaluate AAPL evidence with contradiction.",
            claims=["AAPL growth evidence supports the proposal."],
        )
    )
    claim_id = goal.claims[0].id
    service.add_evidence(
        ResearchEvidenceCreate(goal_id=goal.id, symbol="AAPL", source_type="google-news", text="AAPL growth beats expectations")
    )
    service.add_evidence(
        ResearchEvidenceCreate(
            goal_id=goal.id,
            symbol="AAPL",
            source_type="sec-edgar",
            text="AAPL filed 10-Q but margin trend contradicts the claim.",
            verification_status="verified",
            contradicts_claim_ids=[claim_id],
        ),
        trusted_source=True,
    )

    completed = service.complete_if_sufficient(goal.id)
    gate = evaluate_research_gate(completed)

    assert completed.status == ResearchGoalStatus.INSUFFICIENT
    assert any("contradicting" in reason for reason in gate.reasons)
