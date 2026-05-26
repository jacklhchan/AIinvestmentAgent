from __future__ import annotations

import csv
from pathlib import Path

from invest_agent.advisor import AdvisorService
from invest_agent.config import Settings
from invest_agent.demo_data import seed_demo_data
from invest_agent.models import (
    AdvisorBriefRequest,
    AdvisorSeverity,
    RunCardActor,
    TradeJournalImportRequest,
    TradeJournalSource,
)
from invest_agent.store import Store
from invest_agent.trade_journal import TradeJournalService


def make_store(tmp_path: Path) -> Store:
    settings = Settings(db_path=tmp_path / "test.db")
    store = Store(settings.db_path)
    seed_demo_data(store, force=True)
    return store


def write_csv(path: Path) -> Path:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["datetime", "symbol", "side", "quantity", "price", "fee", "currency", "market"])
        writer.writerows(
            [
                ["2026-01-01 09:30:00", "AAPL", "buy", "10", "100", "0", "USD", "US"],
                ["2026-01-03 09:30:00", "AAPL", "sell", "10", "110", "0", "USD", "US"],
            ]
        )
    return path


def test_advisor_brief_explains_missing_behavior_report(tmp_path) -> None:
    store = make_store(tmp_path)

    brief = AdvisorService(store).build_brief()

    assert brief.paper_only is True
    assert any(item.category == "behavior" for item in brief.advice)
    assert brief.risk_level in {AdvisorSeverity.WATCH, AdvisorSeverity.ACTION, AdvisorSeverity.BLOCKED}


def test_advisor_brief_can_run_light_behavior_analysis_without_creating_proposal(tmp_path) -> None:
    store = make_store(tmp_path)
    TradeJournalService(store).import_csv(
        TradeJournalImportRequest(path=str(write_csv(tmp_path / "trades.csv")), source=TradeJournalSource.GENERIC_CSV),
        actor=RunCardActor.CLI,
    )
    proposal_count = len(store.list_proposals(limit=100))

    brief = AdvisorService(store).build_brief(AdvisorBriefRequest(run_light_analysis=True))

    assert brief.automated_actions
    assert brief.data_status["behavior_report_id"]
    assert len(store.list_behavior_reports(limit=10)) == 1
    assert len(store.list_proposals(limit=100)) == proposal_count


def test_mcp_exposes_advisor_brief() -> None:
    import invest_agent.mcp_server as mcp_server

    assert hasattr(mcp_server, "get_advisor_brief")
