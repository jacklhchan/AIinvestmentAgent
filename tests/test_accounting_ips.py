from __future__ import annotations

import csv
from datetime import datetime
from pathlib import Path

from invest_agent.accounting import CanonicalAccountingService
from invest_agent.advisor_orchestrator import AdvisorOrchestrator
from invest_agent.config import Settings
from invest_agent.demo_data import seed_demo_data
from invest_agent.models import (
    AccountingTransactionCreate,
    AccountingTransactionType,
    AdvisorProfileConfirmationRequest,
    AdvisorProfileUpdateRequest,
    RunCardActor,
    TaxLotStatus,
    TradeJournalImportRequest,
    TradeJournalSource,
)
from invest_agent.schema_checks import run_schema_check
from invest_agent.store import Store
from invest_agent.trade_journal import TradeJournalService


def make_store(tmp_path: Path) -> Store:
    settings = Settings(db_path=tmp_path / "test.db")
    store = Store(settings.db_path)
    seed_demo_data(store, force=True)
    return store


def write_trade_csv(path: Path) -> Path:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["datetime", "symbol", "side", "quantity", "price", "fee", "currency", "market"])
        writer.writerows(
            [
                ["2026-01-01 09:30:00", "AAPL", "buy", "10", "100", "1", "USD", "US"],
                ["2026-01-05 09:30:00", "AAPL", "sell", "4", "120", "1", "USD", "US"],
            ]
        )
    return path


def record_accounting_transaction(
    service: CanonicalAccountingService,
    *,
    transaction_type: AccountingTransactionType,
    symbol: str | None = None,
    quantity: float | None = None,
    price: float | None = None,
    gross_amount: float | None = None,
    fees: float = 0.0,
    taxes: float = 0.0,
    occurred_at: str = "2026-01-01T09:30:00+00:00",
):
    return service.record_transaction(
        AccountingTransactionCreate(
            transaction_type=transaction_type,
            symbol=symbol,
            quantity=quantity,
            price=price,
            gross_amount=gross_amount,
            fees=fees,
            taxes=taxes,
            occurred_at=datetime.fromisoformat(occurred_at),
        )
    )


def test_accounting_sync_builds_fifo_lots_and_snapshot_without_proposals(tmp_path) -> None:
    store = make_store(tmp_path)
    before_proposals = len(store.list_proposals(limit=100))
    before_executions = len(store.list_executions())
    TradeJournalService(store).import_csv(
        TradeJournalImportRequest(path=str(write_trade_csv(tmp_path / "trades.csv")), source=TradeJournalSource.GENERIC_CSV),
        actor=RunCardActor.CLI,
    )

    snapshot = CanonicalAccountingService(store).sync_from_trade_journal(actor=RunCardActor.CLI)
    transactions = store.list_accounting_transactions(ascending=True)
    lots = store.list_accounting_tax_lots(symbol="AAPL")
    open_lots = store.list_accounting_tax_lots(symbol="AAPL", status=TaxLotStatus.OPEN)

    assert len(transactions) == 2
    assert len(lots) == 1
    assert len(open_lots) == 1
    assert open_lots[0].quantity_open == 6
    assert round(open_lots[0].cost_basis_open, 2) == 600.6
    assert round(open_lots[0].realized_pnl, 2) == 78.6
    assert snapshot.run_card_id
    assert snapshot.positions[0].symbol == "AAPL"
    assert snapshot.positions[0].quantity == 6
    assert round(snapshot.positions[0].avg_cost, 2) == 100.1
    assert round(snapshot.cash_by_currency["USD"], 2) == -522.0
    assert round(snapshot.realized_pnl_by_symbol["AAPL"], 2) == 78.6
    assert len(store.list_proposals(limit=100)) == before_proposals
    assert len(store.list_executions()) == before_executions


def test_fifo_sell_across_multiple_lots(tmp_path) -> None:
    store = make_store(tmp_path)
    service = CanonicalAccountingService(store)

    record_accounting_transaction(
        service,
        transaction_type=AccountingTransactionType.BUY,
        symbol="AAPL",
        quantity=100,
        price=10,
        occurred_at="2026-01-01T09:30:00+00:00",
    )
    record_accounting_transaction(
        service,
        transaction_type=AccountingTransactionType.BUY,
        symbol="AAPL",
        quantity=100,
        price=20,
        occurred_at="2026-01-02T09:30:00+00:00",
    )
    snapshot = record_accounting_transaction(
        service,
        transaction_type=AccountingTransactionType.SELL,
        symbol="AAPL",
        quantity=150,
        price=30,
        occurred_at="2026-01-03T09:30:00+00:00",
    )

    lots = store.list_accounting_tax_lots(symbol="AAPL")
    open_lots = store.list_accounting_tax_lots(symbol="AAPL", status=TaxLotStatus.OPEN)

    assert len(lots) == 2
    assert len(open_lots) == 1
    assert open_lots[0].quantity_open == 50
    assert open_lots[0].cost_basis_open == 1000
    assert snapshot.positions[0].quantity == 50
    assert snapshot.positions[0].avg_cost == 20
    assert snapshot.cash_by_currency["USD"] == 1500
    assert snapshot.realized_pnl_by_symbol["AAPL"] == 2500


