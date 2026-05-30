from __future__ import annotations

import csv
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from io import StringIO
from typing import Any
from urllib.parse import urlencode

import httpx

from .config import Settings
from .futu_adapter import FutuIntegrationError, fetch_futu_history_kline
from .models import PriceBar, QuoteHistorySource, utc_now
from .store import Store


PROVIDER_SOURCE = {
    "futu": QuoteHistorySource.FUTU_HISTORY_KLINE,
    "alpaca": QuoteHistorySource.ALPACA_HISTORICAL_BARS,
    "stooq": QuoteHistorySource.STOOQ_HISTORICAL_CSV,
    "fmp": QuoteHistorySource.FMP_HISTORICAL_BARS,
    "twelvedata": QuoteHistorySource.TWELVEDATA_TIME_SERIES,
    "alphavantage": QuoteHistorySource.ALPHAVANTAGE_DAILY,
    "yfinance_dev": QuoteHistorySource.YFINANCE_DEV_CHART,
}


@dataclass
class ProviderBarResult:
    provider: str
    source: QuoteHistorySource
    source_feed: str
    symbol: str
    broker_symbol: str | None
    rows: list[dict[str, Any]]
    adjusted: bool
    quality_score: float
    license_note: str
    retrieved_at: datetime
    skipped_providers: list[dict[str, str]]


class MarketDataProviderError(RuntimeError):
    def __init__(self, symbol: str, errors: list[dict[str, str]]):
        self.symbol = symbol
        self.errors = errors
        message = "; ".join(f"{item['provider']}: {item['error']}" for item in errors) or "no provider attempted"
        super().__init__(f"no historical price bar provider succeeded for {symbol}: {message}")


