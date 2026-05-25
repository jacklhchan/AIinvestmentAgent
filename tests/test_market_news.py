from __future__ import annotations

from invest_agent.config import Settings
from invest_agent.market_news import (
    news_items_from_finnhub,
    news_items_from_gdelt,
    news_items_from_google_news,
    resolve_watchlist_symbols,
)
from invest_agent.models import Quote
from invest_agent.store import Store


def test_gdelt_payload_maps_to_news_items() -> None:
    items = news_items_from_gdelt(
        "US.AAPL",
        {
            "articles": [
                {
                    "title": "Apple shares rise after strong services demand",
                    "url": "https://example.com/aapl",
                    "domain": "example.com",
                    "seendate": "20260525T100000Z",
                }
            ]
        },
        limit=5,
    )

    assert items[0].symbol == "US.AAPL"
    assert items[0].source == "gdelt"
    assert items[0].url == "https://example.com/aapl"
    assert items[0].published_at.year == 2026


def test_finnhub_payload_maps_to_news_items() -> None:
    items = news_items_from_finnhub(
        "MSFT",
        [
            {
                "headline": "Microsoft raises AI capex guidance",
                "summary": "Management noted demand remains strong.",
                "url": "https://example.com/msft",
                "datetime": 1780000000,
            }
        ],
        limit=5,
    )

    assert items[0].symbol == "MSFT"
    assert items[0].source == "finnhub"
    assert "guidance" in items[0].title.lower()


def test_google_news_rss_maps_to_news_items() -> None:
    items = news_items_from_google_news(
        "AAPL",
        """
        <rss><channel><item>
          <title>Apple stock gains as demand improves</title>
          <link>https://news.google.com/articles/example</link>
          <pubDate>Mon, 25 May 2026 10:00:00 GMT</pubDate>
          <source>Example News</source>
        </item></channel></rss>
        """,
        limit=5,
    )

    assert items[0].symbol == "AAPL"
    assert items[0].source == "google-news"
    assert "demand" in items[0].title.lower()


def test_watchlist_prefers_market_prefixed_symbols(tmp_path) -> None:
    settings = Settings(db_path=tmp_path / "test.db", watchlist_symbols="AAPL,MSFT")
    store = Store(settings.db_path)
    store.upsert_quote(Quote(symbol="US.AAPL", last_price=190.0, source="futu-opend"))

    assert resolve_watchlist_symbols(settings, store) == ["US.AAPL", "MSFT"]
