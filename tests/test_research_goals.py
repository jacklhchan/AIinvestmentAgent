from __future__ import annotations

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
        )
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