class MarketDataRouter:
    def __init__(self, settings: Settings, store: Store):
        self.settings = settings
        self.store = store

    def provider_priority(self, source: str = "auto") -> list[str]:
        normalized = (source or "auto").strip().lower()
        if normalized != "auto":
            return [normalized]
        return [
            item.strip().lower()
            for item in self.settings.market_data_provider_priority.split(",")
            if item.strip()
        ]

    def fetch_history(
        self,
        symbol: str,
        *,
        source: str = "auto",
        days: int = 365,
        ktype: str = "K_DAY",
        autype: str = "qfq",
    ) -> ProviderBarResult:
        symbol = symbol.strip().upper()
        errors: list[dict[str, str]] = []
        for provider in self.provider_priority(source):
            if provider == "local_cache":
                if latest_completed_bar(self.store, symbol):
                    errors.append({"provider": provider, "error": "latest completed trading-day bar already present"})
                continue
            try:
                if not self._quota_available(provider, symbol):
                    errors.append({"provider": provider, "error": "quota unavailable or provider disabled"})
                    continue
                result = self._fetch_provider(provider, symbol, days=days, ktype=ktype, autype=autype)
                if not result.rows:
                    raise ValueError("provider returned no bars")
                result.skipped_providers = errors[:]
                self._record_usage(provider, result.source_feed, symbol, True, None)
                return result
            except Exception as exc:
                error = str(exc)
                errors.append({"provider": provider, "error": error})
                self._record_usage(provider, self._endpoint(provider), symbol, False, error)
        raise MarketDataProviderError(symbol, errors)

    def _fetch_provider(self, provider: str, symbol: str, *, days: int, ktype: str, autype: str) -> ProviderBarResult:
        if provider == "futu":
            broker_symbol, rows = fetch_futu_history_kline(self.settings, symbol, days=days, ktype=ktype, autype=autype)
            return _result(provider, "request_history_kline", symbol, broker_symbol, rows, adjusted=autype.lower() != "none", quality=0.95)
        if provider == "alpaca":
            return self._fetch_alpaca(symbol, days=days)
        if provider == "stooq":
            return self._fetch_stooq(symbol, days=days)
        if provider == "fmp":
            return self._fetch_fmp(symbol, days=days)
        if provider == "twelvedata":
            return self._fetch_twelvedata(symbol, days=days)
        if provider == "alphavantage":
            return self._fetch_alpha_vantage(symbol)
        if provider == "yfinance_dev":
            return self._fetch_yfinance_dev(symbol, days=days)
        raise ValueError(f"unknown market data provider: {provider}")

    def _fetch_alpaca(self, symbol: str, *, days: int) -> ProviderBarResult:
        if not (self.settings.alpaca_api_key and self.settings.alpaca_secret_key):
            raise ValueError("ALPACA_API_KEY and ALPACA_SECRET_KEY are required")
        end = utc_now()
        start = end - timedelta(days=days)
        url = f"https://data.alpaca.markets/v2/stocks/{_us_symbol(symbol)}/bars"
        params = {"timeframe": "1Day", "start": start.isoformat(), "end": end.isoformat(), "adjustment": "all", "limit": 10000}
        headers = {"APCA-API-KEY-ID": self.settings.alpaca_api_key, "APCA-API-SECRET-KEY": self.settings.alpaca_secret_key}
        data = _get_json(url, params=params, headers=headers, timeout=self.settings.market_data_timeout_seconds)
        rows = [
            _row(item.get("t"), item.get("o"), item.get("h"), item.get("l"), item.get("c"), item.get("v"), raw=item)
            for item in data.get("bars", [])
        ]
        return _result("alpaca", "v2/stocks/bars", symbol, _us_symbol(symbol), _valid_rows(rows), adjusted=True, quality=0.86)

    def _fetch_stooq(self, symbol: str, *, days: int) -> ProviderBarResult:
        end = utc_now().date()
        start = end - timedelta(days=days)
        stooq_symbol = _stooq_symbol(symbol)
        query = urlencode({"s": stooq_symbol, "i": "d", "d1": start.strftime("%Y%m%d"), "d2": end.strftime("%Y%m%d")})
        text = _get_text(f"https://stooq.com/q/d/l/?{query}", timeout=self.settings.market_data_timeout_seconds)
        reader = csv.DictReader(StringIO(text))
        rows = [
            _row(item.get("Date"), item.get("Open"), item.get("High"), item.get("Low"), item.get("Close"), item.get("Volume"), raw=item)
            for item in reader
        ]
        return _result("stooq", "historical_csv", symbol, stooq_symbol, _valid_rows(rows), adjusted=False, quality=0.72)

    def _fetch_fmp(self, symbol: str, *, days: int) -> ProviderBarResult:
        if not self.settings.fmp_api_key:
            raise ValueError("FMP_API_KEY is required")
        end = utc_now().date()
        start = end - timedelta(days=days)
        url = f"https://financialmodelingprep.com/api/v3/historical-price-full/{_us_symbol(symbol)}"
        data = _get_json(
            url,
            params={"from": start.isoformat(), "to": end.isoformat(), "apikey": self.settings.fmp_api_key},
            timeout=self.settings.market_data_timeout_seconds,
        )
        rows = [
            _row(item.get("date"), item.get("open"), item.get("high"), item.get("low"), item.get("close"), item.get("volume"), raw=item)
            for item in data.get("historical", [])
        ]
        return _result("fmp", "historical-price-full", symbol, _us_symbol(symbol), _valid_rows(rows), adjusted=False, quality=0.78)

    def _fetch_twelvedata(self, symbol: str, *, days: int) -> ProviderBarResult:
        if not self.settings.twelvedata_api_key:
            raise ValueError("TWELVEDATA_API_KEY is required")
        end = utc_now().date()
        start = end - timedelta(days=days)
        data = _get_json(
            "https://api.twelvedata.com/time_series",
            params={
                "symbol": _us_symbol(symbol),
                "interval": "1day",
                "start_date": start.isoformat(),
                "end_date": end.isoformat(),
                "apikey": self.settings.twelvedata_api_key,
                "format": "JSON",
            },
            timeout=self.settings.market_data_timeout_seconds,
        )
        if data.get("status") == "error":
            raise ValueError(data.get("message") or "Twelve Data returned error")
        rows = [
            _row(item.get("datetime"), item.get("open"), item.get("high"), item.get("low"), item.get("close"), item.get("volume"), raw=item)
            for item in data.get("values", [])
        ]
        return _result("twelvedata", "time_series", symbol, _us_symbol(symbol), _valid_rows(rows), adjusted=False, quality=0.75)

    def _fetch_alpha_vantage(self, symbol: str) -> ProviderBarResult:
        if not self.settings.alpha_vantage_api_key:
            raise ValueError("ALPHA_VANTAGE_API_KEY is required")
        data = _get_json(
            "https://www.alphavantage.co/query",
            params={
                "function": "TIME_SERIES_DAILY_ADJUSTED",
                "symbol": _us_symbol(symbol),
                "apikey": self.settings.alpha_vantage_api_key,
                "outputsize": "compact",
            },
            timeout=self.settings.market_data_timeout_seconds,
        )
        if "Note" in data or "Information" in data:
            raise ValueError(data.get("Note") or data.get("Information"))
        series = data.get("Time Series (Daily)") or {}
        rows = [
            _row(day, item.get("1. open"), item.get("2. high"), item.get("3. low"), item.get("5. adjusted close"), item.get("6. volume"), raw=item)
            for day, item in series.items()
        ]
        return _result("alphavantage", "TIME_SERIES_DAILY_ADJUSTED", symbol, _us_symbol(symbol), _valid_rows(rows), adjusted=True, quality=0.74)

    def _fetch_yfinance_dev(self, symbol: str, *, days: int) -> ProviderBarResult:
        if not self.settings.market_data_yfinance_dev_enabled:
            raise ValueError("yfinance_dev is disabled by INVEST_AGENT_YFINANCE_DEV_ENABLED")
        end = int(time.time())
        start = end - days * 24 * 3600
        yahoo_symbol = _yahoo_symbol(symbol)
        data = _get_json(
            f"https://query1.finance.yahoo.com/v8/finance/chart/{yahoo_symbol}",
            params={"period1": start, "period2": end, "interval": "1d", "events": "history", "includeAdjustedClose": "true"},
            timeout=self.settings.market_data_timeout_seconds,
        )
        result = ((data.get("chart") or {}).get("result") or [{}])[0]
        timestamps = result.get("timestamp") or []
        quote = ((result.get("indicators") or {}).get("quote") or [{}])[0]
        adjclose = ((result.get("indicators") or {}).get("adjclose") or [{}])[0].get("adjclose") or quote.get("close") or []
        rows = []
        for idx, ts in enumerate(timestamps):
            rows.append(
                _row(
                    datetime.fromtimestamp(ts, timezone.utc).date().isoformat(),
                    _at(quote.get("open"), idx),
                    _at(quote.get("high"), idx),
                    _at(quote.get("low"), idx),
                    _at(adjclose, idx),
                    _at(quote.get("volume"), idx),
                    raw={"timestamp": ts, "provider": "yfinance_dev"},
                )
            )
        return _result("yfinance_dev", "chart", symbol, yahoo_symbol, _valid_rows(rows), adjusted=True, quality=0.35)

    def _quota_available(self, provider: str, symbol: str) -> bool:
        if provider == "futu":
            if not self.settings.futu_read_enabled:
                return False
            return _usage_count(self.store, "futu", "request_history_kline", symbol, "7d") < self.settings.futu_history_symbol_7d_limit
        if provider == "alpaca":
            return bool(self.settings.alpaca_api_key and self.settings.alpaca_secret_key)
        if provider == "fmp":
            return bool(self.settings.fmp_api_key) and _usage_count(self.store, "fmp", "historical-price-full", "*", "1d") < self.settings.market_data_fmp_daily_limit
        if provider == "twelvedata":
            return bool(self.settings.twelvedata_api_key) and _usage_count(self.store, "twelvedata", "time_series", "*", "1d") < self.settings.market_data_twelvedata_daily_limit
        if provider == "alphavantage":
            return bool(self.settings.alpha_vantage_api_key) and _usage_count(self.store, "alphavantage", "TIME_SERIES_DAILY_ADJUSTED", "*", "1d") < self.settings.market_data_alpha_vantage_daily_limit
        if provider == "yfinance_dev":
            return self.settings.market_data_yfinance_dev_enabled
        if provider == "stooq":
            return True
        return False

    def _record_usage(self, provider: str, endpoint: str, symbol: str, success: bool, error: str | None) -> None:
        quota_window = "7d" if provider == "futu" else "1d" if provider in {"fmp", "twelvedata", "alphavantage"} else "none"
        ledger_symbol = symbol.upper() if provider == "futu" else "*"
        reset_at = utc_now() + (timedelta(days=7) if quota_window == "7d" else timedelta(days=1) if quota_window == "1d" else timedelta(days=3650))
        self.store.record_provider_usage(
            provider=provider,
            endpoint=endpoint,
            symbol=ledger_symbol,
            quota_window=quota_window,
            success=success,
            error=error,
            reset_at=reset_at,
        )

    def _endpoint(self, provider: str) -> str:
        return {
            "futu": "request_history_kline",
            "alpaca": "v2/stocks/bars",
            "stooq": "historical_csv",
            "fmp": "historical-price-full",
            "twelvedata": "time_series",
            "alphavantage": "TIME_SERIES_DAILY_ADJUSTED",
            "yfinance_dev": "chart",
        }.get(provider, provider)


