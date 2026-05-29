from __future__ import annotations

import errno
import json
import os
import signal
import time
from contextlib import AbstractContextManager
from datetime import timedelta
from pathlib import Path
from typing import Any, Callable

import fcntl
from fastapi import HTTPException

from .catalysts import CatalystCalendarService
from .config import Settings
from .futu_adapter import FutuIntegrationError, refresh_futu_readonly
from .ir_feeds import IrFeedIngestor
from .market_context import MarketContextService
from .market_news import MarketNewsIngestor, external_ticker
from .models import AutomationRunResult, AutomationStepResult, Proposal, ProposalDraft, utc_now
from .primary_sources import refresh_primary_sources
from .proposal_drafts import ProposalDraftEngine
from .sec_companyfacts import SecCompanyFactsIngestor
from .sec_edgar import SecEdgarIngestor
from .services import InvestmentService
from .store import Store


class SafeAutonomyRunner:
    def __init__(self, settings: Settings, store: Store, service: InvestmentService | None = None):
        self.settings = settings
        self.store = store
        self.service = service or InvestmentService(settings, store)
        self._stop = False
        self._cycle_number = 0

    def run_cycle(
        self,
        *,
        mode: str = "once",
        create_proposals: bool | None = None,
        include_slow_sources: bool = True,
        cycle_number: int | None = None,
    ) -> AutomationRunResult:
        started = utc_now()
        cycle = cycle_number or self._cycle_number + 1
        create = self.settings.autonomy_create_proposals if create_proposals is None else create_proposals
        lock_path = _safe_autonomy_lock_path(self.settings)
        with _SingleFlightLock(lock_path) as lock:
            if not lock.acquired:
                return self._skipped_for_single_flight(
                    started=started,
                    mode=mode,
                    cycle_number=cycle,
                    create_proposals=create,
                    lock_path=lock_path,
                    holder=lock.holder,
                )
            return self._run_cycle_locked(
                started=started,
                mode=mode,
                create_proposals=create,
                include_slow_sources=include_slow_sources,
                cycle_number=cycle,
            )

    def _run_cycle_locked(
        self,
        *,
        started,
        mode: str,
        create_proposals: bool,
        include_slow_sources: bool,
        cycle_number: int,
    ) -> AutomationRunResult:
        result = AutomationRunResult(mode=mode, started_at=started, cycle_number=cycle_number)
        self.store.audit(
            "autonomy_cycle_started",
            "automation",
            "safe-autonomy",
            {"mode": mode, "cycle_number": cycle_number, "create_proposals": create_proposals},
        )

        result.steps.append(self._run_step("futu_readonly", self._refresh_futu))
        result.steps.append(self._run_step("market_news", self._refresh_news))
        if include_slow_sources:
            result.steps.append(self._run_step("primary_sources", self._refresh_primary_sources))
            result.steps.append(self._run_step("sec_companyfacts", self._refresh_fundamentals))
        else:
            result.steps.append(_skipped_step("primary_sources", "not due in this cycle"))
            result.steps.append(_skipped_step("sec_companyfacts", "not due in this cycle"))

        result.steps.append(self._run_step("catalyst_calendar", self._review_catalysts))
        draft_step, created, skipped = self._draft_and_optionally_create(create_proposals)
        result.steps.append(draft_step)
        result.created_proposals = created
        result.skipped = skipped
        result.errors = [step.message for step in result.steps if step.status == "error"]
        result.finished_at = utc_now()

        self.store.audit(
            "autonomy_cycle_completed",
            "automation",
            "safe-autonomy",
            _automation_payload(result),
        )
        return result

    def _skipped_for_single_flight(
        self,
        *,
        started,
        mode: str,
        cycle_number: int,
        create_proposals: bool,
        lock_path: Path,
        holder: str,
    ) -> AutomationRunResult:
        message = "safe autonomy cycle already running"
        finished = utc_now()
        step = AutomationStepResult(
            name="single_flight",
            status="skipped",
            started_at=started,
            finished_at=finished,
            message=message,
            metrics={"lock_path": str(lock_path), "holder": holder},
        )
        result = AutomationRunResult(
            mode=mode,
            started_at=started,
            finished_at=finished,
            cycle_number=cycle_number,
            skipped=[message],
            steps=[step],
        )
        self.store.audit(
            "autonomy_cycle_skipped",
            "automation",
            "safe-autonomy",
            {
                **_automation_payload(result),
                "reason": "single_flight",
                "create_proposals": create_proposals,
            },
        )
        return result

    def run_forever(self) -> None:
        _install_signal_handlers(self)
        while not self._stop:
            self._cycle_number += 1
            include_slow = self._slow_sources_due(self._cycle_number)
            self.run_cycle(mode="loop", include_slow_sources=include_slow, cycle_number=self._cycle_number)
            self._sleep_interruptibly(max(30, self.settings.autonomy_cycle_seconds))

    def request_stop(self) -> None:
        self._stop = True

    def _slow_sources_due(self, cycle_number: int) -> bool:
        primary_due = cycle_number == 1 or cycle_number % max(1, self.settings.autonomy_primary_every_cycles) == 0
        fundamentals_due = cycle_number == 1 or cycle_number % max(1, self.settings.autonomy_fundamentals_every_cycles) == 0
        return primary_due or fundamentals_due

    def _sleep_interruptibly(self, seconds: int) -> None:
        deadline = time.monotonic() + seconds
        while not self._stop and time.monotonic() < deadline:
            time.sleep(min(1.0, deadline - time.monotonic()))

    def _run_step(self, name: str, callback: Callable[[], dict[str, Any]]) -> AutomationStepResult:
        started = utc_now()
        try:
            metrics = callback()
            status = str(metrics.pop("status", "ok"))
            message = str(metrics.pop("message", ""))
            return AutomationStepResult(
                name=name,
                status=status,
                started_at=started,
                finished_at=utc_now(),
                message=message,
                metrics=metrics,
            )
        except Exception as exc:  # pragma: no cover - defensive runtime guard
            return AutomationStepResult(
                name=name,
                status="error",
                started_at=started,
                finished_at=utc_now(),
                message=str(exc),
            )

    def _refresh_futu(self) -> dict[str, Any]:
        if not self.settings.autonomy_refresh_futu:
            return {"status": "skipped", "message": "disabled by settings"}
        if not self.settings.futu_read_enabled:
            return {"status": "skipped", "message": "FUTU_READ_ENABLED is false"}
        try:
            result = refresh_futu_readonly(self.settings, self.store)
        except FutuIntegrationError as exc:
            return {"status": "error", "message": str(exc)}
        return {
            "position_count": result.position_count,
            "quote_count": result.quote_count,
            "source": result.source,
        }

    def _refresh_news(self) -> dict[str, Any]:
        if not self.settings.autonomy_refresh_news:
            return {"status": "skipped", "message": "disabled by settings"}
        result = MarketNewsIngestor(self.settings, self.store).refresh_news()
        market_result = MarketContextService(self.settings, self.store).refresh_news()
        errors = [*result.errors, *market_result.errors]
        return {
            "stored_count": result.stored_count + market_result.stored_count,
            "total_count": result.total_count + market_result.total_count,
            "symbols": result.symbols,
            "market_context_symbols": market_result.symbols,
            "sources": _merge_counts(result.sources, market_result.sources),
            "errors": errors,
            "status": "error" if errors and result.stored_count + market_result.stored_count == 0 else "ok",
            "message": "; ".join(errors[:3]),
        }

    def _refresh_primary_sources(self) -> dict[str, Any]:
        if not self.settings.autonomy_refresh_primary_sources:
            return {"status": "skipped", "message": "disabled by settings"}
        result = refresh_primary_sources(
            SecEdgarIngestor(self.settings, self.store),
            IrFeedIngestor(self.settings, self.store),
        )
        return {
            "stored_count": result.stored_count,
            "total_count": result.total_count,
            "symbols": result.symbols,
            "sources": result.sources,
            "errors": result.errors,
            "status": "error" if result.errors and result.stored_count == 0 else "ok",
            "message": "; ".join(result.errors[:3]),
        }

    def _refresh_fundamentals(self) -> dict[str, Any]:
        if not self.settings.autonomy_refresh_fundamentals:
            return {"status": "skipped", "message": "disabled by settings"}
        result = SecCompanyFactsIngestor(self.settings, self.store).refresh_fundamentals()
        return {
            "stored_count": result.stored_count,
            "total_count": result.total_count,
            "symbols": result.symbols,
            "errors": result.errors,
            "status": "error" if result.errors and result.stored_count == 0 else "ok",
            "message": "; ".join(result.errors[:3]),
        }

    def _draft_and_optionally_create(self, create_proposals: bool) -> tuple[AutomationStepResult, list[Proposal], list[str]]:
        started = utc_now()
        skipped: list[str] = []
        created: list[Proposal] = []
        draft_result = ProposalDraftEngine(self.settings, self.store, self.service).draft_from_watchlist(create_proposals=False)
        if create_proposals:
            for draft in draft_result.drafts:
                if not draft.evidence_gate_passed:
                    skipped.append(f"{draft.symbol} {draft.side.value}: research evidence gate insufficient")
                    continue
                if self._is_in_cooldown(draft):
                    skipped.append(f"{draft.symbol} {draft.side.value}: proposal cooldown active")
                    continue
                try:
                    created.append(self.service.create_proposal(_proposal_request_from_draft(draft)))
                except HTTPException as exc:
                    skipped.append(f"{draft.symbol} {draft.side.value}: {exc.detail}")
        else:
            skipped.append("proposal creation disabled; drafts kept as research output")

        metrics = {
            "draft_count": len(draft_result.drafts),
            "created_count": len(created),
            "watchlist": draft_result.watchlist,
            "draft_skipped": draft_result.skipped,
            "draft_min_score": draft_result.draft_min_score,
            "skipped_below_min_score": draft_result.skipped_below_min_score,
            "max_score_seen": draft_result.max_score_seen,
        }
        return (
            AutomationStepResult(
                name="proposal_drafts",
                status="ok",
                started_at=started,
                finished_at=utc_now(),
                message=f"{len(draft_result.drafts)} drafts, {len(created)} proposals created",
                metrics=metrics,
            ),
            created,
            [*draft_result.skipped, *skipped],
        )

    def _is_in_cooldown(self, draft: ProposalDraft) -> bool:
        cooldown_start = utc_now() - timedelta(minutes=max(1, self.settings.autonomy_proposal_cooldown_minutes))
        ticker = external_ticker(draft.symbol)
        for proposal in self.store.list_proposals(limit=200):
            if proposal.created_at < cooldown_start:
                continue
            if external_ticker(proposal.symbol) == ticker and proposal.side == draft.side:
                return True
        return False

    def _review_catalysts(self) -> dict[str, Any]:
        service = CatalystCalendarService(self.store)
        upcoming = service.list_upcoming(days=14, limit=50)
        created_goal_ids = service.create_post_event_goals_for_completed(limit=20)
        high_impact = [item for item in upcoming if item.expected_impact == "high"]
        return {
            "upcoming_count": len(upcoming),
            "high_impact_count": len(high_impact),
            "post_event_goal_count": len(created_goal_ids),
            "post_event_goal_ids": created_goal_ids,
        }


