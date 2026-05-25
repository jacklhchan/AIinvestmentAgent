from __future__ import annotations

import pytest

from invest_agent.config import Settings
from invest_agent.futu_adapter import (
    FutuReadDisabled,
    _portfolio_from_records,
    _positions_from_records,
    _quotes_from_records,
    refresh_futu_readonly,
)
from invest_agent.store import Store


def test_futu_read_disabled_refuses_to_connect(tmp_path) -> None:
    settings = Settings(db_path=tmp_path / "test.db", futu_read_enabled=False)
    store = Store(settings.db_path)

    with pytest.raises(FutuReadDisabled):
        refresh_futu_readonly(settings, store)


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