def latest_completed_trading_day(now: datetime | None = None) -> datetime:
    current = (now or utc_now()).astimezone(timezone.utc).date()
    while current.weekday() >= 5:
        current -= timedelta(days=1)
    return datetime.combine(current, datetime.min.time(), tzinfo=timezone.utc)


def latest_completed_bar(store: Store, symbol: str) -> PriceBar | None:
    latest = latest_completed_trading_day()
    for bar in store.list_price_bars(symbol=symbol, limit=5, ascending=False):
        if bar.ts.astimezone(timezone.utc).date() >= latest.date():
            return bar
    return None


def provider_coverage(store: Store, *, symbols: list[str] | None = None) -> dict[str, Any]:
    bars = store.list_price_bars(limit=100000)
    if symbols:
        wanted = {symbol.upper() for symbol in symbols}
        bars = [bar for bar in bars if bar.symbol.upper() in wanted]
    by_provider: dict[str, int] = {}
    latest_by_symbol: dict[str, dict[str, Any]] = {}
    for bar in bars:
        provider = bar.source_provider or bar.source.value
        by_provider[provider] = by_provider.get(provider, 0) + 1
        current = latest_by_symbol.get(bar.symbol)
        if current is None or bar.ts.isoformat() > current["ts"]:
            latest_by_symbol[bar.symbol] = {
                "ts": bar.ts.isoformat(),
                "source_provider": provider,
                "source_feed": bar.source_feed,
                "quality_score": bar.quality_score,
            }
    providers = sorted(by_provider)
    return {
        "bar_count": len(bars),
        "provider_counts": by_provider,
        "providers": providers,
        "latest_by_symbol": latest_by_symbol,
        "only_yfinance_dev": bool(providers) and providers == ["yfinance_dev"],
    }


