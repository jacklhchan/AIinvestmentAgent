from __future__ import annotations

from datetime import timedelta

from .models import NewsItem, PortfolioSnapshot, Position, Quote, utc_now
from .store import Store


def seed_demo_data(store: Store, force: bool = False) -> None:
    portfolio = store.get_portfolio()
    if portfolio.positions and not force:
        return

    now = utc_now()
    snapshot = PortfolioSnapshot(
        cash_usd=27500.0,
        total_value_usd=126850.0,
        source="demo",
        updated_at=now,
        positions=[
            Position(symbol="AAPL", qty=90, market_value=17190.0, avg_cost=178.35, last_price=191.0, unrealized_pl=1138.5),
            Position(symbol="MSFT", qty=55, market_value=23980.0, avg_cost=402.1, last_price=436.0, unrealized_pl=1864.5),
            Position(symbol="NVDA", qty=130, market_value=18135.0, avg_cost=122.2, last_price=139.5, unrealized_pl=2249.0),
        ],
    )
    store.upsert_portfolio(snapshot)

    for quote in [
        Quote(symbol="AAPL", last_price=191.0, bid=190.92, ask=191.08, updated_at=now, source="demo"),
        Quote(symbol="MSFT", last_price=436.0, bid=435.88, ask=436.14, updated_at=now, source="demo"),
        Quote(symbol="NVDA", last_price=139.5, bid=139.42, ask=139.61, updated_at=now, source="demo"),
        Quote(symbol="GOOGL", last_price=175.7, bid=175.61, ask=175.84, updated_at=now, source="demo"),
    ]:
        store.upsert_quote(quote)

    for item in [
        NewsItem(
            id="demo_news_nvda_demand",
            symbol="NVDA",
            title="NVDA supplier commentary suggests AI accelerator demand remains firm",
            source="demo",
            published_at=now - timedelta(minutes=22),
            tags=["semis", "supply-chain"],
            summary="Demo signal only. Treat as research input, not a trading instruction.",
        ),
        NewsItem(
            id="demo_news_aapl_services",
            symbol="AAPL",
            title="AAPL services margin discussion returns to analyst notes",
            source="demo",
            published_at=now - timedelta(hours=1, minutes=10),
            tags=["earnings", "services"],
            summary="Useful for watchlist context. Needs verification against primary sources.",
        ),
        NewsItem(
            id="demo_news_macro_regime",
            symbol=None,
            title="Macro dashboard: US yields and USD strength should be reviewed before risk-on proposals",
            source="demo",
            published_at=now - timedelta(hours=2),
            tags=["macro", "regime"],
            summary="Portfolio-level guardrail reminder for the slow loop.",
        ),
    ]:
        store.upsert_news(item)

    store.audit("demo_seeded", "system", "demo", {"force": force})
