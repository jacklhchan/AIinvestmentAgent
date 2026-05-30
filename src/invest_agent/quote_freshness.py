from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from .models import Quote


DEFAULT_QUOTE_FRESH_SECONDS = 24 * 3600
US_MARKET_CLOSE = time(16, 0)
US_MARKET_TZ = ZoneInfo("America/New_York")


def quote_age_seconds(quote: Quote | None, now: datetime) -> float | None:
    if not quote:
        return None
    return max(0.0, (_aware(now) - _aware(quote.updated_at)).total_seconds())


def quote_freshness_limit_seconds(
    now: datetime,
    *,
    market: str = "US",
    base_seconds: int = DEFAULT_QUOTE_FRESH_SECONDS,
) -> int:
    if market.upper() != "US":
        return base_seconds
    latest_close = latest_completed_us_session_close(now)
    session_aware_limit = int((_aware(now) - latest_close).total_seconds() + 6 * 3600)
    return max(base_seconds, session_aware_limit)


def quote_is_fresh(
    quote: Quote | None,
    now: datetime,
    *,
    market: str = "US",
    base_seconds: int = DEFAULT_QUOTE_FRESH_SECONDS,
) -> bool:
    age = quote_age_seconds(quote, now)
    if age is None:
        return False
    return age <= quote_freshness_limit_seconds(now, market=market, base_seconds=base_seconds)


def latest_completed_us_session_close(now: datetime) -> datetime:
    local_now = _aware(now).astimezone(US_MARKET_TZ)
    candidate = local_now.date()
    if not _is_us_trading_day(candidate) or local_now.time() < US_MARKET_CLOSE:
        candidate = _previous_us_trading_day(candidate)
    while not _is_us_trading_day(candidate):
        candidate -= timedelta(days=1)
    return datetime.combine(candidate, US_MARKET_CLOSE, tzinfo=US_MARKET_TZ).astimezone(timezone.utc)


def _previous_us_trading_day(value: date) -> date:
    candidate = value - timedelta(days=1)
    while not _is_us_trading_day(candidate):
        candidate -= timedelta(days=1)
    return candidate


def _is_us_trading_day(value: date) -> bool:
    return value.weekday() < 5 and value not in _us_market_holidays(value.year)


def _us_market_holidays(year: int) -> set[date]:
    return {
        _observed(date(year, 1, 1)),
        _nth_weekday(year, 1, 0, 3),
        _nth_weekday(year, 2, 0, 3),
        _easter_date(year) - timedelta(days=2),
        _last_weekday(year, 5, 0),
        _observed(date(year, 6, 19)),
        _observed(date(year, 7, 4)),
        _nth_weekday(year, 9, 0, 1),
        _nth_weekday(year, 11, 3, 4),
        _observed(date(year, 12, 25)),
    }


def _observed(value: date) -> date:
    if value.weekday() == 5:
        return value - timedelta(days=1)
    if value.weekday() == 6:
        return value + timedelta(days=1)
    return value


def _nth_weekday(year: int, month: int, weekday: int, nth: int) -> date:
    current = date(year, month, 1)
    while current.weekday() != weekday:
        current += timedelta(days=1)
    return current + timedelta(days=7 * (nth - 1))


def _last_weekday(year: int, month: int, weekday: int) -> date:
    current = date(year, month + 1, 1) - timedelta(days=1) if month < 12 else date(year, 12, 31)
    while current.weekday() != weekday:
        current -= timedelta(days=1)
    return current


def _easter_date(year: int) -> date:
    a = year % 19
    b = year // 100
    c = year % 100
    d = b // 4
    e = b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i = c // 4
    k = c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month = (h + l - 7 * m + 114) // 31
    day = ((h + l - 7 * m + 114) % 31) + 1
    return date(year, month, day)


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
