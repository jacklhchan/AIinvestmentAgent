from __future__ import annotations

from .config import Settings
from .market_news import MarketNewsIngestor, external_ticker, resolve_market_context_symbols
from .models import MarketContextItem, MarketContextSnapshot, NewsIngestResult, Quote
from .store import Store


MARKET_CONTEXT_ROLES = {
    "SPY": ("US broad equity", "S&P 500 / broad risk appetite"),
    "QQQ": ("US growth / mega-cap tech", "Nasdaq 100 / AI and duration-sensitive growth"),
    "IWM": ("US small caps", "Russell 2000 / domestic cyclicals"),
    "DIA": ("US blue chips", "Dow Industrials / defensive cyclicals"),
    "VIX": ("volatility", "Volatility regime"),
    "VIXY": ("volatility proxy", "VIX futures ETF / volatility pressure"),
    "TLT": ("rates", "Long-duration US Treasuries / rates pressure"),
    "GLD": ("gold", "Gold / defensive and real-rate signal"),
    "USO": ("oil", "Oil / inflation and energy pressure"),
}


class MarketContextService:
    def __init__(self, settings: Settings, store: Store):
        self.settings = settings
        self.store = store

    def build_context(self) -> MarketContextSnapshot:
        symbols = resolve_market_context_symbols(self.settings, self.store)
        quotes = self.store.list_quotes()
        quote_by_ticker = {external_ticker(quote.symbol): quote for quote in quotes}
        items = [self._item(symbol, quote_by_ticker.get(external_ticker(symbol))) for symbol in symbols]
        with_quote = sum(1 for item in items if item.has_quote)
        with_news = sum(1 for item in items if item.news_count)
        missing = [item.symbol for item in items if not item.has_quote and not item.news_count]
        notes: list[str] = []
        if missing:
            notes.append(f"Market context missing local quote/news coverage for {', '.join(missing[:5])}.")
        if with_quote == 0:
            notes.append("Market context has no local quote coverage yet; current broad-market view is news-only.")
        if with_news == 0:
            notes.append("Refresh market context news before relying on broad-market advice.")
        if any(external_ticker(item.symbol) in {"VIX", "VIXY"} and item.news_count for item in items):
            notes.append("Volatility proxy has fresh news; review risk appetite before approving new proposals.")
        return MarketContextSnapshot(
            symbols=symbols,
            items=items,
            coverage_summary={
                "symbol_count": len(symbols),
                "with_quote": with_quote,
                "with_news": with_news,
                "missing_count": len(missing),
            },
            risk_notes=notes,
        )

    def refresh_news(
        self,
        *,
        days: int | None = None,
        max_per_symbol: int | None = None,
        include_google_news: bool | None = None,
        include_finnhub: bool = True,
    ) -> NewsIngestResult:
        symbols = resolve_market_context_symbols(self.settings, self.store)
        return MarketNewsIngestor(self.settings, self.store).refresh_news(
            symbols=symbols,
            days=days,
            max_per_symbol=max_per_symbol,
            max_symbols=len(symbols),
            include_google_news=include_google_news,
            include_finnhub=include_finnhub,
        )

    def _item(self, symbol: str, quote: Quote | None) -> MarketContextItem:
        ticker = external_ticker(symbol)
        role, label = MARKET_CONTEXT_ROLES.get(ticker, ("market context", f"{ticker} market context"))
        news_candidates = self.store.list_news(symbol=symbol, limit=20)
        if symbol != ticker:
            news_candidates.extend(self.store.list_news(symbol=ticker, limit=20))
        news_by_id = {
            item.id: item
            for item in news_candidates
            if item.symbol and external_ticker(item.symbol) == ticker
        }
        news = sorted(news_by_id.values(), key=lambda item: item.published_at, reverse=True)
        latest = news[0] if news else None
        return MarketContextItem(
            symbol=symbol,
            role=role,
            label=label,
            has_quote=quote is not None,
            last_price=quote.last_price if quote else None,
            previous_close=quote.previous_close if quote else None,
            change_pct=quote.change_pct if quote else None,
            quote_source=quote.source if quote else None,
            quote_updated_at=quote.updated_at if quote else None,
            news_count=len(news),
            latest_news_title=latest.title if latest else None,
            latest_news_source=latest.source if latest else None,
            latest_news_at=latest.published_at if latest else None,
        )
