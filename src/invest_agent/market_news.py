from __future__ import annotations

from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from hashlib import sha1
from typing import Any
from xml.etree import ElementTree

import httpx

from .config import Settings
from .models import NewsIngestResult, NewsItem, utc_now
from .store import Store


COMPANY_NAMES = {
    "AAPL": "Apple",
    "MSFT": "Microsoft",
    "NVDA": "Nvidia",
    "GOOGL": "Alphabet",
    "GOOG": "Alphabet",
    "TSLA": "Tesla",
    "AMZN": "Amazon",
    "META": "Meta Platforms",
    "AMD": "AMD",
    "NFLX": "Netflix",
}


def resolve_watchlist_symbols(settings: Settings, store: Store, symbols: list[str] | None = None) -> list[str]:
    candidates: list[str] = []
    if symbols:
        candidates.extend(symbols)
    else:
        candidates.extend(_split_symbols(settings.watchlist_symbols))
        candidates.extend(position.symbol for position in store.get_portfolio().positions)
        candidates.extend(quote.symbol for quote in store.list_quotes())

    by_ticker: dict[str, str] = {}
    for candidate in candidates:
        symbol = _normalize_symbol(candidate)
        if not symbol:
            continue
        ticker = external_ticker(symbol)
        current = by_ticker.get(ticker)
        if current is None or _is_market_symbol(symbol):
            by_ticker[ticker] = symbol
    return list(by_ticker.values())


class MarketNewsIngestor:
    def __init__(self, settings: Settings, store: Store, client: httpx.Client | None = None):
        self.settings = settings
        self.store = store
        self.client = client

    def refresh_news(
        self,
        symbols: list[str] | None = None,
        *,
        days: int | None = None,
        max_per_symbol: int | None = None,
        max_symbols: int | None = None,
        include_gdelt: bool = True,
        include_google_news: bool | None = None,
        include_finnhub: bool = True,
    ) -> NewsIngestResult:
        watchlist = resolve_watchlist_symbols(self.settings, self.store, symbols)
        watchlist = watchlist[: max_symbols or self.settings.news_max_symbols]
        lookback_days = days or self.settings.news_lookback_days
        limit = max_per_symbol or self.settings.news_max_per_symbol
        use_google_news = self.settings.google_news_fallback_enabled if include_google_news is None else include_google_news
        errors: list[str] = []
        items: list[NewsItem] = []

        owns_client = self.client is None
        timeout = httpx.Timeout(
            self.settings.news_timeout_seconds,
            connect=min(3.0, self.settings.news_timeout_seconds),
        )
        client = self.client or httpx.Client(timeout=timeout)
        try:
            for symbol in watchlist:
                if include_gdelt:
                    try:
                        gdelt_items = self.fetch_gdelt(client, symbol, days=lookback_days, limit=limit)
                        items.extend(gdelt_items)
                    except (httpx.HTTPError, ValueError) as exc:
                        errors.append(f"gdelt {symbol}: {exc}")
                        gdelt_items = []
                    if use_google_news and not gdelt_items:
                        try:
                            items.extend(self.fetch_google_news(client, symbol, limit=limit))
                        except (httpx.HTTPError, ValueError, ElementTree.ParseError) as exc:
                            errors.append(f"google-news {symbol}: {exc}")
                if include_finnhub and self.settings.finnhub_api_key:
                    try:
                        items.extend(self.fetch_finnhub(client, symbol, days=lookback_days, limit=limit))
                    except (httpx.HTTPError, ValueError) as exc:
                        errors.append(f"finnhub {symbol}: {exc}")
        finally:
            if owns_client:
                client.close()

        stored: dict[str, NewsItem] = {}
        sources: dict[str, int] = {}
        for item in items:
            if item.id in stored:
                continue
            self.store.upsert_news(item)
            stored[item.id] = item
            sources[item.source] = sources.get(item.source, 0) + 1

        self.store.audit(
            "market_news_refreshed",
            "news",
            "watchlist",
            {
                "symbols": watchlist,
                "stored_count": len(stored),
                "total_count": len(items),
                "sources": sources,
                "errors": errors,
            },
        )

        return NewsIngestResult(
            symbols=watchlist,
            total_count=len(items),
            stored_count=len(stored),
            sources=sources,
            errors=errors,
            items=list(stored.values()),
        )

    def fetch_gdelt(self, client: httpx.Client, symbol: str, *, days: int, limit: int) -> list[NewsItem]:
        ticker = external_ticker(symbol)
        company = COMPANY_NAMES.get(ticker, ticker)
        query = f'"{company}" ({ticker} OR stock OR shares OR earnings)'
        response = client.get(
            "https://api.gdeltproject.org/api/v2/doc/doc",
            params={
                "query": query,
                "mode": "ArtList",
                "format": "json",
                "sort": "DateDesc",
                "timespan": f"{max(days, 1)}d",
                "maxrecords": max(limit, 1),
            },
        )
        response.raise_for_status()
        payload = response.json()
        return news_items_from_gdelt(symbol, payload, limit=limit)

    def fetch_google_news(self, client: httpx.Client, symbol: str, *, limit: int) -> list[NewsItem]:
        ticker = external_ticker(symbol)
        company = COMPANY_NAMES.get(ticker, ticker)
        response = client.get(
            "https://news.google.com/rss/search",
            params={
                "q": f"{ticker} stock OR {company}",
                "hl": "en-US",
                "gl": "US",
                "ceid": "US:en",
            },
        )
        response.raise_for_status()
        return news_items_from_google_news(symbol, response.text, limit=limit)

    def fetch_finnhub(self, client: httpx.Client, symbol: str, *, days: int, limit: int) -> list[NewsItem]:
        ticker = external_ticker(symbol)
        today = utc_now().date()
        start = today - timedelta(days=max(days, 1))
        response = client.get(
            "https://finnhub.io/api/v1/company-news",
            params={
                "symbol": ticker,
                "from": start.isoformat(),
                "to": today.isoformat(),
                "token": self.settings.finnhub_api_key,
            },
        )
        response.raise_for_status()
        payload = response.json()
        return news_items_from_finnhub(symbol, payload, limit=limit)


