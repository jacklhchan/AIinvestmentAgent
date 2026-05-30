from __future__ import annotations

import json
import sqlite3
from collections import Counter
from datetime import datetime, timezone
from typing import Any

from .advice_readiness import AdviceReadinessService
from .config import Settings
from .futu_adapter import discover_futu_accounts, get_futu_status
from .store import Store
from .models import utc_now
from .quote_freshness import quote_age_seconds, quote_freshness_limit_seconds, quote_is_fresh
from .signal_outcomes import SignalOutcomeEvaluator


class RuntimeDoctorService:
    def __init__(self, settings: Settings, store: Store):
        self.settings = settings
        self.store = store
        self._futu_status_cache: dict[str, Any] | None = None
        self._futu_accounts_cache: dict[str, Any] | None = None

    def run(self) -> dict[str, Any]:
        checked_at = utc_now()
        checks = {
            "database": self._check_database(),
            "latest_audit_event": self._check_latest_audit_event(checked_at),
            "latest_autonomy_cycle": self._check_latest_autonomy_cycle(checked_at),
            "latest_advisor_run": self._check_latest_advisor_run(checked_at),
            "futu_quote_connection": self._check_futu_quote_connection(),
            "futu_account_discovery": self._check_futu_account_discovery(),
            "futu_selected_account_valid": self._check_futu_selected_account_valid(),
            "futu_account_snapshot": self._check_futu_account_snapshot(checked_at),
            "futu_quote_refresh": self._check_futu_quote_refresh(checked_at),
            "quote_freshness": self._check_quote_freshness(checked_at),
            "fundamental_freshness": self._check_fundamental_freshness(checked_at),
            "latest_proposal_draft": self._check_latest_proposal_draft(checked_at),
            "latest_signal_run": self._check_latest_signal_run(checked_at),
            "signal_outcomes": self._check_signal_outcomes(),
            "advice_readiness": self._check_advice_readiness(),
            "skipped_reasons": self._check_skipped_reasons(),
            "draft_min_score": self._check_draft_min_score(),
            "proposal_status_mismatches": self._check_proposal_status_mismatches(),
        }
        severity = _overall_severity(checks)
        return {
            "ok": severity != "error",
            "severity": severity,
            "checked_at": checked_at.isoformat(),
            "settings": self._settings_summary(),
            "checks": checks,
            "summary": _summary(checks),
        }

    def _settings_summary(self) -> dict[str, Any]:
        return {
            "db_path": str(self.settings.db_path),
            "mode": self.settings.mode,
            "paper_only": self.settings.is_paper,
            "draft_min_score": self.settings.draft_min_score,
            "draft_max_candidates": self.settings.draft_max_candidates,
            "signal_buy_threshold": self.settings.signal_buy_threshold,
            "signal_sell_threshold": self.settings.signal_sell_threshold,
            "signal_watch_threshold": self.settings.signal_watch_threshold,
            "signal_max_per_run": self.settings.signal_max_per_run,
            "signal_expiry_hours": self.settings.signal_expiry_hours,
            "autonomy_cycle_seconds": self.settings.autonomy_cycle_seconds,
            "autonomy_create_proposals": self.settings.autonomy_create_proposals,
            "autonomy_proposal_cooldown_minutes": self.settings.autonomy_proposal_cooldown_minutes,
            "futu_read_enabled": self.settings.futu_read_enabled,
            "futu_host": self.settings.futu_host,
            "futu_monitor_port": self.settings.futu_monitor_port,
            "futu_trd_env": self.settings.futu_trd_env,
            "futu_trd_market": self.settings.futu_trd_market,
            "futu_acc_id_configured": bool(self.settings.futu_acc_id),
            "futu_security_firm_configured": bool(self.settings.futu_security_firm),
            "futu_sim_acc_type_configured": bool(self.settings.futu_sim_acc_type),
        }

    def _check_database(self) -> dict[str, Any]:
        required_tables = {
            "audit_events",
            "advisor_briefs",
            "advisor_pulses",
            "advisor_recommendations",
            "fundamentals",
            "news",
            "proposals",
            "quotes",
            "research_evidence",
            "research_goals",
            "investor_framework_profiles",
            "investor_committee_runs",
            "investor_committee_votes",
            "paper_advice_runs",
            "paper_advice_items",
            "signal_outcome_rows",
            "signal_runs",
            "signals",
        }
        try:
            with self.store.connect() as conn:
                quick_check = conn.execute("PRAGMA quick_check").fetchone()[0]
                tables = {row["name"] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
                missing = sorted(required_tables - tables)
                conn.execute("BEGIN IMMEDIATE")
                conn.execute("ROLLBACK")
        except sqlite3.DatabaseError as exc:
            return _check("error", f"SQLite check failed: {exc}", {"db_path": str(self.settings.db_path)})
        status = "ok" if quick_check == "ok" and not missing else "error"
        message = "SQLite quick_check ok and core schema is present." if status == "ok" else "SQLite schema check failed."
        return _check(
            status,
            message,
            {
                "db_path": str(self.settings.db_path),
                "quick_check": quick_check,
                "missing_tables": missing,
                "writable": True,
            },
        )

    def _check_latest_audit_event(self, now: datetime) -> dict[str, Any]:
        event = _latest_event(self.store)
        if not event:
            return _check("warn", "No audit events found.", {})
        created_at = _parse_dt(event.get("created_at"))
        return _check(
            "ok",
            f"Latest audit event is {event.get('event_type')}.",
            {
                "event_type": event.get("event_type"),
                "entity_type": event.get("entity_type"),
                "entity_id": event.get("entity_id"),
                "created_at": event.get("created_at"),
                "age_seconds": _age_seconds(now, created_at),
            },
        )

    def _check_latest_autonomy_cycle(self, now: datetime) -> dict[str, Any]:
        event = _latest_event(self.store, "autonomy_cycle_completed")
        if not event:
            return _check("warn", "No completed safe autonomy cycle found.", {})
        payload = _payload(event)
        finished_at = _parse_dt(payload.get("finished_at") or event.get("created_at"))
        age = _age_seconds(now, finished_at)
        stale_after = max(1800, self.settings.autonomy_cycle_seconds * 2)
        status = "warn" if age is not None and age > stale_after else "ok"
        return _check(
            status,
            "Safe autonomy cycle is stale." if status == "warn" else "Safe autonomy has a recent completed cycle.",
            {
                "created_at": event.get("created_at"),
                "finished_at": payload.get("finished_at"),
                "age_seconds": age,
                "stale_after_seconds": stale_after,
                "mode": payload.get("mode"),
                "created_count": payload.get("created_count", 0),
            },
        )

    def _check_latest_advisor_run(self, now: datetime) -> dict[str, Any]:
        event = _latest_event(self.store, "advisor_scheduler_checked")
        if not event:
            return _check("warn", "No advisor scheduler check found.", {})
        created_at = _parse_dt(event.get("created_at"))
        age = _age_seconds(now, created_at)
        status = "warn" if age is not None and age > 180 else "ok"
        return _check(
            status,
            "Advisor scheduler check is stale." if status == "warn" else "Advisor scheduler checked recently.",
            {"created_at": event.get("created_at"), "age_seconds": age, "payload": _payload(event)},
        )

    def _check_futu_quote_connection(self) -> dict[str, Any]:
        status = self._futu_status()
        if not self.settings.futu_read_enabled:
            level = "warn"
            message = "Futu read-only quote integration is disabled by config."
        elif not status.get("connected"):
            level = "error"
            message = "Futu read-only quote integration is enabled but not connected."
        else:
            level = "ok"
            message = "Futu read-only quote integration is connected."
        return _check(level, message, status)

    def _check_futu_account_discovery(self) -> dict[str, Any]:
        discovery = self._futu_accounts()
        if not self.settings.futu_read_enabled:
            return _check("warn", "Futu account discovery is disabled by config.", discovery)
        if discovery.get("error"):
            return _check("error", f"Futu account discovery failed: {discovery['error']}", discovery)
        count = int(discovery.get("account_count") or 0)
        level = "ok" if count else "warn"
        return _check(
            level,
            f"Discovered {count} Futu account(s)." if count else "No Futu accounts discovered.",
            discovery,
        )

    def _check_futu_selected_account_valid(self) -> dict[str, Any]:
        discovery = self._futu_accounts()
        if not self.settings.futu_read_enabled:
            return _check("warn", "Futu account selection is disabled by config.", discovery)
        if discovery.get("error"):
            return _check("error", f"Futu account selection could not be checked: {discovery['error']}", discovery)
        status = str(discovery.get("selection_status") or "warn")
        level = "ok" if status == "ok" else "error" if status == "error" else "warn"
        return _check(
            level,
            discovery.get("message") or "Futu account selection diagnostics are available.",
            {
                "selection_status": status,
                "selected_account": discovery.get("selected_account"),
                "candidate_acc_ids": discovery.get("candidate_acc_ids", []),
                "configured_acc_id": self.settings.futu_acc_id if self.settings.futu_acc_id else None,
                "trd_env": self.settings.futu_trd_env,
                "trd_market": self.settings.futu_trd_market,
            },
        )

    def _check_futu_account_snapshot(self, now: datetime) -> dict[str, Any]:
        event = _latest_of_events(self.store, ("futu_account_snapshot_refreshed", "futu_account_snapshot_failed"))
        if not event:
            return _check("warn", "No Futu account snapshot audit event found.", {})
        payload = _payload(event)
        created_at = _parse_dt(event.get("created_at"))
        age = _age_seconds(now, created_at)
        stale_after = max(1800, self.settings.autonomy_cycle_seconds * 2)
        if event.get("event_type") == "futu_account_snapshot_failed":
            return _check(
                "error",
                "Latest Futu account snapshot failed.",
                {"created_at": event.get("created_at"), "age_seconds": age, "payload": payload},
            )
        status = "warn" if age is not None and age > stale_after else "ok"
        return _check(
            status,
            "Latest Futu account snapshot is stale." if status == "warn" else "Latest Futu account snapshot is recent.",
            {"created_at": event.get("created_at"), "age_seconds": age, "stale_after_seconds": stale_after, "payload": payload},
        )

    def _check_futu_quote_refresh(self, now: datetime) -> dict[str, Any]:
        event = _latest_of_events(self.store, ("futu_quotes_refreshed", "futu_quote_refresh_failed"))
        if not event:
            return _check("warn", "No Futu quote refresh audit event found.", {})
        payload = _payload(event)
        created_at = _parse_dt(event.get("created_at"))
        age = _age_seconds(now, created_at)
        stale_after = max(1800, self.settings.autonomy_cycle_seconds * 2)
        if event.get("event_type") == "futu_quote_refresh_failed":
            return _check(
                "error",
                "Latest Futu quote refresh failed.",
                {"created_at": event.get("created_at"), "age_seconds": age, "payload": payload},
            )
        status = "warn" if age is not None and age > stale_after else "ok"
        return _check(
            status,
            "Latest Futu quote refresh is stale." if status == "warn" else "Latest Futu quote refresh is recent.",
            {"created_at": event.get("created_at"), "age_seconds": age, "stale_after_seconds": stale_after, "payload": payload},
        )

    def _check_quote_freshness(self, now: datetime) -> dict[str, Any]:
        quotes = self.store.list_quotes()
        latest = max((_aware(item.updated_at) for item in quotes), default=None)
        if not latest:
            return _check("warn", "No quote snapshots found.", {"quote_count": 0})
        age = _age_seconds(now, latest)
        freshness_limit = quote_freshness_limit_seconds(now)
        stale_quotes = [quote.symbol for quote in quotes if not quote_is_fresh(quote, now)]
        level = "error" if len(stale_quotes) == len(quotes) and age is not None and age > freshness_limit * 2 else "warn" if stale_quotes else "ok"
        return _check(
            level,
            "Quote snapshots are stale." if level != "ok" else "Quote snapshots are fresh enough.",
            {
                "quote_count": len(quotes),
                "latest_updated_at": latest.isoformat(),
                "age_seconds": age,
                "freshness_limit_seconds": freshness_limit,
                "market_session_aware": True,
                "stale_symbols": stale_quotes[:20],
                "latest_age_seconds": quote_age_seconds(next((quote for quote in quotes if _aware(quote.updated_at) == latest), None), now),
            },
        )

    def _check_fundamental_freshness(self, now: datetime) -> dict[str, Any]:
        snapshots = self.store.list_fundamentals()
        latest = max((_aware(item.updated_at) for item in snapshots), default=None)
        if not latest:
            return _check("warn", "No SEC companyfacts fundamentals snapshots found.", {"snapshot_count": 0})
        age = _age_seconds(now, latest)
        level = "error" if age is not None and age > 30 * 24 * 3600 else "warn" if age is not None and age > 7 * 24 * 3600 else "ok"
        return _check(
            level,
            "Fundamental snapshots are stale." if level != "ok" else "Fundamental snapshots are fresh enough.",
            {"snapshot_count": len(snapshots), "latest_updated_at": latest.isoformat(), "age_seconds": age},
        )

    def _check_latest_proposal_draft(self, now: datetime) -> dict[str, Any]:
        event = _latest_event(self.store, "proposal_drafts_generated")
        if not event:
            return _check("warn", "No proposal draft generation event found.", {})
        payload = _payload(event)
        created_at = _parse_dt(event.get("created_at"))
        age = _age_seconds(now, created_at)
        stale_after = max(1800, self.settings.autonomy_cycle_seconds * 2)
        level = "warn" if age is not None and age > stale_after else "ok"
        return _check(
            level,
            "Latest proposal draft run is stale." if level == "warn" else "Latest proposal draft run is recent.",
            {
                "created_at": event.get("created_at"),
                "age_seconds": age,
                "draft_count": payload.get("draft_count", 0),
                "created_count": payload.get("created_count", 0),
                "draft_min_score": payload.get("draft_min_score", self.settings.draft_min_score),
                "skipped_below_min_score": payload.get("skipped_below_min_score", 0),
                "max_score_seen": payload.get("max_score_seen", 0),
                "skipped": payload.get("skipped", []),
            },
        )

    def _check_latest_signal_run(self, now: datetime) -> dict[str, Any]:
        run = self.store.get_latest_signal_run()
        if not run:
            return _check("warn", "No paper signal run found.", {})
        age = _age_seconds(now, _aware(run.created_at))
        stale_after = max(1800, self.settings.autonomy_cycle_seconds * 2)
        level = "warn" if age is not None and age > stale_after else "ok"
        return _check(
            level,
            "Latest paper signal run is stale." if level == "warn" else "Latest paper signal run is recent.",
            {
                "signal_run_id": run.id,
                "created_at": run.created_at.isoformat(),
                "age_seconds": age,
                "stale_after_seconds": stale_after,
                "signal_count": len(run.signals),
                "max_score": run.metrics.get("max_score", 0),
                "buy_count": run.metrics.get("buy_count", 0),
                "sell_reduce_count": run.metrics.get("sell_reduce_count", 0),
                "blocked_count": run.metrics.get("blocked_count", 0),
                "watch_count": run.metrics.get("watch_count", 0),
                "summary": run.summary,
            },
        )

    def _check_signal_outcomes(self) -> dict[str, Any]:
        summary = SignalOutcomeEvaluator(self.settings, self.store).summary(limit=200)
        evaluated = int(summary.get("evaluated_window_count") or 0)
        return _check(
            "ok" if evaluated else "warn",
            "Signal outcome windows have evaluated results."
            if evaluated
            else "No evaluated signal outcome windows found; import price bars and run outcome evaluation.",
            summary,
        )

    def _check_advice_readiness(self) -> dict[str, Any]:
        readiness = AdviceReadinessService(self.settings, self.store).run()
        return _check(
            readiness["severity"],
            f"Advice readiness score is {readiness['score']}/100.",
            {
                "score": readiness["score"],
                "ok": readiness["ok"],
                "summary": readiness["summary"],
                "checks": readiness["checks"],
            },
        )

    def _check_skipped_reasons(self) -> dict[str, Any]:
        reasons: Counter[str] = Counter()
        for event_type in ("autonomy_cycle_completed", "autonomy_cycle_skipped", "proposal_drafts_generated", "signals_generated"):
            for event in self.store.list_audit_events(limit=10, event_type=event_type):
                payload = _payload(event)
                for item in payload.get("skipped", []) or []:
                    reasons[_normalize_skip_reason(str(item))] += 1
                for item in payload.get("draft_skipped", []) or []:
                    reasons[_normalize_skip_reason(str(item))] += 1
        top = [{"reason": reason, "count": count} for reason, count in reasons.most_common(8)]
        return _check("ok", "Skipped reasons summarized.", {"top_reasons": top, "total_skipped": sum(reasons.values())})

    def _check_draft_min_score(self) -> dict[str, Any]:
        event = _latest_event(self.store, "proposal_drafts_generated")
        payload = _payload(event) if event else {}
        max_score_seen = int(payload.get("max_score_seen") or 0)
        skipped_below = int(payload.get("skipped_below_min_score") or 0)
        level = "warn" if event and skipped_below and max_score_seen < self.settings.draft_min_score else "ok"
        return _check(
            level,
            "Draft threshold is filtering all observed directional scores." if level == "warn" else "Draft threshold metrics are available.",
            {
                "draft_min_score": self.settings.draft_min_score,
                "skipped_below_min_score": skipped_below,
                "max_score_seen": max_score_seen,
            },
        )

    def _check_proposal_status_mismatches(self) -> dict[str, Any]:
        mismatches = self.store.proposal_status_mismatches(limit=8)
        count = int(mismatches["count"])
        return _check(
            "warn" if count else "ok",
            "Proposal table/payload status mismatches found; reads are canonicalized to table status."
            if count
            else "Proposal table/payload statuses match.",
            mismatches,
        )

    def _futu_status(self) -> dict[str, Any]:
        if self._futu_status_cache is None:
            try:
                self._futu_status_cache = get_futu_status(self.settings)
            except Exception as exc:  # pragma: no cover - defensive local integration guard
                self._futu_status_cache = {"connected": False, "available": False, "error": str(exc), "message": str(exc)}
        return self._futu_status_cache

    def _futu_accounts(self) -> dict[str, Any]:
        if self._futu_accounts_cache is None:
            try:
                self._futu_accounts_cache = discover_futu_accounts(self.settings).as_dict()
            except Exception as exc:  # pragma: no cover - defensive local integration guard
                self._futu_accounts_cache = {
                    "account_count": 0,
                    "accounts": [],
                    "selected_account": None,
                    "candidate_acc_ids": [],
                    "selection_status": "error",
                    "error": str(exc),
                    "message": str(exc),
                }
        return self._futu_accounts_cache


def _check(status: str, message: str, metrics: dict[str, Any]) -> dict[str, Any]:
    return {"status": status, "message": message, "metrics": metrics}


def _overall_severity(checks: dict[str, dict[str, Any]]) -> str:
    statuses = {item["status"] for item in checks.values()}
    if "error" in statuses:
        return "error"
    if "warn" in statuses:
        return "warn"
    return "ok"


def _summary(checks: dict[str, dict[str, Any]]) -> dict[str, Any]:
    counts = Counter(item["status"] for item in checks.values())
    attention = [
        {"check": name, "status": check["status"], "message": check["message"]}
        for name, check in checks.items()
        if check["status"] != "ok"
    ]
    return {"counts": dict(counts), "attention": attention}


def _latest_event(store: Store, event_type: str | None = None) -> dict[str, Any] | None:
    events = store.list_audit_events(limit=1, event_type=event_type)
    return events[0] if events else None


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


def _normalize_skip_reason(reason: str) -> str:
    if ": " in reason:
        return reason.split(": ", 1)[1]
    return reason
