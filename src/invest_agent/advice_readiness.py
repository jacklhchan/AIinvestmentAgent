from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Any

from .config import Settings
from .market_news import resolve_watchlist_symbols
from .models import SignalSide, utc_now
from .quote_freshness import quote_age_seconds, quote_freshness_limit_seconds, quote_is_fresh
from .signal_outcomes import SignalOutcomeEvaluator, _symbol_candidates
from .store import Store


READINESS_RULE_VERSION = "advice_readiness_v1"


class AdviceReadinessService:
    """Summarizes whether proactive signals have enough local data for useful advice."""

    def __init__(self, settings: Settings, store: Store):
        self.settings = settings
        self.store = store

    def run(self) -> dict[str, Any]:
        checked_at = utc_now()
        latest_run = self.store.get_latest_signal_run()
        universe = latest_run.universe if latest_run else resolve_watchlist_symbols(self.settings, self.store, None)
        checks = {
            "quote_freshness": self._check_quote_freshness(checked_at),
            "account_snapshot": self._check_account_snapshot(checked_at),
            "fundamentals_coverage": self._check_fundamentals_coverage(universe),
            "verified_evidence_coverage": self._check_verified_evidence_coverage(latest_run.signals if latest_run else []),
            "news_freshness": self._check_news_freshness(checked_at),
            "latest_signal_run": self._check_latest_signal_run(checked_at, latest_run),
            "latest_committee_review": self._check_latest_committee_review(checked_at),
            "outcome_validation": self._check_outcome_validation(),
        }
        by_symbol = {symbol: self.run_for_symbol(symbol) for symbol in universe}
        severity = _overall_severity(checks)
        score = round(sum(float(check.get("score", 0.0)) for check in checks.values()) / max(1, len(checks)), 1)
        return {
            "ok": severity != "error" and score >= 60,
            "severity": severity,
            "score": score,
            "readiness_version": READINESS_RULE_VERSION,
            "checked_at": checked_at.isoformat(),
            "checks": checks,
            "by_symbol": by_symbol,
            "summary": _summary(checks, score),
        }

    def run_for_symbol(self, symbol: str, signal=None) -> dict[str, Any]:
        checked_at = utc_now()
        signal = signal or self._latest_signal_for_symbol(symbol)
        checks = {
            "quote_freshness": self._symbol_quote_freshness(symbol, checked_at),
            "price_bar_coverage": self._symbol_price_bar_coverage(symbol),
            "fundamentals_coverage": self._symbol_fundamentals(symbol),
            "verified_evidence": self._symbol_verified_evidence(symbol, signal),
            "directional_evidence": self._symbol_directional_evidence(symbol, signal),
            "news_freshness": self._symbol_news_freshness(symbol, checked_at),
            "committee_freshness": self._symbol_committee_freshness(symbol, signal, checked_at),
            "outcome_coverage": self._symbol_outcome_coverage(symbol, signal),
        }
        score = round(sum(float(check.get("score", 0.0)) for check in checks.values()) / max(1, len(checks)), 1)
        severity = _overall_severity(checks)
        return {
            "symbol": symbol.upper(),
            "ok": severity != "error" and score >= 75,
            "severity": severity,
            "score": score,
            "checked_at": checked_at.isoformat(),
            "checks": checks,
            "failed_checks": [
                {"check": name, "status": check["status"], "message": check["message"]}
                for name, check in checks.items()
                if check["status"] != "ok"
            ],
        }

    def _check_quote_freshness(self, now: datetime) -> dict[str, Any]:
        quotes = self.store.list_quotes()
        if not quotes:
            return _check("error", "No quote snapshots available for signal scoring.", {"quote_count": 0}, 0)
        stale = [quote.symbol for quote in quotes if not quote_is_fresh(quote, now)]
        latest = max((_aware(quote.updated_at) for quote in quotes), default=None)
        if len(stale) == len(quotes):
            status = "error"
            message = "All quote snapshots are stale."
            score = 0
        elif stale:
            status = "warn"
            message = "Some quote snapshots are stale."
            score = 65
        else:
            status = "ok"
            message = "Quote snapshots are fresh enough for proactive signal scoring."
            score = 100
        return _check(
            status,
            message,
            {
                "quote_count": len(quotes),
                "latest_updated_at": latest.isoformat() if latest else None,
                "latest_age_seconds": quote_age_seconds(next((quote for quote in quotes if _aware(quote.updated_at) == latest), None), now),
                "freshness_limit_seconds": quote_freshness_limit_seconds(now),
                "stale_symbols": stale[:20],
                "market_session_aware": True,
            },
            score,
        )

    def _check_account_snapshot(self, now: datetime) -> dict[str, Any]:
        event = _latest_of_events(self.store, ("futu_account_snapshot_refreshed", "futu_account_snapshot_failed", "portfolio_upserted"))
        portfolio = self.store.get_portfolio()
        if not self.settings.futu_read_enabled:
            return _check(
                "warn",
                "Futu account snapshot is disabled; BUY/WATCH can score, but SELL/REDUCE position context may be limited.",
                {"position_count": len(portfolio.positions), "futu_read_enabled": False},
                60,
            )
        if not event:
            return _check(
                "warn",
                "No account snapshot audit event found; BUY/WATCH can score, but SELL/REDUCE may be blocked.",
                {"position_count": len(portfolio.positions), "futu_read_enabled": True},
                45,
            )
        payload = _payload(event)
        age = _age_seconds(now, _parse_dt(event.get("created_at")))
        if event.get("event_type") == "futu_account_snapshot_failed":
            return _check(
                "warn",
                "Latest Futu account snapshot failed; quote-based BUY/WATCH signals can still run.",
                {"created_at": event.get("created_at"), "age_seconds": age, "payload": payload, "position_count": len(portfolio.positions)},
                45,
            )
        status = "warn" if age is not None and age > max(1800, self.settings.autonomy_cycle_seconds * 2) else "ok"
        return _check(
            status,
            "Account snapshot is stale." if status == "warn" else "Account snapshot is recent enough.",
            {"created_at": event.get("created_at"), "age_seconds": age, "payload": payload, "position_count": len(portfolio.positions)},
            75 if status == "warn" else 100,
        )

    def _check_fundamentals_coverage(self, universe: list[str]) -> dict[str, Any]:
        fundamentals = self.store.list_fundamentals()
        covered = {symbol for item in fundamentals for symbol in _symbol_candidates(item.symbol)}
        universe = list(dict.fromkeys(universe))
        covered_symbols = [symbol for symbol in universe if any(candidate in covered for candidate in _symbol_candidates(symbol))]
        coverage = len(covered_symbols) / len(universe) if universe else 0.0
        if not universe:
            status, message, score = "warn", "No watchlist or latest signal universe found.", 45
        elif coverage >= 0.7:
            status, message, score = "ok", "Fundamentals coverage is broad enough for signal context.", 100
        elif coverage > 0:
            status, message, score = "warn", "Fundamentals coverage is partial.", 65
        else:
            status, message, score = "warn", "No fundamentals snapshots cover the current signal universe.", 35
        return _check(
            status,
            message,
            {
                "universe_count": len(universe),
                "snapshot_count": len(fundamentals),
                "covered_count": len(covered_symbols),
                "coverage": round(coverage, 4),
                "missing_symbols": [symbol for symbol in universe if symbol not in covered_symbols][:20],
            },
            score,
        )

    def _check_verified_evidence_coverage(self, signals) -> dict[str, Any]:
        directional = [
            signal
            for signal in signals
            if signal.side
            in {SignalSide.BUY_SIGNAL, SignalSide.ADD_SIGNAL, SignalSide.SELL_SIGNAL, SignalSide.REDUCE_SIGNAL, SignalSide.BLOCKED}
        ]
        verified = [
            signal
            for signal in directional
            if int(((signal.gates or {}).get("research_gate") or {}).get("verified_count") or 0) > 0
        ]
        coverage = len(verified) / len(directional) if directional else 0.0
        if not directional:
            status, message, score = "warn", "No directional paper signals were available for evidence coverage.", 50
        elif coverage >= 0.7:
            status, message, score = "ok", "Directional signals have verified evidence coverage.", 100
        elif verified:
            status, message, score = "warn", "Only some directional signals have verified evidence.", 65
        else:
            status, message, score = "warn", "Directional signals lack verified evidence coverage.", 35
        return _check(
            status,
            message,
            {"directional_count": len(directional), "verified_count": len(verified), "coverage": round(coverage, 4)},
            score,
        )

    def _check_news_freshness(self, now: datetime) -> dict[str, Any]:
        news = self.store.list_news(limit=50)
        if not news:
            return _check("warn", "No news items found for catalyst context.", {"news_count": 0}, 45)
        latest = max((_aware(item.published_at) for item in news), default=None)
        age = _age_seconds(now, latest)
        status = "warn" if age is not None and age > 2 * 24 * 3600 else "ok"
        return _check(
            status,
            "News/catalyst context is stale." if status == "warn" else "News/catalyst context is recent enough.",
            {"news_count": len(news), "latest_published_at": latest.isoformat() if latest else None, "age_seconds": age},
            70 if status == "warn" else 100,
        )

    def _check_latest_signal_run(self, now: datetime, latest_run) -> dict[str, Any]:
        if not latest_run:
            return _check("warn", "No proactive paper signal run found.", {}, 35)
        age = _age_seconds(now, _aware(latest_run.created_at))
        stale_after = max(1800, self.settings.autonomy_cycle_seconds * 2)
        status = "warn" if age is not None and age > stale_after else "ok"
        return _check(
            status,
            "Latest paper signal run is stale." if status == "warn" else "Latest paper signal run is recent.",
            {
                "signal_run_id": latest_run.id,
                "created_at": latest_run.created_at.isoformat(),
                "age_seconds": age,
                "stale_after_seconds": stale_after,
                "signal_count": len(latest_run.signals),
                "max_score": latest_run.metrics.get("max_score", 0),
                "buy_count": latest_run.metrics.get("buy_count", 0),
                "sell_reduce_count": latest_run.metrics.get("sell_reduce_count", 0),
                "blocked_count": latest_run.metrics.get("blocked_count", 0),
                "watch_count": latest_run.metrics.get("watch_count", 0),
            },
            70 if status == "warn" else 100,
        )

    def _check_latest_committee_review(self, now: datetime) -> dict[str, Any]:
        reviews = self.store.list_committee_reviews(limit=1)
        if not reviews:
            return _check("warn", "No investment committee review found for recent signal context.", {}, 45)
        review = reviews[0]
        age = _age_seconds(now, _aware(review.completed_at or review.created_at))
        status = "warn" if age is not None and age > 7 * 24 * 3600 else "ok"
        return _check(
            status,
            "Latest committee review is stale." if status == "warn" else "Latest committee review is recent enough.",
            {
                "committee_review_id": review.id,
                "topic": review.topic,
                "status": review.status.value,
                "created_at": review.created_at.isoformat(),
                "completed_at": review.completed_at.isoformat() if review.completed_at else None,
                "age_seconds": age,
            },
            70 if status == "warn" else 100,
        )

    def _check_outcome_validation(self) -> dict[str, Any]:
        summary = SignalOutcomeEvaluator(self.settings, self.store).summary(limit=200)
        evaluated = int(summary.get("evaluated_window_count") or 0)
        if evaluated:
            return _check("ok", "Signal outcome validation has evaluated windows.", summary, 100)
        return _check(
            "warn",
            "No evaluated signal outcome windows yet; run signals-evaluate-outcomes after price bars are imported.",
            summary,
            40,
        )

    def _latest_signal_for_symbol(self, symbol: str):
        candidates = set(_symbol_candidates(symbol))
        for signal in self.store.list_signals(limit=200):
            if any(candidate in candidates for candidate in _symbol_candidates(signal.symbol)):
                return signal
        return None

    def _symbol_quote_freshness(self, symbol: str, now: datetime) -> dict[str, Any]:
        quote = self._find_quote(symbol)
        if not quote:
            return _check("error", f"{symbol.upper()} has no quote snapshot.", {}, 0)
        fresh = quote_is_fresh(quote, now)
        source = str(quote.source or "")
        fallback_penalty = source and source not in {"futu-opend", "futu"}
        score = 100 if fresh else 55
        if fallback_penalty:
            score = min(score, 75)
        return _check(
            "warn" if fallback_penalty else "ok" if fresh else "warn",
            f"{symbol.upper()} quote source is fallback; keep BUY/SELL non-actionable for intraday decisions."
            if fallback_penalty
            else f"{symbol.upper()} quote is fresh enough."
            if fresh
            else f"{symbol.upper()} quote is stale.",
            {
                "quote_symbol": quote.symbol,
                "quote_source": source,
                "updated_at": quote.updated_at.isoformat(),
                "age_seconds": quote_age_seconds(quote, now),
                "freshness_limit_seconds": quote_freshness_limit_seconds(now),
            },
            score,
        )

    def _symbol_price_bar_coverage(self, symbol: str) -> dict[str, Any]:
        bars = []
        for candidate in _symbol_candidates(symbol):
            bars.extend(self.store.list_price_bars(symbol=candidate, limit=5, ascending=False))
        if not bars:
            return _check("warn", f"{symbol.upper()} has no imported EOD price bars.", {"bar_count": 0}, 45)
        latest = max(bars, key=lambda bar: bar.ts)
        status = "warn" if latest.source_provider == "yfinance_dev" else "ok"
        return _check(
            status,
            f"{symbol.upper()} EOD price bars are available."
            if status == "ok"
            else f"{symbol.upper()} only has dev-only yfinance bars; do not treat them as verified evidence.",
            {
                "bar_count": len(bars),
                "latest_ts": latest.ts.isoformat(),
                "source_provider": latest.source_provider,
                "source_feed": latest.source_feed,
                "quality_score": latest.quality_score,
                "license_note": latest.license_note,
                "supports_outcome_validation": True,
                "verified_primary_evidence": False,
            },
            max(35, latest.quality_score * 100),
        )

    def _symbol_fundamentals(self, symbol: str) -> dict[str, Any]:
        snapshot = self._find_fundamentals(symbol)
        if not snapshot:
            return _check("warn", f"{symbol.upper()} has no fundamentals snapshot.", {}, 40)
        return _check(
            "ok",
            f"{symbol.upper()} fundamentals snapshot is available.",
            {"snapshot_symbol": snapshot.symbol, "updated_at": snapshot.updated_at.isoformat(), "metric_count": len(snapshot.metrics)},
            100,
        )

    def _symbol_verified_evidence(self, symbol: str, signal) -> dict[str, Any]:
        if signal:
            gate = (signal.gates or {}).get("research_gate") or {}
            verified_count = int(gate.get("verified_count") or 0)
            if verified_count:
                return _check("ok", f"{symbol.upper()} signal has verified research-gate evidence.", {"verified_count": verified_count}, 100)
        if self._find_fundamentals(symbol):
            return _check("ok", f"{symbol.upper()} has SEC/companyfacts evidence available.", {"source": "fundamentals"}, 90)
        return _check("warn", f"{symbol.upper()} lacks verified primary-source or fundamentals evidence.", {}, 35)

    def _symbol_directional_evidence(self, symbol: str, signal) -> dict[str, Any]:
        if signal and (signal.gates or {}).get("directional_evidence"):
            return _check("ok", f"{symbol.upper()} signal has directional evidence.", {"from_signal_gate": True}, 100)
        recent_news = self._recent_news(symbol)
        if recent_news:
            return _check("ok", f"{symbol.upper()} has recent market/news evidence.", {"news_count": len(recent_news)}, 80)
        return _check("warn", f"{symbol.upper()} lacks recent directional market evidence.", {"news_count": 0}, 35)

    def _symbol_news_freshness(self, symbol: str, now: datetime) -> dict[str, Any]:
        news = self._recent_news(symbol, days=7)
        latest = max((_aware(item.published_at) for item in news), default=None)
        if not latest:
            return _check("warn", f"{symbol.upper()} has no recent news items.", {"news_count": 0}, 45)
        age = _age_seconds(now, latest)
        fresh = age is not None and age <= 2 * 24 * 3600
        return _check(
            "ok" if fresh else "warn",
            f"{symbol.upper()} news is recent enough." if fresh else f"{symbol.upper()} news/catalyst context is stale.",
            {"news_count": len(news), "latest_published_at": latest.isoformat(), "age_seconds": age},
            100 if fresh else 65,
        )

    def _symbol_committee_freshness(self, symbol: str, signal, now: datetime) -> dict[str, Any]:
        if not signal:
            return _check("warn", f"{symbol.upper()} has no signal-specific committee run.", {}, 45)
        runs = self.store.list_investor_committee_runs(signal_id=signal.id, limit=1)
        if not runs:
            return _check("warn", f"{symbol.upper()} has no fresh investor committee run for the latest signal.", {"signal_id": signal.id}, 45)
        run = runs[0]
        age = _age_seconds(now, _aware(run.created_at))
        stale_after = self.settings.paper_advice_committee_freshness_minutes * 60
        fresh = age is not None and age <= stale_after
        return _check(
            "ok" if fresh else "warn",
            f"{symbol.upper()} committee run is fresh." if fresh else f"{symbol.upper()} committee run is stale.",
            {"signal_id": signal.id, "committee_run_id": run.id, "age_seconds": age, "stale_after_seconds": stale_after},
            100 if fresh else 55,
        )

    def _symbol_outcome_coverage(self, symbol: str, signal) -> dict[str, Any]:
        if signal:
            rows = self.store.list_signal_outcome_rows(signal_id=signal.id, limit=20)
            if rows:
                return _check("ok", f"{symbol.upper()} latest signal has evaluated outcome rows.", {"signal_id": signal.id, "row_count": len(rows)}, 100)
            return _check("warn", f"{symbol.upper()} latest signal has no evaluated outcome rows yet.", {"signal_id": signal.id}, 45)
        candidates = set(_symbol_candidates(symbol))
        count = 0
        for row in self.store.list_signal_outcome_rows(limit=500):
            signal_for_row = self.store.get_signal(row.signal_id)
            if signal_for_row and any(candidate in candidates for candidate in _symbol_candidates(signal_for_row.symbol)):
                count += 1
        return _check(
            "ok" if count else "warn",
            f"{symbol.upper()} has historical outcome coverage." if count else f"{symbol.upper()} has no outcome coverage yet.",
            {"row_count": count},
            90 if count else 45,
        )

    def _find_quote(self, symbol: str):
        for candidate in _symbol_candidates(symbol):
            quote = self.store.get_quote(candidate)
            if quote:
                return quote
        candidates = set(_symbol_candidates(symbol))
        return next((quote for quote in self.store.list_quotes() if any(item in candidates for item in _symbol_candidates(quote.symbol))), None)

    def _find_fundamentals(self, symbol: str):
        for candidate in _symbol_candidates(symbol):
            snapshot = self.store.get_fundamentals(candidate)
            if snapshot:
                return snapshot
        candidates = set(_symbol_candidates(symbol))
        return next((item for item in self.store.list_fundamentals() if any(candidate in candidates for candidate in _symbol_candidates(item.symbol))), None)

    def _recent_news(self, symbol: str, *, days: int | None = None):
        cutoff = utc_now() - timedelta(days=days or self.settings.news_lookback_days)
        candidates = set(_symbol_candidates(symbol))
        items = []
        for candidate in candidates:
            items.extend(self.store.list_news(symbol=candidate, limit=80))
        unique = {item.id: item for item in items}
        return [item for item in unique.values() if _aware(item.published_at) >= cutoff]