def news_items_from_gdelt(symbol: str, payload: dict[str, Any], *, limit: int) -> list[NewsItem]:
    articles = payload.get("articles") if isinstance(payload, dict) else []
    if not isinstance(articles, list):
        return []

    items: list[NewsItem] = []
    for row in articles[:limit]:
        if not isinstance(row, dict):
            continue
        title = str(row.get("title") or "").strip()
        url = str(row.get("url") or "").strip()
        if not title or not url:
            continue
        domain = str(row.get("domain") or "").strip()
        items.append(
            NewsItem(
                id=_stable_news_id("gdelt", symbol, url or title),
                symbol=_normalize_symbol(symbol),
                title=title,
                source="gdelt",
                url=url,
                published_at=_parse_gdelt_date(str(row.get("seendate") or "")),
                tags=["market-news", "gdelt"],
                summary=f"Discovered by GDELT{f' from {domain}' if domain else ''}.",
            )
        )
    return items


def news_items_from_finnhub(symbol: str, payload: Any, *, limit: int) -> list[NewsItem]:
    rows = payload if isinstance(payload, list) else []
    items: list[NewsItem] = []
    for row in rows[:limit]:
        if not isinstance(row, dict):
            continue
        title = str(row.get("headline") or "").strip()
        url = str(row.get("url") or "").strip()
        if not title:
            continue
        items.append(
            NewsItem(
                id=_stable_news_id("finnhub", symbol, url or title),
                symbol=_normalize_symbol(symbol),
                title=title,
                source="finnhub",
                url=url or None,
                published_at=_parse_epoch(row.get("datetime")),
                tags=["market-news", "finnhub"],
                summary=str(row.get("summary") or "").strip(),
            )
        )
    return items


def news_items_from_google_news(symbol: str, xml_text: str, *, limit: int) -> list[NewsItem]:
    root = ElementTree.fromstring(xml_text)
    items: list[NewsItem] = []
    for node in root.findall("./channel/item")[:limit]:
        title = _xml_text(node, "title")
        link = _xml_text(node, "link")
        if not title:
            continue
        source = _xml_text(node, "source")
        published = _parse_rss_date(_xml_text(node, "pubDate"))
        summary = f"Google News RSS{f' via {source}' if source else ''}."
        items.append(
            NewsItem(
                id=_stable_news_id("google-news", symbol, link or title),
                symbol=_normalize_symbol(symbol),
                title=title,
                source="google-news",
                url=link or None,
                published_at=published,
                tags=["market-news", "google-news"],
                summary=summary,
            )
        )
    return items


def external_ticker(symbol: str) -> str:
    normalized = _normalize_symbol(symbol)
    return normalized.split(".", 1)[1] if "." in normalized else normalized


def _split_symbols(raw: str) -> list[str]:
    return [_normalize_symbol(item) for item in raw.replace(";", ",").split(",") if _normalize_symbol(item)]


def _normalize_symbol(symbol: str) -> str:
    return symbol.strip().upper()


def _is_market_symbol(symbol: str) -> bool:
    return "." in symbol


def _stable_news_id(source: str, symbol: str, value: str) -> str:
    digest = sha1(f"{source}:{_normalize_symbol(symbol)}:{value}".encode("utf-8")).hexdigest()[:16]
    return f"news_{source}_{digest}"


def _parse_gdelt_date(value: str) -> datetime:
    if not value:
        return utc_now()
    for fmt in ("%Y%m%dT%H%M%SZ", "%Y%m%d%H%M%S"):
        try:
            return datetime.strptime(value, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return utc_now()


def _parse_epoch(value: Any) -> datetime:
    try:
        return datetime.fromtimestamp(int(value), tz=timezone.utc)
    except (TypeError, ValueError, OSError):
        return utc_now()


def _parse_rss_date(value: str) -> datetime:
    if not value:
        return utc_now()
    try:
        parsed = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return utc_now()
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _xml_text(node: ElementTree.Element, tag: str) -> str:
    child = node.find(tag)
    return (child.text or "").strip() if child is not None else ""
