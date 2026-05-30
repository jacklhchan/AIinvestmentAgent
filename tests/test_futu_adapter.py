from __future__ import annotations

import pytest

from invest_agent.config import Settings
from invest_agent.futu_adapter import (
    FutuIntegrationError,
    FutuReadDisabled,
    _disable_futu_console_logging,
    _portfolio_from_records,
    _positions_from_records,
    _quotes_from_records,
    discover_futu_accounts,
    refresh_futu_account_snapshot,
    refresh_futu_readonly,
)
from invest_agent.models import PortfolioSnapshot
from invest_agent.store import Store


def test_futu_read_disabled_refuses_to_connect(tmp_path) -> None:
    settings = Settings(db_path=tmp_path / "test.db", futu_read_enabled=False)
    store = Store(settings.db_path)

    with pytest.raises(FutuReadDisabled):
        refresh_futu_readonly(settings, store)


def test_futu_console_logging_is_disabled_for_mcp_stdio() -> None:
    class Logger:
        disabled = False

        @classmethod
        def enable_console_log(cls, enabled: bool) -> None:
            cls.disabled = not enabled

    class FtLogger:
        logger = Logger

    class Common:
        ft_logger = FtLogger

    class FutuModule:
        common = Common

    _disable_futu_console_logging(FutuModule)

    assert Logger.disabled is True


def test_position_and_portfolio_record_mapping() -> None:
    positions = _positions_from_records(
        [
            {
                "code": "US.AAPL",
                "qty": 10,
                "market_val": 1910.0,
                "average_cost": 180.0,
                "nominal_price": 191.0,
                "pl_val": 110.0,
            }
        ]
    )
    portfolio = _portfolio_from_records(
        [{"us_cash": 500.0, "total_assets": 2410.0}],
        positions,
    )

    assert positions[0].symbol == "US.AAPL"
    assert positions[0].qty == 10
    assert positions[0].last_price == 191.0
    assert portfolio.cash_usd == 500.0
    assert portfolio.total_value_usd == 2410.0
    assert portfolio.source == "futu-opend"


def test_quote_record_mapping() -> None:
    quotes = _quotes_from_records(
        [
            {
                "code": "US.AAPL",
                "last_price": 191.0,
                "bid_price": 190.9,
                "ask_price": 191.1,
            },
            {
                "code": "HK.00700",
                "last_price": 390.0,
            },
        ]
    )

    assert quotes[0].symbol == "US.AAPL"
    assert quotes[0].currency == "USD"
    assert quotes[0].bid == 190.9
    assert quotes[1].currency == "HKD"


def test_wrong_futu_acc_id_lists_available_candidates(tmp_path, monkeypatch) -> None:
    settings = Settings(db_path=tmp_path / "test.db", futu_read_enabled=True, futu_acc_id=999999, futu_trd_env="REAL")
    store = Store(settings.db_path)
    monkeypatch.setattr("invest_agent.futu_adapter._load_futu", lambda: _dummy_futu(accounts=[_account(17875763)]))

    discovery = discover_futu_accounts(settings)

    assert discovery.selection_status == "error"
    assert discovery.candidate_acc_ids == [17875763]
    with pytest.raises(FutuIntegrationError, match="Available candidate acc_id values: 17875763"):
        refresh_futu_account_snapshot(settings, store)


def test_quote_refresh_succeeds_while_account_snapshot_fails(tmp_path, monkeypatch) -> None:
    settings = Settings(
        db_path=tmp_path / "test.db",
        futu_read_enabled=True,
        futu_acc_id=999999,
        watchlist_symbols="AAPL",
        market_context_symbols="SPY",
    )
    store = Store(settings.db_path)
    store.upsert_portfolio(PortfolioSnapshot(positions=[], source="test"))
    monkeypatch.setattr(
        "invest_agent.futu_adapter._load_futu",
        lambda: _dummy_futu(accounts=[_account(17875763)], quote_prices={"US.AAPL": 190.0, "US.SPY": 500.0}),
    )

    result = refresh_futu_readonly(settings, store)

    assert result.quote_status == "ok"
    assert result.account_status == "error"
    assert "Configured FUTU_ACC_ID 999999 is not available" in result.account_error
    assert {quote.symbol for quote in store.list_quotes()} == {"US.AAPL", "US.SPY"}
    assert store.list_audit_events(event_type="futu_quotes_refreshed")
    assert store.list_audit_events(event_type="futu_account_snapshot_failed")


def test_account_discovery_requires_explicit_selection_when_ambiguous(tmp_path, monkeypatch) -> None:
    settings = Settings(db_path=tmp_path / "test.db", futu_read_enabled=True, futu_acc_id=0)
    monkeypatch.setattr(
        "invest_agent.futu_adapter._load_futu",
        lambda: _dummy_futu(accounts=[_account(111), _account(222)]),
    )

    discovery = discover_futu_accounts(settings)

    assert discovery.selection_status == "warn"
    assert discovery.selected_account is None
    assert discovery.candidate_acc_ids == [111, 222]
    assert "set FUTU_ACC_ID explicitly" in discovery.message


def _account(acc_id: int) -> dict:
    return {
        "acc_id": acc_id,
        "trd_env": "REAL",
        "trdmarket_auth": ["US"],
        "security_firm": "FUTUINC",
        "sim_acc_type": "",
    }


def _dummy_futu(*, accounts: list[dict], quote_prices: dict[str, float] | None = None):
    quote_prices = quote_prices or {}

    class DummyFutu:
        RET_OK = 0
        RET_ERROR = -1

        class TrdMarket:
            US = "US"
            NONE = "NONE"

        class TrdEnv:
            REAL = "REAL"
            SIMULATE = "SIMULATE"

        class Currency:
            USD = "USD"

        class OpenQuoteContext:
            def __init__(self, **_kwargs):
                pass

            def get_market_snapshot(self, symbols):
                return DummyFutu.RET_OK, [
                    {"code": symbol, "last_price": quote_prices.get(symbol, 100.0), "prev_close_price": 99.0}
                    for symbol in symbols
                ]

            def close(self):
                pass

        class OpenSecTradeContext:
            def __init__(self, **_kwargs):
                pass

            def get_acc_list(self):
                return DummyFutu.RET_OK, accounts

            def accinfo_query(self, **_kwargs):
                return DummyFutu.RET_OK, [{"us_cash": 5000.0, "total_assets": 5000.0}]

            def position_list_query(self, **_kwargs):
                return DummyFutu.RET_OK, []

            def close(self):
                pass

    return DummyFutu
