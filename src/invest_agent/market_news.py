from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from hashlib import sha1
from typing import Any
from xml.etree import ElementTree

import httpx

from .config import Settings
from .models import NewsIngestResult, NewsItem, Quote, utc_now
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

# Some tickers are different share classes of the same economic issuer. Risk,
# thesis and proposal gates must treat these as one exposure even when the
# broker/account stores only one share class. Keep this deliberately small: it
# is a risk-control alias, not a general ticker rewrite layer.
ECONOMIC_EXPOSURE_TICKER_ALIASES = {
    "GOOG": "GOOGL",
    "GOOGL": "GOOGL",
}

MARKET_CONTEXT_QUERIES = {
    "SPY": "S&P 500 OR broad market OR US equities",
    "QQQ": "Nasdaq 100 OR mega cap tech OR growth stocks",
    "IWM": "Russell 2000 OR small caps",
    "DIA": "Dow Jones Industrial Average OR blue chip stocks",
    "VIX": "VIX OR volatility OR market fear",
    "VIXY": "VIX OR volatility OR market fear",
    "TLT": "Treasury yields OR long duration Treasuries OR bond market",
    "GLD": "gold prices OR real yields OR safe haven",
    "USO": "oil prices OR crude oil OR energy inflation",
}


def resolve_watchlist_symbols(settings: Settings, store: Store, symbols: list[str] | None = None) -> list[str]:
    candidates: list[str] = []
    if symbols:
        candidates.extend(symbols)
    else:
        configured = _split_symbols(settings.watchlist_symbols)
        held = [position.symbol for position in store.get_portfolio().positions]
        market_context_tickers = {economic_exposure_ticker(symbol) for symbol in _split_symbols(settings.market_context_symbols)}
        protected_tickers = {economic_exposure_ticker(symbol) for symbol in [*configured, *held]}
        quote_symbols = [
            quote.symbol
            for quote in store.list_quotes()
            if economic_exposure_ticker(quote.symbol) not in market_context_tickers
            or economic_exposure_ticker(quote.symbol) in protected_tickers
        ]
        candidates.extend(configured)
        candidates.extend(held)
        candidates.extend(quote_symbols)

    by_ticker: dict[str, str] = {}
    for candidate in candidates:
        symbol = _normalize_symbol(candidate)
        if not symbol:
            continue
        ticker = economic_exposure_ticker(symbol)
        current = by_ticker.get(ticker)
        if current is None or _is_market_symbol(symbol):
            by_ticker[ticker] = symbol
    return list(by_ticker.values())


def resolve_market_context_symbols(settings: Settings, store: Store | None = None) -> list[str]:
    symbols = _split_symbols(settings.market_context_symbols)
    if not store:
        return symbols
    quotes_by_ticker = {external_ticker(quote.symbol): quote.symbol for quote in store.list_quotes()}
    resolved: list[str] = []
    for symbol in symbols:
        resolved.append(quotes_by_ticker.get(external_ticker(symbol), symbol))
    return resolved


