from __future__ import annotations

import csv
from pathlib import Path

from invest_agent.config import Settings
from invest_agent.demo_data import seed_demo_data
from invest_agent.models import (
    BehaviorReportRunRequest,
    BehaviorSeverity,
    RunCardActor,
    RunCardType,
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


def write_csv(path: Path, headers: list[str], rows: list[list[str]]) -> Path:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(headers)
        writer.writerows(rows)
    return path


def import_generic(store: Store, path: Path):
    return TradeJournalService(store).import_csv(
        TradeJournalImportRequest(path=str(path), source=TradeJournalSource.GENERIC_CSV),
        actor=RunCardActor.CLI,
    )


def test_import_generic_trade_journal_csv_creates_fills(tmp_path) -> None:
    store = make_store(tmp_path)
    path = write_csv(
        tmp_path / "generic.csv",
        ["datetime", "symbol", "side", "quantity", "price", "fee", "currency", "market"],
        [
            ["2026-01-01 09:30:00", "AAPL", "buy", "10", "100", "1", "USD", "US"],
            ["2026-01-02 10:00:00", "AAPL", "sell", "5", "110", "0.5", "USD", "US"],
        ],
    )

    trade_import = import_generic(store, path)
    fills = store.list_trade_fills(symbol="AAPL", ascending=True)

    assert trade_import.row_count == 2
    assert len(fills) == 2
    assert fills[0].symbol == "AAPL"
    assert fills[0].qty == 10
    assert fills[1].side == "sell"


def test_import_futu_trade_journal_csv_alias_mapping(tmp_path) -> None:
    store = make_store(tmp_path)
    path = write_csv(
        tmp_path / "futu.csv",
        ["成交時間", "代碼", "買賣方向", "成交數量", "成交價格", "費用", "幣種", "訂單號", "成交號"],
        [["2026/01/01 09:30:00", "US.AAPL", "買入", "10", "100", "1", "USD", "ord1", "trade1"]],
    )

    trade_import = TradeJournalService(store).import_csv(
        TradeJournalImportRequest(path=str(path), source=TradeJournalSource.FUTU_CSV),
        actor=RunCardActor.CLI,
    )
    fill = store.list_trade_fills(symbol="US.AAPL")[0]

    assert trade_import.source == TradeJournalSource.FUTU_CSV
    assert fill.broker == "futu"
    assert fill.broker_order_id == "ord1"
    assert fill.broker_trade_id == "trade1"


def test_duplicate_import_file_hash_is_idempotent(tmp_path) -> None:
    store = make_store(tmp_path)
    path = write_csv(
        tmp_path / "generic.csv",
        ["datetime", "symbol", "side", "quantity", "price", "fee", "currency", "market"],
        [
            ["2026-01-01 09:30:00", "AAPL", "buy", "10", "100", "1", "USD", "US"],
            ["2026-01-02 10:00:00", "AAPL", "sell", "5", "110", "0.5", "USD", "US"],
        ],
    )

    first = import_generic(store, path)
    second = import_generic(store, path)

    assert second.id == first.id
    assert len(store.list_trade_imports()) == 1
    assert len(store.list_trade_fills(symbol="AAPL")) == 2


def test_fifo_roundtrip_pairing_partial_sell(tmp_path) -> None:
    store = make_store(tmp_path)
    path = write_csv(
        tmp_path / "roundtrip.csv",
        ["datetime", "symbol", "side", "quantity", "price", "fee", "currency", "market"],
        [
            ["2026-01-01 09:30:00", "AAPL", "buy", "10", "100", "1", "USD", "US"],
            ["2026-01-02 10:00:00", "AAPL", "sell", "4", "110", "0.4", "USD", "US"],
            ["2026-01-03 10:00:00", "AAPL", "sell", "6", "90", "0.6", "USD", "US"],
        ],
    )
    import_generic(store, path)

    report = TradeJournalService(store).run_behavior_report(BehaviorReportRunRequest())
    roundtrips = store.list_trade_roundtrips(symbol="AAPL", limit=10)

    assert report.total_roundtrips == 2
    assert sorted(roundtrip.qty for roundtrip in roundtrips) == [4, 6]
    assert round(report.total_realized_pnl, 2) == -22.0
    assert round(report.win_rate, 2) == 0.5
    assert round(report.profit_loss_ratio, 2) == 0.64
    assert round(report.max_drawdown, 2) == -61.2


def test_disposition_effect_flags_holding_losers_longer(tmp_path) -> None:
    store = make_store(tmp_path)
    path = write_csv(
        tmp_path / "disposition.csv",
        ["datetime", "symbol", "side", "quantity", "price", "fee", "currency", "market"],
        [
            ["2026-01-01 09:30:00", "WIN", "buy", "10", "100", "0", "USD", "US"],
            ["2026-01-02 09:30:00", "WIN", "sell", "10", "110", "0", "USD", "US"],
            ["2026-01-01 09:30:00", "LOSS", "buy", "10", "100", "0", "USD", "US"],
            ["2026-01-07 09:30:00", "LOSS", "sell", "10", "90", "0", "USD", "US"],
        ],
    )
    import_generic(store, path)

    report = TradeJournalService(store).run_behavior_report(BehaviorReportRunRequest())

    assert report.diagnostics["disposition_effect"].severity == BehaviorSeverity.HIGH


def test_overtrading_flags_busy_day_underperformance(tmp_path) -> None:
    store = make_store(tmp_path)
    path = write_csv(
        tmp_path / "overtrading.csv",
        ["datetime", "symbol", "side", "quantity", "price", "fee", "currency", "market"],
        [
            ["2026-01-01 09:30:00", "Q1", "buy", "10", "100", "0", "USD", "US"],
            ["2026-01-01 10:00:00", "Q1", "sell", "10", "110", "0", "USD", "US"],
            ["2026-01-02 09:30:00", "Q2", "buy", "10", "100", "0", "USD", "US"],
            ["2026-01-02 10:00:00", "Q2", "sell", "10", "105", "0", "USD", "US"],
            ["2026-01-03 09:30:00", "B1", "buy", "10", "100", "0", "USD", "US"],
            ["2026-01-03 10:00:00", "B1", "sell", "10", "90", "0", "USD", "US"],
            ["2026-01-03 11:00:00", "B2", "buy", "10", "100", "0", "USD", "US"],
            ["2026-01-03 12:00:00", "B2", "sell", "10", "95", "0", "USD", "US"],
        ],
    )
    import_generic(store, path)

    report = TradeJournalService(store).run_behavior_report(BehaviorReportRunRequest())

    assert report.diagnostics["overtrading"].severity == BehaviorSeverity.HIGH


def test_chasing_momentum_flags_repeat_buy_after_runup(tmp_path) -> None:
    store = make_store(tmp_path)
    path = write_csv(
        tmp_path / "chasing.csv",
        ["datetime", "symbol", "side", "quantity", "price", "fee", "currency", "market"],
        [
            ["2026-01-01 09:30:00", "AAPL", "buy", "1", "100", "0", "USD", "US"],
            ["2026-01-02 09:30:00", "AAPL", "buy", "1", "102", "0", "USD", "US"],
            ["2026-01-03 09:30:00", "AAPL", "buy", "1", "104", "0", "USD", "US"],
            ["2026-01-04 09:30:00", "AAPL", "buy", "1", "108", "0", "USD", "US"],
        ],
    )
    import_generic(store, path)

    report = TradeJournalService(store).run_behavior_report(BehaviorReportRunRequest())

    assert report.diagnostics["chasing_momentum"].severity == BehaviorSeverity.HIGH


def test_anchoring_flags_repeated_trades_in_narrow_price_band(tmp_path) -> None:
    store = make_store(tmp_path)
    path = write_csv(
        tmp_path / "anchoring.csv",
        ["datetime", "symbol", "side", "quantity", "price", "fee", "currency", "market"],
        [
            ["2026-01-01 09:30:00", "MSFT", "buy", "1", "100", "0", "USD", "US"],
            ["2026-01-02 09:30:00", "MSFT", "buy", "1", "101", "0", "USD", "US"],
            ["2026-01-03 09:30:00", "MSFT", "buy", "1", "99", "0", "USD", "US"],
            ["2026-01-04 09:30:00", "MSFT", "buy", "1", "100.5", "0", "USD", "US"],
            ["2026-01-05 09:30:00", "MSFT", "buy", "1", "100.2", "0", "USD", "US"],
        ],
    )
    import_generic(store, path)

    report = TradeJournalService(store).run_behavior_report(BehaviorReportRunRequest())

    assert report.diagnostics["anchoring"].severity == BehaviorSeverity.HIGH


def test_behavior_report_creates_run_card_with_dataset_hash(tmp_path) -> None:
    store = make_store(tmp_path)
    path = write_csv(
        tmp_path / "generic.csv",
        ["datetime", "symbol", "side", "quantity", "price", "fee", "currency", "market"],
        [
            ["2026-01-01 09:30:00", "AAPL", "buy", "10", "100", "0", "USD", "US"],
            ["2026-01-02 09:30:00", "AAPL", "sell", "10", "110", "0", "USD", "US"],
        ],
    )
    import_generic(store, path)

    report = TradeJournalService(store).run_behavior_report(BehaviorReportRunRequest())
    run_card = store.get_run_card(report.run_card_id)

    assert run_card.run_type == RunCardType.BEHAVIOR_REPORT
    assert run_card.dataset_hash
    assert run_card.outputs["behavior_report_id"] == report.id


def test_mcp_can_read_behavior_reports_but_not_import_files() -> None:
    import invest_agent.mcp_server as mcp_server

    assert hasattr(mcp_server, "list_behavior_reports")
    assert hasattr(mcp_server, "get_behavior_report")
    assert hasattr(mcp_server, "list_trade_roundtrips")
    assert not hasattr(mcp_server, "import_trade_journal")
