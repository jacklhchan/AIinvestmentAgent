from __future__ import annotations

from invest_agent.autonomy import SafeAutonomyRunner, autonomy_status
from invest_agent.config import Settings
from invest_agent.demo_data import seed_demo_data
from invest_agent.models import ProposalStatus
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
    )
    store = Store(settings.db_path)
    seed_demo_data(store, force=True)
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


def test_autonomy_status_reports_latest_run(tmp_path) -> None:
    runner, settings, store = make_runner(tmp_path)

    runner.run_cycle(mode="test")
    status = autonomy_status(settings, store)

    assert status["paper_only"] is True
    assert status["last_run"]["mode"] == "test"
    assert status["last_run"]["created_count"] == 1