class MarketNewsIngestor:
    def __init__(self, settings: Settings, store: Store, client: httpx.Client | None = None):
        self.settings = settings
        self.store = store
        self.client = client
        self._last_finnhub_request_at: float | None = None

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
        watchlist = _resolve_explicit_symbols(symbols) if symbols is not None else resolve_watchlist_symbols(self.settings, self.store)
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
                gdelt_items: list[NewsItem] = []
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
        concept_query = MARKET_CONTEXT_QUERIES.get(ticker)
        query = f"({concept_query})" if concept_query else f'"{company}" ({ticker} OR stock OR shares OR earnings)'
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
        query = MARKET_CONTEXT_QUERIES.get(ticker) or f"{ticker} stock OR {company}"
        response = client.get(
            "https://news.google.com/rss/search",
            params={
                "q": query,
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
        response = self._get_finnhub_with_backoff(
            client,
            "https://finnhub.io/api/v1/company-news",
            params={
                "symbol": ticker,
                "from": start.isoformat(),
                "to": today.isoformat(),
                "token": self.settings.finnhub_api_key,
            },
        )
        payload = response.json()
        return news_items_from_finnhub(symbol, payload, limit=limit)

    def refresh_finnhub_quotes(self, symbols: list[str]) -> dict[str, Any]:
        watchlist = _resolve_explicit_symbols(symbols)
        if not watchlist:
            return {"symbols": [], "stored_count": 0, "errors": []}
        if not self.settings.finnhub_api_key:
            return {"symbols": watchlist, "stored_count": 0, "errors": ["finnhub api key is not configured"]}

        errors: list[str] = []
        stored_count = 0
        owns_client = self.client is None
        client = self.client or httpx.Client(
            timeout=httpx.Timeout(
                self.settings.news_timeout_seconds,
                connect=min(3.0, self.settings.news_timeout_seconds),
            )
        )
        try:
            for symbol in watchlist:
                ticker = external_ticker(symbol)
                try:
                    response = self._get_finnhub_with_backoff(
                        client,
                        "https://finnhub.io/api/v1/quote",
                        params={"symbol": ticker, "token": self.settings.finnhub_api_key},
                    )
                    quote = quote_from_finnhub(symbol, response.json())
                    if quote:
                        self.store.upsert_quote(quote)
                        stored_count += 1
                    else:
                        errors.append(f"finnhub-quote {symbol}: empty quote payload")
                except (httpx.HTTPError, ValueError) as exc:
                    errors.append(f"finnhub-quote {symbol}: {exc}")
        finally:
            if owns_client:
                client.close()

        self.store.audit(
            "finnhub_quotes_refreshed",
            "quotes",
            "finnhub",
            {"symbols": watchlist, "stored_count": stored_count, "errors": errors},
        )
        return {"symbols": watchlist, "stored_count": stored_count, "errors": errors}

    def _get_finnhub_with_backoff(self, client: httpx.Client, url: str, *, params: dict[str, Any]) -> httpx.Response:
        attempts = max(0, self.settings.finnhub_max_retries) + 1
        last_error: httpx.HTTPStatusError | None = None
        for attempt in range(attempts):
            self._wait_for_finnhub_slot()
            response = client.get(url, params=params)
            try:
                response.raise_for_status()
                return response
            except httpx.HTTPStatusError as exc:
                last_error = exc
                if exc.response.status_code != 429 or attempt >= attempts - 1:
                    raise
                time.sleep(self._finnhub_retry_delay(exc.response, attempt))
        if last_error:
            raise last_error
        raise ValueError("finnhub request did not return a response")

    def _wait_for_finnhub_slot(self) -> None:
        interval = max(0.0, self.settings.finnhub_min_interval_seconds)
        if interval <= 0:
            self._last_finnhub_request_at = time.monotonic()
            return
        now = time.monotonic()
        if self._last_finnhub_request_at is not None:
            remaining = interval - (now - self._last_finnhub_request_at)
            if remaining > 0:
                time.sleep(remaining)
                now = time.monotonic()
        self._last_finnhub_request_at = now

    def _finnhub_retry_delay(self, response: httpx.Response, attempt: int) -> float:
        retry_after = response.headers.get("Retry-After")
        if retry_after:
            retry_after = retry_after.strip()
            try:
                return max(0.0, float(retry_after))
            except ValueError:
                try:
                    parsed = parsedate_to_datetime(retry_after)
                    return max(0.0, (parsed - datetime.now(timezone.utc)).total_seconds())
                except (TypeError, ValueError):
                    pass
        base = max(0.0, self.settings.finnhub_rate_limit_backoff_seconds)
        return base * (2**attempt)


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


def quote_from_finnhub(symbol: str, payload: Any) -> Quote | None:
    if not isinstance(payload, dict):
        return None
    last_price = _float_or_none(payload.get("c"))
    previous_close = _float_or_none(payload.get("pc"))
    if last_price is None or last_price <= 0:
        return None
    return Quote(
        symbol=_normalize_symbol(symbol),
        last_price=last_price,
        previous_close=previous_close,
        change_pct=_float_or_none(payload.get("dp")),
        updated_at=_parse_epoch(payload.get("t")),
        source="finnhub",
    )


def external_ticker(symbol: str) -> str:
    normalized = _normalize_symbol(symbol)
    return normalized.split(".", 1)[1] if "." in normalized else normalized


def economic_exposure_ticker(symbol: str) -> str:
    ticker = external_ticker(symbol)
    return ECONOMIC_EXPOSURE_TICKER_ALIASES.get(ticker, ticker)


def symbols_economically_equivalent(left: str, right: str) -> bool:
    return economic_exposure_ticker(left) == economic_exposure_ticker(right)


def _split_symbols(raw: str) -> list[str]:
    return [_normalize_symbol(item) for item in raw.replace(";", ",").split(",") if _normalize_symbol(item)]


def _resolve_explicit_symbols(symbols: list[str]) -> list[str]:
    by_ticker: dict[str, str] = {}
    for candidate in symbols:
        symbol = _normalize_symbol(candidate)
        if not symbol:
            continue
        ticker = economic_exposure_ticker(symbol)
        current = by_ticker.get(ticker)
        if current is None or _is_market_symbol(symbol):
            by_ticker[ticker] = symbol
    return list(by_ticker.values())


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


def _float_or_none(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


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
