from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import httpx

from .config import Settings
from .market_news import external_ticker, resolve_watchlist_symbols
from .models import FundamentalMetric, FundamentalSnapshot, FundamentalsRefreshResult, utc_now
from .sec_edgar import parse_company_tickers
from .store import Store


METRIC_CONCEPTS: dict[str, tuple[str, list[str]]] = {
    "revenue": (
        "Revenue",
        [
            "RevenueFromContractWithCustomerExcludingAssessedTax",
            "Revenues",
            "SalesRevenueNet",
        ],
    ),
    "net_income": ("Net income", ["NetIncomeLoss"]),
    "operating_income": ("Operating income", ["OperatingIncomeLoss"]),
    "operating_cash_flow": ("Operating cash flow", ["NetCashProvidedByUsedInOperatingActivities"]),
    "assets": ("Assets", ["Assets"]),
    "liabilities": ("Liabilities", ["Liabilities"]),
    "equity": ("Equity", ["StockholdersEquity", "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest"]),
    "eps_diluted": ("Diluted EPS", ["EarningsPerShareDiluted"]),
}

DEFAULT_COMPANYFACTS_FORMS = {"10-K", "10-Q", "20-F", "40-F", "6-K"}


class SecCompanyFactsIngestor:
    def __init__(self, settings: Settings, store: Store, client: httpx.Client | None = None):
        self.settings = settings
        self.store = store
        self.client = client

    def refresh_fundamentals(
        self,
        symbols: list[str] | None = None,
        *,
        max_symbols: int | None = None,
        forms: list[str] | None = None,
    ) -> FundamentalsRefreshResult:
        watchlist = resolve_watchlist_symbols(self.settings, self.store, symbols)
        watchlist = watchlist[: max_symbols or self.settings.news_max_symbols]
        form_filter = {form.upper() for form in (forms or DEFAULT_COMPANYFACTS_FORMS)}
        snapshots: list[FundamentalSnapshot] = []
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
                    errors.append(f"companyfacts {symbol}: no CIK found")
                    continue
                try:
                    payload = self.fetch_companyfacts(client, cik)
                    snapshot = companyfacts_snapshot_from_payload(symbol, cik, payload, form_filter=form_filter)
                    self.store.upsert_fundamentals(snapshot)
                    snapshots.append(snapshot)
                except (httpx.HTTPError, ValueError, KeyError) as exc:
                    errors.append(f"companyfacts {symbol}: {exc}")
        finally:
            if owns_client:
                client.close()

        self.store.audit(
            "sec_companyfacts_refreshed",
            "fundamentals",
            "sec-companyfacts",
            {
                "symbols": watchlist,
                "forms": sorted(form_filter),
                "stored_count": len(snapshots),
                "errors": errors,
            },
        )

        return FundamentalsRefreshResult(
            symbols=watchlist,
            total_count=len(snapshots),
            stored_count=len(snapshots),
            errors=errors,
            snapshots=snapshots,
        )

    def fetch_ticker_map(self, client: httpx.Client) -> dict[str, str]:
        response = client.get("https://www.sec.gov/files/company_tickers_exchange.json")
        response.raise_for_status()
        return parse_company_tickers(response.json())

    def fetch_companyfacts(self, client: httpx.Client, cik: str) -> dict[str, Any]:
        response = client.get(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json")
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise ValueError("unexpected companyfacts payload")
        return payload


def companyfacts_snapshot_from_payload(
    symbol: str,
    cik: str,
    payload: dict[str, Any],
    *,
    form_filter: set[str] | None = None,
) -> FundamentalSnapshot:
    us_gaap = payload.get("facts", {}).get("us-gaap", {})
    if not isinstance(us_gaap, dict):
        raise ValueError("companyfacts payload has no us-gaap facts")

    metrics: dict[str, FundamentalMetric] = {}
    for metric_name, (label, concepts) in METRIC_CONCEPTS.items():
        metric = _metric_from_concepts(metric_name, label, concepts, us_gaap, form_filter or DEFAULT_COMPANYFACTS_FORMS)
        if metric:
            metrics[metric_name] = metric

    if not metrics:
        raise ValueError("no supported us-gaap metrics found")

    return FundamentalSnapshot(
        symbol=symbol,
        cik=str(payload.get("cik") or cik).zfill(10),
        entity_name=str(payload.get("entityName") or ""),
        metrics=metrics,
        updated_at=utc_now(),
    )


def _metric_from_concepts(
    metric_name: str,
    label: str,
    concept_names: list[str],
    us_gaap: dict[str, Any],
    form_filter: set[str],
) -> FundamentalMetric | None:
    combined_facts: list[dict[str, Any]] = []
    for concept in concept_names:
        concept_payload = us_gaap.get(concept)
        if not isinstance(concept_payload, dict):
            continue
        facts = _unit_facts(concept_payload)
        if not facts:
            continue
        for fact in facts:
            fact["_concept"] = concept
        combined_facts.extend(facts)

    if not combined_facts:
        return None

    filtered = [fact for fact in combined_facts if _form(fact) in form_filter] or combined_facts
    latest = _latest_fact(filtered)
    if latest is None:
        return None
    previous = _previous_comparable_fact(latest, filtered)
    return FundamentalMetric(
        name=metric_name,
        label=label,
        concept=str(latest.get("_concept") or ""),
        value=_number(latest.get("val")),
        unit=str(latest.get("unit") or ""),
        fiscal_year=_int_or_none(latest.get("fy")),
        fiscal_period=str(latest.get("fp") or ""),
        end_date=str(latest.get("end") or ""),
        form=str(latest.get("form") or ""),
        filed_at=_parse_sec_date(str(latest.get("filed") or "")),
        frame=str(latest.get("frame") or "") or None,
        yoy_change_pct=_yoy_change_pct(latest, previous),
    )


def _unit_facts(concept_payload: dict[str, Any]) -> list[dict[str, Any]]:
    units = concept_payload.get("units", {})
    if not isinstance(units, dict):
        return []

    facts: list[dict[str, Any]] = []
    for unit, rows in units.items():
        if not isinstance(rows, list):
            continue
        for row in rows:
            if not isinstance(row, dict) or _number(row.get("val")) is None:
                continue
            fact = dict(row)
            fact["unit"] = str(unit)
            facts.append(fact)
    return facts


def _latest_fact(facts: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not facts:
        return None
    return max(facts, key=lambda fact: (_date_sort(str(fact.get("filed") or "")), _date_sort(str(fact.get("end") or ""))))


def _previous_comparable_fact(current: dict[str, Any], facts: list[dict[str, Any]]) -> dict[str, Any] | None:
    current_value = _number(current.get("val"))
    current_fy = _int_or_none(current.get("fy"))
    current_fp = str(current.get("fp") or "")
    current_unit = str(current.get("unit") or "")
    if current_value is None or current_fy is None or not current_fp:
        return None

    candidates = [
        fact
        for fact in facts
        if fact is not current
        and _int_or_none(fact.get("fy")) == current_fy - 1
        and str(fact.get("fp") or "") == current_fp
        and str(fact.get("unit") or "") == current_unit
        and _number(fact.get("val")) not in (None, 0.0)
    ]
    return _latest_fact(candidates)


def _yoy_change_pct(current: dict[str, Any], previous: dict[str, Any] | None) -> float | None:
    if previous is None:
        return None
    current_value = _number(current.get("val"))
    previous_value = _number(previous.get("val"))
    if current_value is None or previous_value in (None, 0.0):
        return None
    return round(((current_value - previous_value) / abs(previous_value)) * 100.0, 2)


def _number(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _int_or_none(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _form(fact: dict[str, Any]) -> str:
    return str(fact.get("form") or "").upper()


def _date_sort(value: str) -> tuple[int, int, int]:
    parsed = _parse_sec_date(value)
    if parsed is None:
        return (0, 0, 0)
    return (parsed.year, parsed.month, parsed.day)


def _parse_sec_date(value: str) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.strptime(value, "%Y-%m-%d")
    except ValueError:
        return None
    return parsed.replace(tzinfo=timezone.utc)
