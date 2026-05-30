from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timezone
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
        severity = _overall_severity(checks)
        score = round(sum(float(check.get("score", 0.0)) for check in checks.values()) / max(1, len(checks)), 1)
        return {
            "ok": severity != "error" and score >= 60,
            "severity": severity,
            "score": score,
            "readiness_version": READINESS_RULE_VERSION,
            "checked_at": checked_at.isoformat(),
            "checks": checks,
            "summary": _summary(checks, score),
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