def autonomy_status(settings: Settings, store: Store) -> dict[str, Any]:
    last_run = store.list_audit_events(limit=1, event_type="autonomy_cycle_completed")
    last_skipped = store.list_audit_events(limit=1, event_type="autonomy_cycle_skipped")
    last_draft = store.list_audit_events(limit=1, event_type="proposal_drafts_generated")
    last_draft_payload = _decode_audit_payload(last_draft[0]) if last_draft else None
    return {
        "mode": "paper" if settings.is_paper else "live-requested",
        "paper_only": settings.is_paper,
        "cycle_seconds": settings.autonomy_cycle_seconds,
        "create_proposals": settings.autonomy_create_proposals,
        "proposal_cooldown_minutes": settings.autonomy_proposal_cooldown_minutes,
        "draft_min_score": settings.draft_min_score,
        "lock_path": str(_safe_autonomy_lock_path(settings)),
        "refresh": {
            "futu": settings.autonomy_refresh_futu and settings.futu_read_enabled,
            "news": settings.autonomy_refresh_news,
            "primary_sources": settings.autonomy_refresh_primary_sources,
            "fundamentals": settings.autonomy_refresh_fundamentals,
        },
        "last_run": _decode_audit_payload(last_run[0]) if last_run else None,
        "last_skipped": _decode_audit_payload(last_skipped[0]) if last_skipped else None,
        "latest_draft_metrics": {
            "draft_min_score": settings.draft_min_score,
            "skipped_below_min_score": (last_draft_payload or {}).get("skipped_below_min_score", 0),
            "max_score_seen": (last_draft_payload or {}).get("max_score_seen", 0),
            "draft_count": (last_draft_payload or {}).get("draft_count", 0),
            "created_count": (last_draft_payload or {}).get("created_count", 0),
        },
    }


