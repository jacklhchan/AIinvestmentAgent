from __future__ import annotations

from invest_agent.ir_feeds import ir_items_from_feed, parse_ir_feed_config
from invest_agent.sec_edgar import parse_company_tickers, sec_filings_from_submission


def test_parse_sec_ticker_map() -> None:
    mapping = parse_company_tickers(
        {
            "fields": ["cik", "name", "ticker", "exchange"],
            "data": [[320193, "Apple Inc.", "AAPL", "Nasdaq"]],
        }
    )

    assert mapping == {"AAPL": "0000320193"}


def test_sec_submission_maps_to_primary_source_news() -> None:
    items = sec_filings_from_submission(
        "AAPL",
        "0000320193",
        {
            "filings": {
                "recent": {
                    "form": ["10-Q", "4"],
                    "accessionNumber": ["0000320193-26-000010", "0000320193-26-000011"],
                    "filingDate": ["2026-05-20", "2026-05-21"],
                    "reportDate": ["2026-03-31", ""],
                    "acceptanceDateTime": ["2026-05-20T18:00:00.000Z", "2026-05-21T18:00:00.000Z"],
                    "primaryDocument": ["aapl-20260331.htm", "xslF345X05/wk-form4.xml"],
                    "primaryDocDescription": ["Quarterly report", "Ownership form"],
                }
            }
        },
        {"10-Q"},
        limit=5,
    )

    assert len(items) == 1
    assert items[0].source == "sec-edgar"
    assert "primary-source" in items[0].tags
    assert "10-Q" in items[0].title
    assert "Archives/edgar/data/320193" in (items[0].url or "")


def test_ir_rss_feed_maps_to_primary_source_news() -> None:
    items = ir_items_from_feed(
        "MSFT",
        """
        <rss><channel><item>
          <title>Microsoft announces quarterly results</title>
          <link>https://example.com/ir/msft-results</link>
          <pubDate>Mon, 25 May 2026 10:00:00 GMT</pubDate>
        </item></channel></rss>
        """,
        source_url="https://example.com/rss",
        limit=5,
    )

    assert items[0].source == "company-ir"
    assert items[0].symbol == "MSFT"
    assert "primary-source" in items[0].tags


def test_parse_ir_feed_config() -> None:
    assert parse_ir_feed_config("AAPL=https://example.com/aapl.xml;MSFT=https://example.com/msft.xml") == {
        "AAPL": "https://example.com/aapl.xml",
        "MSFT": "https://example.com/msft.xml",
    }
