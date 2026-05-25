from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha1
from typing import Any

import httpx

from .config import Settings
from .market_news import external_ticker, resolve_watchlist_symbols
from .models import NewsIngestResult, NewsItem, utc_now
from .store import Store


class SecEdgarIngestor:
    def __init__(self, settings: Settings, store: Store, client: httpx.Client | None = None):
        self.settings = settings
        self.store = store
        self.client = client

    def refresh_filings(
        self,
        symbols: list[str] | None = None,
        *,
        forms: list[str] | None = None,
        max_filings: int | None = None,
        max_symbols: int | None = None,
    ) -> NewsIngestResult:
        watchlist = resolve_watchlist_symbols(self.settings, self.store, symbols)
        watchlist = watchlist[: max_symbols or self.settings.news_max_symbols]
        form_filter = {form.upper() for form in (forms or _split_csv(self.settings.sec_forms))}
        filing_limit = max_filings or self.settings.sec_max_filings_per_symbol
        items: list[NewsItem] = []
        errors: list[str] = []

        owns_client = self.client is None
        client = self.client or httpx.Client(
            timeout=httpx.Timeout(
                self.settings.sec_timeout_seconds,
                connect=min(3.0, self.settings.sec_timeout_seconds),
            ),
            headers={
                "User-Agent": self.settings.sec_user_agent,
                "Accept-Encoding": "gzip, deflate",
            },
        )
        try:
            ticker_map = self.fetch_ticker_map(client)
            for symbol in watchlist:
                ticker = external_ticker(symbol)
                cik = ticker_map.get(ticker)
                if not cik:
                    errors.append(f"sec {symbol}: no CIK found")
                    continue
                try:
                    submission = self.fetch_submission(client, cik)
                    items.extend(sec_filings_from_submission(symbol, cik, submission, form_filter, limit=filing_limit))
                except (httpx.HTTPError, ValueError, KeyError) as exc:
                    errors.append(f"sec {symbol}: {exc}")
        finally:
            if owns_client:
                client.close()

        stored: dict[str, NewsItem] = {}
        for item in items:
            if item.id in stored:
                continue
            self.store.upsert_news(item)
            stored[item.id] = item

        self.store.audit(
            "sec_filings_refreshed",
            "news",
            "sec-edgar",
            {
                "symbols": watchlist,
                "forms": sorted(form_filter),
                "stored_count": len(stored),
                "total_count": len(items),
                "errors": errors,
            },
        )

        return NewsIngestResult(
            symbols=watchlist,
            total_count=len(items),
            stored_count=len(stored),
            sources={"sec-edgar": len(stored)} if stored else {},
            errors=errors,
            items=list(stored.values()),
        )

    def fetch_ticker_map(self, client: httpx.Client) -> dict[str, str]:
        response = client.get("https://www.sec.gov/files/company_tickers_exchange.json")
        response.raise_for_status()
        return parse_company_tickers(response.json())

    def fetch_submission(self, client: httpx.Client, cik: str) -> dict[str, Any]:
        response = client.get(f"https://data.sec.gov/submissions/CIK{cik}.json")
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise ValueError("unexpected submissions payload")
        return payload


def parse_company_tickers(payload: dict[str, Any]) -> dict[str, str]:
    fields = payload.get("fields", [])
    data = payload.get("data", [])
    if not isinstance(fields, list) or not isinstance(data, list):
        return {}
    lower_fields = [str(field).lower() for field in fields]
    try:
        cik_idx = lower_fields.index("cik")
        ticker_idx = lower_fields.index("ticker")
    except ValueError:
        return {}

    output: dict[str, str] = {}
    for row in data:
        if not isinstance(row, list) or len(row) <= max(cik_idx, ticker_idx):
            continue
        ticker = str(row[ticker_idx] or "").strip().upper()
        cik_raw = str(row[cik_idx] or "").strip()
        if ticker and cik_raw:
            output[ticker] = cik_raw.zfill(10)
    return output


def sec_filings_from_submission(
    symbol: str,
    cik: str,
    payload: dict[str, Any],
    forms: set[str],
    *,
    limit: int,
) -> list[NewsItem]:
    recent = payload.get("filings", {}).get("recent", {})
    if not isinstance(recent, dict):
        return []

    forms_col = _column(recent, "form")
    accession_col = _column(recent, "accessionNumber")
    filing_date_col = _column(recent, "filingDate")
    report_date_col = _column(recent, "reportDate")
    accepted_col = _column(recent, "acceptanceDateTime")
    primary_doc_col = _column(recent, "primaryDocument")
    description_col = _column(recent, "primaryDocDescription")

    items: list[NewsItem] = []
    for idx, form in enumerate(forms_col):
        form_name = str(form or "").upper()
        if forms and form_name not in forms:
            continue
        accession = _at(accession_col, idx)
        filing_date = _at(filing_date_col, idx)
        primary_doc = _at(primary_doc_col, idx)
        if not accession or not filing_date:
            continue
        report_date = _at(report_date_col, idx)
        description = _at(description_col, idx)
        accepted = _at(accepted_col, idx)
        url = _filing_url(cik, accession, primary_doc)
        published_at = _parse_sec_datetime(accepted) or _parse_sec_date(filing_date)
        title = f"SEC {form_name} filed for {symbol}"
        if report_date:
            title += f" covering {report_date}"
        summary = f"Primary-source SEC EDGAR filing. Accession {accession}."
        if description:
            summary += f" {description}."
        items.append(
            NewsItem(
                id=_stable_sec_id(symbol, accession, form_name),
                symbol=symbol.strip().upper(),
                title=title,
                source="sec-edgar",
                url=url,
                published_at=published_at,
                tags=["primary-source", "sec-edgar", "filing", form_name.lower()],
                summary=summary,
            )
        )
        if len(items) >= limit:
            break
    return items


def _column(recent: dict[str, Any], name: str) -> list[Any]:
    value = recent.get(name, [])
    return value if isinstance(value, list) else []


def _at(values: list[Any], idx: int) -> str:
    if idx >= len(values):
        return ""
    return str(values[idx] or "").strip()


def _filing_url(cik: str, accession: str, primary_doc: str) -> str | None:
    if not primary_doc:
        return None
    accession_path = accession.replace("-", "")
    cik_path = str(int(cik))
    return f"https://www.sec.gov/Archives/edgar/data/{cik_path}/{accession_path}/{primary_doc}"


def _parse_sec_date(value: str) -> datetime:
    try:
        return datetime.strptime(value, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except ValueError:
        return utc_now()


def _parse_sec_datetime(value: str) -> datetime | None:
    if not value:
        return None
    try:
        normalized = value.replace("Z", "+00:00")
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _stable_sec_id(symbol: str, accession: str, form: str) -> str:
    digest = sha1(f"sec:{symbol.upper()}:{accession}:{form}".encode("utf-8")).hexdigest()[:16]
    return f"news_sec-edgar_{digest}"


def _split_csv(raw: str) -> list[str]:
    return [item.strip().upper() for item in raw.replace(";", ",").split(",") if item.strip()]