def _usage_count(store: Store, provider: str, endpoint: str, symbol: str, quota_window: str) -> int:
    for item in store.list_provider_usage(provider=provider, symbol=symbol if provider == "futu" else "*", limit=20):
        if item.endpoint == endpoint and item.quota_window == quota_window:
            if item.reset_at and item.reset_at < utc_now():
                return 0
            return item.request_count
    return 0


def _result(
    provider: str,
    feed: str,
    symbol: str,
    broker_symbol: str | None,
    rows: list[dict[str, Any]],
    *,
    adjusted: bool,
    quality: float,
) -> ProviderBarResult:
    license_note = {
        "futu": "Futu OpenD read-only historical K-line; paper-only local use.",
        "alpaca": "Alpaca market data; observe account data plan and terms.",
        "stooq": "Stooq free historical CSV; paper-only research/outcome validation.",
        "fmp": "Financial Modeling Prep API; observe quota and license terms.",
        "twelvedata": "Twelve Data API; observe quota and license terms.",
        "alphavantage": "Alpha Vantage API; observe quota and license terms.",
        "yfinance_dev": "Unofficial Yahoo Finance chart endpoint; dev-only, not verified evidence.",
    }.get(provider, "Fallback market data; paper-only research/outcome validation.")
    return ProviderBarResult(
        provider=provider,
        source=PROVIDER_SOURCE[provider],
        source_feed=feed,
        symbol=symbol.upper(),
        broker_symbol=broker_symbol,
        rows=rows,
        adjusted=adjusted,
        quality_score=quality,
        license_note=license_note,
        retrieved_at=utc_now(),
        skipped_providers=[],
    )


def _get_json(url: str, *, params: dict[str, Any] | None = None, headers: dict[str, str] | None = None, timeout: float) -> dict[str, Any]:
    with httpx.Client(timeout=timeout, follow_redirects=True) as client:
        response = client.get(url, params=params, headers=headers)
        response.raise_for_status()
        return response.json()


def _get_text(url: str, *, timeout: float) -> str:
    with httpx.Client(timeout=timeout, follow_redirects=True) as client:
        response = client.get(url)
        response.raise_for_status()
        return response.text


def _row(ts: Any, open_: Any, high: Any, low: Any, close: Any, volume: Any, *, raw: dict[str, Any]) -> dict[str, Any]:
    return {
        "ts": _parse_ts(ts),
        "open": _float(open_),
        "high": _float(high),
        "low": _float(low),
        "close": _float(close),
        "volume": _float(volume, default=0.0),
        "raw": dict(raw),
    }


def _valid_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        [
            row
            for row in rows
            if row["ts"] and row["open"] is not None and row["high"] is not None and row["low"] is not None and row["close"] is not None
        ],
        key=lambda row: row["ts"],
    )


def _parse_ts(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    text = str(value).strip()
    for fmt in ("%Y-%m-%d", "%Y%m%d"):
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _float(value: Any, default: float | None = None) -> float | None:
    try:
        if value in (None, ""):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _at(values: Any, index: int) -> Any:
    if not isinstance(values, list) or index >= len(values):
        return None
    return values[index]


def _us_symbol(symbol: str) -> str:
    symbol = symbol.upper()
    return symbol.split(".", 1)[1] if symbol.startswith("US.") else symbol


def _stooq_symbol(symbol: str) -> str:
    symbol = symbol.upper()
    if symbol.startswith("HK."):
        return f"{symbol.split('.', 1)[1].lstrip('0') or '0'}.hk"
    return f"{_us_symbol(symbol).lower()}.us"


def _yahoo_symbol(symbol: str) -> str:
    symbol = symbol.upper()
    if symbol.startswith("HK."):
        return f"{symbol.split('.', 1)[1]}.HK"
    return _us_symbol(symbol)