def _check(status: str, message: str, metrics: dict[str, Any], score: float) -> dict[str, Any]:
    return {"status": status, "message": message, "metrics": metrics, "score": score}


def _overall_severity(checks: dict[str, dict[str, Any]]) -> str:
    statuses = {item["status"] for item in checks.values()}
    if "error" in statuses:
        return "error"
    if "warn" in statuses:
        return "warn"
    return "ok"


def _summary(checks: dict[str, dict[str, Any]], score: float) -> dict[str, Any]:
    counts = Counter(item["status"] for item in checks.values())
    attention = [
        {"check": name, "status": check["status"], "message": check["message"]}
        for name, check in checks.items()
        if check["status"] != "ok"
    ]
    return {"score": score, "counts": dict(counts), "attention": attention}


def _latest_of_events(store: Store, event_types: tuple[str, ...]) -> dict[str, Any] | None:
    events: list[dict[str, Any]] = []
    for event_type in event_types:
        events.extend(store.list_audit_events(limit=1, event_type=event_type))
    if not events:
        return None
    return max(events, key=lambda event: event.get("created_at") or "")


def _payload(event: dict[str, Any] | None) -> dict[str, Any]:
    if not event:
        return {}
    payload = event.get("payload")
    if isinstance(payload, str):
        try:
            return json.loads(payload)
        except json.JSONDecodeError:
            return {"raw": payload}
    return payload if isinstance(payload, dict) else {}


def _parse_dt(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return _aware(value)
    if isinstance(value, str):
        try:
            return _aware(datetime.fromisoformat(value.replace("Z", "+00:00")))
        except ValueError:
            return None
    return None


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _age_seconds(now: datetime, value: datetime | None) -> float | None:
    if value is None:
        return None
    return max(0.0, (_aware(now) - _aware(value)).total_seconds())
