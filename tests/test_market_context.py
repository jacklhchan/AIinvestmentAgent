from __future__ import annotations

from pathlib import Path

from invest_agent.config import Settings
from invest_agent.market_context import MarketContextService
from invest_agent.market_news import resolve_market_context_symbols
from invest_agent.models import NewsIngestResult, NewsItem, Quote
from invest_agent.store import Store


def make_store(tmp_path: Path) -> Store:
    settings = Settings(db_path=tmp_path / "test.db")
    return Store(settings.db_path)


def test_market_context_prefers_market_prefixed_quote_symbol(tmp_path) -> None:
    settings = Settings(db_path=tmp_path / "test.db", market_context_symbols="SPY,QQQ")
    store = make_store(tmp_path)
    store.upsert_quote(Quote(symbol="US.SPY", last_price=500.0, source="futu-opend"))

    assert resolve_market_context_symbols(settings, store) == ["US.SPY", "QQQ"]


def test_market_context_snapshot_tracks_quote_and_news_coverage(tmp_path) -> None:
    settings = Settings(db_path=tmp_path / "test.db", market_context_symbols="SPY,VIXY")
    store = make_store(tmp_path)
    store.upsert_quote(Quote(symbol="SPY", last_price=500.0, source="demo"))
    store.upsert_news(
        NewsItem(
            symbol="VIXY",
            title="Volatility proxy rises as broad market sells off",
            source="google-news",
            tags=["market-news"],
        )
    )

    snapshot = MarketContextService(settings, store).build_context()

    assert snapshot.coverage_summary["symbol_count"] == 2
    assert snapshot.coverage_summary["with_quote"] == 1
    assert snapshot.coverage_summary["with_news"] == 1
    assert any("Volatility proxy" in note for note in snapshot.risk_notes)


def test_market_context_snapshot_flags_low_broad_coverage(tmp_path) -> None:
    settings = Settings(db_path=tmp_path / "test.db", market_context_symbols="SPY,QQQ,XLK,XLV")
    store = make_store(tmp_path)
    store.upsert_quote(Quote(symbol="SPY", last_price=500.0, source="demo"))
    store.upsert_news(NewsItem(symbol="SPY", title="Broad market news", source="google-news"))

    snapshot = MarketContextService(settings, store).build_context()

    assert snapshot.coverage_summary["coverage_sufficient"] is False
    assert snapshot.coverage_summary["news_coverage_ratio"] == 0.25
    assert any("news coverage is low" in note for note in snapshot.risk_notes)
    assert any("quote coverage is low" in note for note in snapshot.risk_notes)


def test_market_context_refresh_uses_full_context_universe(tmp_path, monkeypatch) -> None:
    settings = Settings(db_path=tmp_path / "test.db", market_context_symbols="SPY,QQQ,XLK")
    store = make_store(tmp_path)
    captured: dict[str, object] = {}

    def fake_refresh(self, symbols=None, **kwargs):
        captured["symbols"] = symbols
        captured["max_symbols"] = kwargs.get("max_symbols")
        captured["max_per_symbol"] = kwargs.get("max_per_symbol")
        captured["include_gdelt"] = kwargs.get("include_gdelt")
        return NewsIngestResult(symbols=symbols or [])

    monkeypatch.setattr("invest_agent.market_context.MarketNewsIngestor.refresh_news", fake_refresh)

    result = MarketContextService(settings, store).refresh_news(max_per_symbol=7)

    assert result.symbols == ["SPY", "QQQ", "XLK"]
    assert captured["symbols"] == ["SPY", "QQQ", "XLK"]
    assert captured["max_symbols"] == 3
    assert captured["max_per_symbol"] == 7
    assert captured["include_gdelt"] is True


def test_mcp_exposes_market_context_tools() -> None:
    import invest_agent.mcp_server as mcp_server

    assert hasattr(mcp_server, "get_market_context")
    assert hasattr(mcp_server, "refresh_market_context_news")
