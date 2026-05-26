from __future__ import annotations

import csv
from datetime import datetime, timezone
from pathlib import Path

from invest_agent.catalysts import CatalystCalendarService
from invest_agent.config import Settings
from invest_agent.demo_data import seed_demo_data
from invest_agent.models import (
    BehaviorReportRunRequest,
    CatalystCreate,
    CatalystEventType,
    CatalystExpectedImpact,
    CatalystStatus,
    ShadowEventType,
    ShadowReportRunRequest,
    ShadowStrategyConfirmRequest,
    ShadowStrategyExtractRequest,
    ShadowStrategyStatus,
    Thesis,
    ThesisSide,
    ThesisStatus,
    TradeJournalImportRequest,
    TradeJournalSource,
)
from invest_agent.shadow_account import ShadowAccountService
from invest_agent.store import Store
from invest_agent.trade_journal import TradeJournalService


def make_store(tmp_path: Path) -> Store:
    settings = Settings(db_path=tmp_path / "test.db")
    store = Store(settings.db_path)
    seed_demo_data(store, force=True)
    return store


def write_csv(path: Path, rows: list[list[str]]) -> Path:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["datetime", "symbol", "side", "quantity", "price", "fee", "currency", "market"])
        writer.writerows(rows)
    return path


def import_and_report(store: Store, path: Path):
    TradeJournalService(store).import_csv(
        TradeJournalImportRequest(path=str(path), source=TradeJournalSource.GENERIC_CSV),
    )
    return TradeJournalService(store).run_behavior_report(BehaviorReportRunRequest())


def extract_confirmed_strategy(store: Store, behavior_report_id: str):
    service = ShadowAccountService(store)
    strategy = service.extract_strategy(ShadowStrategyExtractRequest(behavior_report_id=behavior_report_id))
    return service.confirm_strategy(strategy.id, ShadowStrategyConfirmRequest(confirmed_by="test"))


def test_extract_shadow_strategy_from_behavior_report_creates_draft_rules(tmp_path) -> None:
    store = make_store(tmp_path)
    report = import_and_report(
        store,
        write_csv(
            tmp_path / "trades.csv",
            [
                ["2026-01-01 09:30:00", "AAPL", "buy", "10", "100", "0", "USD", "US"],
                ["2026-01-03 09:30:00", "AAPL", "sell", "10", "110", "0", "USD", "US"],
            ],
        ),
    )

    strategy = ShadowAccountService(store).extract_strategy(
        ShadowStrategyExtractRequest(behavior_report_id=report.id, name="Observed Rules"),
    )

    assert strategy.status == ShadowStrategyStatus.DRAFT
    assert strategy.human_confirmed is False
    assert strategy.source_behavior_report_id == report.id
    assert {rule.rule_type.value for rule in strategy.rules} >= {"exit", "sizing", "thesis", "catalyst"}


def test_mcp_can_read_but_not_confirm_shadow_strategy() -> None:
    import invest_agent.mcp_server as mcp_server

    assert hasattr(mcp_server, "list_shadow_strategies")
    assert hasattr(mcp_server, "get_shadow_strategy")
    assert hasattr(mcp_server, "list_shadow_reports")
    assert hasattr(mcp_server, "get_shadow_report")
    assert hasattr(mcp_server, "list_shadow_events")
    assert not hasattr(mcp_server, "extract_shadow_strategy")
    assert not hasattr(mcp_server, "confirm_shadow_strategy")
    assert not hasattr(mcp_server, "run_shadow_report")


def test_confirmed_shadow_strategy_can_run_shadow_report(tmp_path) -> None:
    store = make_store(tmp_path)
    report = import_and_report(
        store,
        write_csv(
            tmp_path / "trades.csv",
            [
                ["2026-01-01 09:30:00", "AAPL", "buy", "10", "100", "0", "USD", "US"],
                ["2026-01-03 09:30:00", "AAPL", "sell", "10", "110", "0", "USD", "US"],
            ],
        ),
    )
    strategy = extract_confirmed_strategy(store, report.id)

    shadow_report = ShadowAccountService(store).run_report(ShadowReportRunRequest(strategy_id=strategy.id))

    assert shadow_report.strategy_id == strategy.id
    assert shadow_report.behavior_report_id == report.id
    assert shadow_report.run_card_id


