from __future__ import annotations

import signal
import time
from datetime import datetime, timedelta, timezone
from typing import Any

from .advisor_orchestrator import AdvisorOrchestrator, advisor_schedule_context, market_session_date
from .config import Settings
from .models import AdvisorFullBriefType, RunCardActor, utc_now
from .store import Store


class AdvisorSchedulerRunner:
    def __init__(self, settings: Settings, store: Store):
        self.settings = settings
        self.store = store
        self._stop = False

    def run_once(self, *, now: datetime | None = None) -> dict[str, Any]:
        now = _aware_utc(now or utc_now())
        orchestrator = AdvisorOrchestrator(self.store, settings=self.settings)
        result: dict[str, Any] = {
            "now": now.isoformat(),
            "ran": [],
            "skipped": [],
            "paper_only": self.settings.is_paper,
        }
        if self._hourly_pulse_due(now):
            pulse = orchestrator.run_hourly_pulse(now=now, actor=RunCardActor.SCHEDULER)
            result["ran"].append({"job": "hourly_pulse", "id": pulse.id, "severity": pulse.severity.value})
        else:
            result["skipped"].append({"job": "hourly_pulse", "reason": "not due"})

        for brief_type in (AdvisorFullBriefType.PRE_MARKET, AdvisorFullBriefType.POST_CLOSE):
            due, reason = self._brief_due(brief_type, now)
            if due:
                brief = orchestrator.run_full_advisor_brief(brief_type, now=now, actor=RunCardActor.SCHEDULER)
                result["ran"].append({"job": brief_type.value, "id": brief.id, "session": brief.market_session_date})
            else:
                result["skipped"].append({"job": brief_type.value, "reason": reason})
        self.store.audit("advisor_scheduler_checked", "automation", "hermes-advisor", result)
        return result

    def run_forever(self, *, poll_seconds: int = 60) -> None:
        _install_signal_handlers(self)
        while not self._stop:
            self.run_once()
            self._sleep_interruptibly(max(15, poll_seconds))

    def request_stop(self) -> None:
        self._stop = True

    def _hourly_pulse_due(self, now: datetime) -> bool:
        pulses = self.store.list_advisor_pulses(limit=1)
        if not pulses:
            return True
        return _aware_utc(pulses[0].created_at) <= now - timedelta(hours=1)

    def _brief_due(self, brief_type: AdvisorFullBriefType, now: datetime) -> tuple[bool, str]:
        session = market_session_date(now, brief_type)
        schedule = advisor_schedule_context(session)
        schedule_key = "pre_market_brief_sgt" if brief_type == AdvisorFullBriefType.PRE_MARKET else "post_close_brief_sgt"
        scheduled_at = datetime.fromisoformat(schedule.as_dict()[schedule_key]).astimezone(timezone.utc)
        if now < scheduled_at:
            return False, "before scheduled window"
        if now >= scheduled_at + timedelta(minutes=30):
            return False, "after scheduled window"
        existing = [
            item
            for item in self.store.list_advisor_briefs(brief_type=brief_type.value, limit=20)
            if item.market_session_date == session.isoformat()
        ]
        if existing:
            return False, "already created for session"
        return True, "due"

    def _sleep_interruptibly(self, seconds: int) -> None:
        deadline = time.monotonic() + seconds
        while not self._stop and time.monotonic() < deadline:
            time.sleep(min(1.0, deadline - time.monotonic()))


def _install_signal_handlers(runner: AdvisorSchedulerRunner) -> None:
    def _handler(_signum, _frame) -> None:
        runner.request_stop()

    signal.signal(signal.SIGINT, _handler)
    signal.signal(signal.SIGTERM, _handler)


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
