from __future__ import annotations

import httpx

from invest_agent.config import Settings
from invest_agent.market_news import (
    MarketNewsIngestor,
    news_items_from_finnhub,
    news_items_from_gdelt,
    news_items_from_google_news,
    resolve_watchlist_symbols,
)
from invest_agent.models import NewsItem, Quote
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


def test_watchlist_dedupes_alphabet_share_classes_by_economic_exposure(tmp_path) -> None:
    settings = Settings(db_path=tmp_path / "test.db", watchlist_symbols="GOOGL")
    store = Store(settings.db_path)
    store.upsert_quote(Quote(symbol="US.GOOG", last_price=175.0, source="futu-opend"))

    assert resolve_watchlist_symbols(settings, store, symbols=["GOOG", "GOOGL"]) == ["GOOG"]
    assert resolve_watchlist_symbols(settings, store) == ["US.GOOG"]


def test_google_news_can_run_when_gdelt_is_disabled(tmp_path, monkeypatch) -> None:
    settings = Settings(db_path=tmp_path / "test.db")
    store = Store(settings.db_path)

    def fail_gdelt(*args, **kwargs):
        raise AssertionError("GDELT should not run")

    def fake_google(self, client, symbol, *, limit):
        return [NewsItem(symbol=symbol, title="Market context fallback item", source="google-news")]

    monkeypatch.setattr(MarketNewsIngestor, "fetch_gdelt", fail_gdelt)
    monkeypatch.setattr(MarketNewsIngestor, "fetch_google_news", fake_google)

    result = MarketNewsIngestor(settings, store).refresh_news(
        symbols=["SPY"],
        include_gdelt=False,
        include_google_news=True,
        include_finnhub=False,
    )

    assert result.stored_count == 1
    assert result.sources == {"google-news": 1}


def test_finnhub_requests_are_throttled_between_calls(tmp_path, monkeypatch) -> None:
    settings = Settings(
        db_path=tmp_path / "test.db",
        finnhub_api_key="test-key",
        finnhub_min_interval_seconds=1.2,
        finnhub_max_retries=0,
    )
    store = Store(settings.db_path)
    current_time = [100.0]
    sleeps: list[float] = []

    def fake_monotonic() -> float:
        return current_time[0]

    def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)
        current_time[0] += seconds

    monkeypatch.setattr("invest_agent.market_news.time.monotonic", fake_monotonic)
    monkeypatch.setattr("invest_agent.market_news.time.sleep", fake_sleep)

    class FakeClient:
        def get(self, url, *, params):
            return httpx.Response(
                200,
                json=[
                    {
                        "headline": f"News for {params['symbol']}",
                        "summary": "ok",
                        "url": f"https://example.com/{params['symbol']}",
                        "datetime": 1780000000,
                    }
                ],
                request=httpx.Request("GET", url),
            )

    ingestor = MarketNewsIngestor(settings, store)
    ingestor.fetch_finnhub(FakeClient(), "AAPL", days=1, limit=1)
    ingestor.fetch_finnhub(FakeClient(), "MSFT", days=1, limit=1)

    assert sleeps == [1.2]


def test_finnhub_429_uses_retry_after_backoff(tmp_path, monkeypatch) -> None:
    settings = Settings(
        db_path=tmp_path / "test.db",
        finnhub_api_key="test-key",
        finnhub_min_interval_seconds=0,
        finnhub_max_retries=1,
        finnhub_rate_limit_backoff_seconds=2.0,
    )
    store = Store(settings.db_path)
    sleeps: list[float] = []
    responses = [
        httpx.Response(429, headers={"Retry-After": "0.5"}, request=httpx.Request("GET", "https://finnhub.io")),
        httpx.Response(
            200,
            json=[
                {
                    "headline": "Retry succeeds",
                    "summary": "ok",
                    "url": "https://example.com/retry",
                    "datetime": 1780000000,
                }
            ],
            request=httpx.Request("GET", "https://finnhub.io"),
        ),
    ]

    monkeypatch.setattr("invest_agent.market_news.time.sleep", lambda seconds: sleeps.append(seconds))

    class FakeClient:
        def get(self, url, *, params):
            return responses.pop(0)

    items = MarketNewsIngestor(settings, store).fetch_finnhub(FakeClient(), "AAPL", days=1, limit=1)

    assert sleeps == [0.5]
    assert len(items) == 1
    assert items[0].source == "finnhub"
