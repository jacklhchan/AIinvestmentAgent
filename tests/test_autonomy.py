from __future__ import annotations

import fcntl

from invest_agent.autonomy import SafeAutonomyRunner, autonomy_status
from invest_agent.config import Settings
from invest_agent.demo_data import seed_demo_data
from invest_agent.models import NewsItem, ProposalStatus, utc_now
from invest_agent.services import InvestmentService
from invest_agent.store import Store


def make_runner(tmp_path):
    settings = Settings(
        db_path=tmp_path / "test.db",
        watchlist_symbols="NVDA",
        autonomy_refresh_news=False,
        autonomy_refresh_primary_sources=False,
        autonomy_refresh_fundamentals=False,
        autonomy_create_proposals=True,
        autonomy_proposal_cooldown_minutes=240,
        draft_min_score=1,
    )
    store = Store(settings.db_path)
    seed_demo_data(store, force=True)
    store.upsert_news(
        NewsItem(
            symbol="NVDA",
            title="SEC 10-Q filed for NVDA",
            source="sec-edgar",
            tags=["primary-source", "sec-edgar", "10-q"],
            published_at=utc_now(),
            summary="Primary-source filing used to satisfy research evidence gate in autonomy tests.",
        )
    )
    service = InvestmentService(settings, store)
    return SafeAutonomyRunner(settings, store, service), settings, store


def test_safe_autonomy_cycle_creates_paper_only_proposal(tmp_path) -> None:
    runner, _settings, store = make_runner(tmp_path)

    result = runner.run_cycle(mode="test")

    assert len(result.created_proposals) == 1
    assert result.created_proposals[0].status == ProposalStatus.PENDING
    assert result.created_proposals[0].execution_mode == "PAPER"
    assert any(step.name == "proposal_drafts" for step in result.steps)
    assert store.list_audit_events(event_type="autonomy_cycle_completed")


def test_safe_autonomy_proposal_cooldown_prevents_duplicate(tmp_path) -> None:
    runner, _settings, _store = make_runner(tmp_path)

    first = runner.run_cycle(mode="test")
    second = runner.run_cycle(mode="test")

    assert len(first.created_proposals) == 1
    assert second.created_proposals == []
    assert any("cooldown active" in item for item in second.skipped)


def test_safe_autonomy_single_flight_skips_when_lock_is_held(tmp_path) -> None:
    runner, settings, store = make_runner(tmp_path)
    lock_path = settings.db_path.parent / "safe_autonomy.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    started_before = len(store.list_audit_events(event_type="autonomy_cycle_started"))

    with lock_path.open("a+", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            result = runner.run_cycle(mode="test")
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    assert result.created_proposals == []
    assert result.steps[0].name == "single_flight"
    assert result.steps[0].status == "skipped"
    assert result.skipped == ["safe autonomy cycle already running"]
    assert result.steps[0].metrics["lock_path"] == str(lock_path)
    assert len(store.list_audit_events(event_type="autonomy_cycle_started")) == started_before
    assert store.list_audit_events(event_type="autonomy_cycle_skipped")


def test_autonomy_status_reports_latest_run(tmp_path) -> None:
    runner, settings, store = make_runner(tmp_path)

    runner.run_cycle(mode="test")
    status = autonomy_status(settings, store)

    assert status["paper_only"] is True
    assert status["last_run"]["mode"] == "test"
    assert status["last_run"]["created_count"] == 1
    assert status["draft_min_score"] == 1