def test_sell_more_than_available_is_flagged_without_creating_short_lot(tmp_path) -> None:
    store = make_store(tmp_path)
    service = CanonicalAccountingService(store)

    record_accounting_transaction(
        service,
        transaction_type=AccountingTransactionType.BUY,
        symbol="MSFT",
        quantity=10,
        price=100,
        occurred_at="2026-01-01T09:30:00+00:00",
    )
    snapshot = record_accounting_transaction(
        service,
        transaction_type=AccountingTransactionType.SELL,
        symbol="MSFT",
        quantity=12,
        price=110,
        occurred_at="2026-01-02T09:30:00+00:00",
    )

    assert snapshot.positions == []
    assert store.list_accounting_tax_lots(symbol="MSFT", status=TaxLotStatus.OPEN) == []
    assert snapshot.realized_pnl_by_symbol["MSFT"] == 100
    assert any("exceeds available FIFO lots" in warning for warning in snapshot.warnings)


def test_accounting_records_dividend_and_withholding(tmp_path) -> None:
    store = make_store(tmp_path)
    service = CanonicalAccountingService(store)

    snapshot = service.record_transaction(
        AccountingTransactionCreate(
            transaction_type=AccountingTransactionType.DIVIDEND,
            symbol="VOO",
            gross_amount=10.0,
            taxes=3.0,
            currency="USD",
            source_id="dividend-test",
        )
    )

    assert snapshot.dividend_income_by_symbol["VOO"] == 10.0
    assert snapshot.tax_withheld_by_currency["USD"] == 3.0
    assert snapshot.cash_by_currency["USD"] == 7.0


def test_standalone_fee_affects_cash_and_fee_summary_once(tmp_path) -> None:
    store = make_store(tmp_path)

    snapshot = record_accounting_transaction(
        CanonicalAccountingService(store),
        transaction_type=AccountingTransactionType.FEE,
        gross_amount=5.0,
    )

    assert snapshot.cash_by_currency["USD"] == -5.0
    assert snapshot.fees_by_currency["USD"] == 5.0


def test_accounting_sync_from_journal_is_idempotent(tmp_path) -> None:
    store = make_store(tmp_path)
    TradeJournalService(store).import_csv(
        TradeJournalImportRequest(path=str(write_trade_csv(tmp_path / "trades.csv")), source=TradeJournalSource.GENERIC_CSV),
        actor=RunCardActor.CLI,
    )
    service = CanonicalAccountingService(store)

    first = service.sync_from_trade_journal(actor=RunCardActor.CLI)
    first_lots = [
        (lot.symbol, lot.status, lot.quantity_open, lot.cost_basis_open, lot.realized_pnl)
        for lot in store.list_accounting_tax_lots(symbol="AAPL")
    ]
    second = service.sync_from_trade_journal(actor=RunCardActor.CLI)
    second_lots = [
        (lot.symbol, lot.status, lot.quantity_open, lot.cost_basis_open, lot.realized_pnl)
        for lot in store.list_accounting_tax_lots(symbol="AAPL")
    ]

    assert len(store.list_accounting_transactions(ascending=True)) == 2
    assert second.transaction_count == first.transaction_count == 2
    assert second.open_lot_count == first.open_lot_count == 1
    assert second.positions == first.positions
    assert second.cash_by_currency == first.cash_by_currency
    assert second.realized_pnl_by_symbol == first.realized_pnl_by_symbol
    assert second_lots == first_lots


def test_confirmed_advisor_profile_creates_investor_policy_statement(tmp_path) -> None:
    store = make_store(tmp_path)
    orchestrator = AdvisorOrchestrator(store, settings=Settings(db_path=tmp_path / "test.db"))
    update = orchestrator.suggest_profile_update(
        AdvisorProfileUpdateRequest(
            risk_profile="growth",
            max_single_stock_weight=0.2,
            max_tech_exposure=0.4,
            min_cash_weight=0.2,
            allow_options=False,
            notes=["投資取向：中長期為主，可以承受中高風險。"],
            rationale="User confirmed medium-to-long term growth profile.",
        )
    )

    orchestrator.confirm_profile_update(update.id, AdvisorProfileConfirmationRequest(confirmed_by="test-user"))
    policy = store.get_investor_policy_statement()

    assert policy is not None
    assert policy.version == 1
    assert policy.source_profile_version == 1
    assert policy.risk_profile.value == "growth"
    assert policy.investment_horizon == "medium_to_long_term"
    assert policy.max_single_stock_weight == 0.2
    assert policy.max_tech_exposure == 0.4
    assert policy.min_cash_weight == 0.2
    assert policy.max_drawdown_tolerance == 0.3
    assert policy.core_satellite_target == {"core": 0.6, "satellite": 0.4}
    assert "options_without_explicit_user_request" in policy.prohibited_assets


def test_rejected_advisor_profile_update_does_not_create_investor_policy_statement(tmp_path) -> None:
    store = make_store(tmp_path)
    orchestrator = AdvisorOrchestrator(store, settings=Settings(db_path=tmp_path / "test.db"))
    update = orchestrator.suggest_profile_update(
        AdvisorProfileUpdateRequest(
            risk_profile="growth",
            notes=["投資取向：中長期為主，可以承受中高風險。"],
            rationale="User mentioned a preference but did not confirm applying it.",
        )
    )

    orchestrator.confirm_profile_update(
        update.id,
        AdvisorProfileConfirmationRequest(confirmed=False, confirmed_by="test-user", rejection_reason="Not now"),
    )

    assert store.get_advisor_profile() is None
    assert store.get_investor_policy_statement() is None


def test_schema_check_includes_accounting_and_ips_tables(tmp_path) -> None:
    store = make_store(tmp_path)

    result = run_schema_check(store)

    assert result["ok"] is True
    assert not result["missing_tables"]