def _proposal_request_from_draft(draft: ProposalDraft):
    from .models import ProposalCreate

    return ProposalCreate(
        symbol=draft.symbol,
        side=draft.side,
        qty=draft.qty,
        limit_price=draft.limit_price,
        thesis=draft.thesis,
        trigger=f"Autonomy cycle: {draft.trigger}",
        confidence=draft.confidence,
        evidence=draft.evidence,
        counter_evidence=draft.counter_evidence,
        research_goal_id=draft.research_goal_id,
        thesis_id=draft.thesis_id,
    )


def _skipped_step(name: str, message: str) -> AutomationStepResult:
    now = utc_now()
    return AutomationStepResult(name=name, status="skipped", started_at=now, finished_at=now, message=message)


def _automation_payload(result: AutomationRunResult) -> dict[str, Any]:
    payload = result.model_dump(mode="json", exclude={"created_proposals"})
    payload["created_count"] = len(result.created_proposals)
    payload["created_proposal_ids"] = [proposal.id for proposal in result.created_proposals]
    return payload


def _merge_counts(*sources: dict[str, int]) -> dict[str, int]:
    merged: dict[str, int] = {}
    for source in sources:
        for key, value in source.items():
            merged[key] = merged.get(key, 0) + value
    return merged


def _safe_autonomy_lock_path(settings: Settings) -> Path:
    return settings.db_path.parent / "safe_autonomy.lock"