def test_shadow_report_flags_early_exit_against_holding_rule(tmp_path) -> None:
    store = make_store(tmp_path)
    report = import_and_report(
        store,
        write_csv(
            tmp_path / "early_exit.csv",
            [
                ["2026-01-01 09:30:00", "FAST", "buy", "10", "100", "0", "USD", "US"],
                ["2026-01-02 09:30:00", "FAST", "sell", "10", "108", "0", "USD", "US"],
                ["2026-01-01 09:30:00", "SLOW", "buy", "10", "100", "0", "USD", "US"],
                ["2026-01-11 09:30:00", "SLOW", "sell", "10", "112", "0", "USD", "US"],
                ["2026-01-01 09:30:00", "LOSS", "buy", "10", "100", "0", "USD", "US"],
                ["2026-01-11 09:30:00", "LOSS", "sell", "10", "95", "0", "USD", "US"],
            ],
        ),
    )
    strategy = extract_confirmed_strategy(store, report.id)

    shadow_report = ShadowAccountService(store).run_report(ShadowReportRunRequest(strategy_id=strategy.id))
    events = store.list_shadow_events(shadow_report_id=shadow_report.id)

    assert any(event.event_type == ShadowEventType.EARLY_EXIT for event in events)


def test_shadow_report_flags_thesis_mismatch_for_trade_without_active_confirmed_thesis(tmp_path) -> None:
    store = make_store(tmp_path)
    report = import_and_report(
        store,
        write_csv(
            tmp_path / "no_thesis.csv",
            [
                ["2026-01-01 09:30:00", "NTHS", "buy", "10", "100", "0", "USD", "US"],
                ["2026-01-03 09:30:00", "NTHS", "sell", "10", "102", "0", "USD", "US"],
            ],
        ),
    )
    strategy = extract_confirmed_strategy(store, report.id)

    shadow_report = ShadowAccountService(store).run_report(ShadowReportRunRequest(strategy_id=strategy.id))
    events = store.list_shadow_events(shadow_report_id=shadow_report.id)

    assert any(event.event_type == ShadowEventType.THESIS_MISMATCH for event in events)
    assert shadow_report.diagnostics["thesis_mismatch_count"] >= 1


def test_shadow_report_flags_high_impact_catalyst_violation(tmp_path) -> None:
    store = make_store(tmp_path)
    store.create_thesis(
        Thesis(
            symbol="AAPL",
            side=ThesisSide.LONG,
            thesis_statement="Active human-confirmed thesis for catalyst test.",
            status=ThesisStatus.ACTIVE,
            human_confirmed=True,
        )
    )
    report = import_and_report(
        store,
        write_csv(
            tmp_path / "catalyst.csv",
            [
                ["2026-01-01 09:30:00", "AAPL", "buy", "10", "100", "0", "USD", "US"],
                ["2026-01-03 09:30:00", "AAPL", "sell", "10", "101", "0", "USD", "US"],
            ],
        ),
    )
    CatalystCalendarService(store).create_catalyst(
        CatalystCreate(
            symbol="AAPL",
            event_type=CatalystEventType.EARNINGS,
            title="AAPL high-impact earnings",
            event_date=datetime(2026, 1, 2, 9, 30, tzinfo=timezone.utc),
            expected_impact=CatalystExpectedImpact.HIGH,
            status=CatalystStatus.UPCOMING,
        )
    )
    strategy = extract_confirmed_strategy(store, report.id)

    shadow_report = ShadowAccountService(store).run_report(ShadowReportRunRequest(strategy_id=strategy.id))
    events = store.list_shadow_events(shadow_report_id=shadow_report.id)

    assert any(event.event_type == ShadowEventType.IGNORED_CATALYST for event in events)


def test_shadow_report_handles_missing_quote_history_without_fake_pnl(tmp_path) -> None:
    store = make_store(tmp_path)
    report = import_and_report(
        store,
        write_csv(
            tmp_path / "missing_quotes.csv",
            [
                ["2026-01-01 09:30:00", "AAPL", "buy", "10", "100", "0", "USD", "US"],
                ["2026-01-03 09:30:00", "AAPL", "sell", "10", "110", "0", "USD", "US"],
            ],
        ),
    )
    strategy = extract_confirmed_strategy(store, report.id)

    shadow_report = ShadowAccountService(store).run_report(ShadowReportRunRequest(strategy_id=strategy.id))
    run_card = store.get_run_card(shadow_report.run_card_id)

    assert shadow_report.counterfactual_pnl is None
    assert shadow_report.delta_pnl is None
    assert run_card is not None
    assert any("counterfactual_pnl is unavailable" in warning for warning in run_card.warnings)


def test_shadow_events_are_readable_from_store(tmp_path) -> None:
    store = make_store(tmp_path)
    report = import_and_report(
        store,
        write_csv(
            tmp_path / "readable.csv",
            [
                ["2026-01-01 09:30:00", "READ", "buy", "10", "100", "0", "USD", "US"],
                ["2026-01-03 09:30:00", "READ", "sell", "10", "90", "0", "USD", "US"],
            ],
        ),
    )
    strategy = extract_confirmed_strategy(store, report.id)
    shadow_report = ShadowAccountService(store).run_report(ShadowReportRunRequest(strategy_id=strategy.id))

    assert store.get_shadow_report(shadow_report.id) is not None
    assert store.list_shadow_reports(strategy_id=strategy.id)
    assert store.list_shadow_events(shadow_report_id=shadow_report.id)

