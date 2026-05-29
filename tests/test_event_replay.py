from __future__ import annotations

from invest_agent.config import Settings
from invest_agent.demo_data import seed_demo_data
from invest_agent.event_replay import export_event_replay, replay_event_file
from invest_agent.models import NewsItem, PortfolioSnapshot, Quote, utc_now
from invest_agent.store import Store


def test_export_and_replay_signal_events(tmp_path) -> None:
    source_store = Store(tmp_path / "source.db")
    seed_demo_data(source_store, force=True)
    source_store.upsert_news(
        NewsItem(
            symbol="GOOGL",
            title="Alphabet raises guidance after strong cloud demand",
            source="company-ir",
            published_at=utc_now(),
            tags=["primary-source", "company-ir"],
            summary="Primary-source company investor-relations feed item.",
        )
    )

    replay_path = tmp_path / "events.jsonl"
    exported = export_event_replay(source_store, replay_path)

    target_settings = Settings(db_path=tmp_path / "target.db", watchlist_symbols="GOOGL", draft_min_score=1)
    target_store = Store(target_settings.db_path)
    result = replay_event_file(target_settings, target_store, replay_path)

    assert exported.exported_counts["news_item"] >= 1
    assert result.imported_counts["portfolio"] == 1
    assert result.imported_counts["quote"] >= 1
    assert result.imported_counts["news_item"] >= 1
    assert result.draft_result is not None
    assert result.draft_result.drafts


def test_replay_rejects_unknown_event_type(tmp_path) -> None:
    replay_path = tmp_path / "events.jsonl"
    replay_path.write_text('{"type":"unknown","payload":{}}\n', encoding="utf-8")

    settings = Settings(db_path=tmp_path / "test.db")
    store = Store(settings.db_path)
    result = replay_event_file(settings, store, replay_path, run_drafts=False)

    assert result.errors


def test_replay_accepts_minimal_portfolio_quote_news(tmp_path) -> None:
    source_store = Store(tmp_path / "source.db")
    source_store.upsert_portfolio(PortfolioSnapshot(cash_usd=1000, total_value_usd=1000))
    source_store.upsert_quote(Quote(symbol="AAPL", last_price=190.0))
    source_store.upsert_news(NewsItem(symbol="AAPL", title="Apple demand growth remains strong", source="google-news"))

    replay_path = tmp_path / "events.jsonl"
    export_event_replay(source_store, replay_path)

    target_settings = Settings(db_path=tmp_path / "target.db", watchlist_symbols="AAPL", draft_min_score=1)
    target_store = Store(target_settings.db_path)
    result = replay_event_file(target_settings, target_store, replay_path)

    assert result.imported_counts == {"portfolio": 1, "quote": 1, "news_item": 1}
    assert target_store.get_quote("AAPL") is not None