class _SingleFlightLock(AbstractContextManager["_SingleFlightLock"]):
    def __init__(self, path: Path):
        self.path = path
        self.acquired = False
        self.holder = ""
        self._file = None

    def __enter__(self) -> "_SingleFlightLock":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._file = self.path.open("a+", encoding="utf-8")
        try:
            fcntl.flock(self._file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            if exc.errno not in {errno.EACCES, errno.EAGAIN}:
                raise
            self._file.seek(0)
            self.holder = self._file.read().strip()
            return self
        self.acquired = True
        self._file.seek(0)
        self._file.truncate()
        self._file.write(
            json.dumps(
                {
                    "pid": os.getpid(),
                    "started_at": utc_now().isoformat(),
                }
            )
        )
        self._file.flush()
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        if self._file is None:
            return
        try:
            if self.acquired:
                fcntl.flock(self._file.fileno(), fcntl.LOCK_UN)
        finally:
            self._file.close()
            self._file = None


def _decode_audit_payload(event: dict[str, Any]) -> dict[str, Any]:
    payload = event.get("payload")
    if isinstance(payload, str):
        try:
            return json.loads(payload)
        except json.JSONDecodeError:
            return {"raw": payload}
    if isinstance(payload, dict):
        return payload
    return {}


def _install_signal_handlers(runner: SafeAutonomyRunner) -> None:
    def stop(_signum, _frame):
        runner.request_stop()

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
