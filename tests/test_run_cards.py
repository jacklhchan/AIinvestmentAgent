from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import pytest

from invest_agent.config import Settings
from invest_agent.demo_data import seed_demo_data
from invest_agent.earnings_review import EARNINGS_REVIEW_RULE_VERSION, EarningsReviewService
from invest_agent.event_replay import export_event_replay
from invest_agent.models import (
    EarningsReviewRunRequest,
    FundamentalMetric,
    FundamentalSnapshot,
    RunCardActor,
    RunCardStatus,
    RunCardTriggerSource,
    RunCardType,
    utc_now,
)
from invest_agent.run_cards import RunCardService, sha256_file, stable_hash
from invest_agent.store import Store


def make_store(tmp_path: Path) -> Store:
    settings = Settings(db_path=tmp_path / "test.db")
    store = Store(settings.db_path)
    seed_demo_data(store, force=True)
    return store


def make_snapshot(symbol: str = "GOOGL", revenue_yoy: float = 12.0) -> FundamentalSnapshot:
    filed_at = utc_now() - timedelta(days=2)

    def metric(name: str, label: str, yoy: float) -> FundamentalMetric:
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
            "net_income": metric("net_income", "Net income", 18.0),
            "operating_income": metric("operating_income", "Operating income", 16.0),
            "operating_cash_flow": metric("operating_cash_flow", "Operating cash flow", 10.0),
            "eps_diluted": metric("eps_diluted", "Diluted EPS", 14.0),
        },
    )


def test_run_card_created_for_earnings_review_and_evidence(tmp_path) -> None:
    store = make_store(tmp_path)
    store.upsert_fundamentals(make_snapshot())

    review = EarningsReviewService(store).run_review(
        EarningsReviewRunRequest(symbol="GOOGL"),
        actor=RunCardActor.CLI,
        trigger_source=RunCardTriggerSource.MANUAL,
    )
    run_card = store.get_run_card(review.run_card_id)
    goal = store.get_research_goal(review.research_goal_id)

    assert run_card is not None
    assert run_card.status == RunCardStatus.COMPLETED
    assert run_card.run_type == RunCardType.EARNINGS_REVIEW
    assert run_card.rule_version == EARNINGS_REVIEW_RULE_VERSION
    assert run_card.assumptions["positive_yoy_threshold"] == 5.0
    assert run_card.earnings_review_id == review.id
    assert run_card.artifacts
    assert any(item.run_card_id == run_card.id for item in goal.evidence)


def test_run_card_hash_helpers_are_stable_and_output_changes(tmp_path) -> None:
    store = make_store(tmp_path)
    assert stable_hash({"b": 2, "a": [1, 2]}) == stable_hash({"a": [1, 2], "b": 2})

    service = RunCardService(store, artifact_root=tmp_path / "cards")
    first = service.start_run(RunCardType.EARNINGS_REVIEW, title="Hash Test", symbol="AAPL", inputs={"x": 1})
    second = service.start_run(RunCardType.EARNINGS_REVIEW, title="Hash Test", symbol="AAPL", inputs={"x": 1})
    first_done = service.complete_run(first.id, metrics={"score": 1}, outputs={"delta": "neutral"})
    second_done = service.complete_run(second.id, metrics={"score": 2}, outputs={"delta": "strengthens"})

    assert first.input_hash == second.input_hash
    assert first_done.output_hash != second_done.output_hash


def test_run_card_artifacts_are_written_with_sha256(tmp_path) -> None:
    store = make_store(tmp_path)
    service = RunCardService(store, artifact_root=tmp_path / "cards")
    run_card = service.start_run(RunCardType.CATALYST_REVIEW, title="Artifact Test", symbol="AAPL")

    completed = service.complete_run(run_card.id, metrics={"score": 1}, outputs={"delta": "neutral"})

    for artifact in completed.artifacts:
        path = Path(artifact["path"])
        assert path.exists()
        assert artifact["sha256"] == sha256_file(path)


def test_failed_earnings_review_creates_failed_run_card(tmp_path) -> None:
    store = make_store(tmp_path)

    with pytest.raises(ValueError, match="fundamental snapshot not found"):
        EarningsReviewService(store).run_review(EarningsReviewRunRequest(symbol="GOOGL"))

    cards = store.list_run_cards(run_type=RunCardType.EARNINGS_REVIEW)
    assert cards[0].status == RunCardStatus.FAILED
    assert "fundamental snapshot not found" in cards[0].error


def test_event_replay_export_creates_run_card_artifact(tmp_path) -> None:
    store = make_store(tmp_path)
    replay_path = tmp_path / "events.jsonl"

    result = export_event_replay(store, replay_path, actor=RunCardActor.CLI)
    run_card = store.get_run_card(result.run_card_id)

    assert result.run_card_id
    assert run_card.run_type == RunCardType.EVENT_REPLAY
    assert run_card.status == RunCardStatus.COMPLETED
    assert any(item["kind"] == "jsonl" and item["sha256"] == sha256_file(replay_path) for item in run_card.artifacts)
