from __future__ import annotations

from collections import Counter
from typing import Any

from .advice_readiness import AdviceReadinessService
from .config import Settings
from .investor_committee import InvestorFrameworkCommitteeService
from .models import (
    InvestorCommitteeRun,
    PaperAdviceItem,
    PaperAdviceRequest,
    PaperAdviceRun,
    PaperAdviceStatus,
    RunCardActor,
    RunCardTriggerSource,
    RunCardType,
    Signal,
    SignalRunRequest,
    SignalSide,
    SignalSource,
    SignalStatus,
    utc_now,
)
from .run_cards import RunCardService
from .services import InvestmentService
from .signals import SignalEngine
from .promotion_gate import PromotionGateService, directional_threshold
from .store import Store


PAPER_ADVICE_RULE_VERSION = "paper_advice_flow_v1"
READINESS_THRESHOLD = 75.0
ADVICE_SIGNAL_SIDES = {
    SignalSide.BUY_SIGNAL,
    SignalSide.ADD_SIGNAL,
    SignalSide.SELL_SIGNAL,
    SignalSide.REDUCE_SIGNAL,
    SignalSide.BLOCKED,
}


class PaperAdviceFlowService:
    def __init__(self, settings: Settings, store: Store, service: InvestmentService | None = None):
        self.settings = settings
        self.store = store
        self.service = service or InvestmentService(settings, store)

    def run(
        self,
        request: PaperAdviceRequest | None = None,
        *,
        actor: RunCardActor | str = RunCardActor.CLI,
        trigger_source: RunCardTriggerSource | str = RunCardTriggerSource.MANUAL,
    ) -> PaperAdviceRun:
        request = request or PaperAdviceRequest()
        signal_result = SignalEngine(self.settings, self.store, self.service).run(
            SignalRunRequest(
                symbols=request.symbols,
                horizon=request.horizon,
                max_signals=request.max_signals,
                source=_source_for_actor(actor),
            ),
            actor=actor,
            trigger_source=trigger_source,
        )
        latest_run = self.store.get_latest_signal_run() or signal_result.run
        signals = self._select_signals(latest_run.signals)
        readiness_service = AdviceReadinessService(self.settings, self.store)
        readiness = readiness_service.run()
        readiness_score = float(readiness.get("score") or 0.0)
        run_card = RunCardService(self.store).start_run(
            RunCardType.PAPER_ADVICE,
            title="Committee-Gated Paper Advice",
            actor=actor,
            trigger_source=trigger_source,
            rule_version=PAPER_ADVICE_RULE_VERSION,
            inputs=request.model_dump(mode="json"),
            dataset={
                "signal_run_id": latest_run.id,
                "readiness": readiness,
                "selected_signal_ids": [signal.id for signal in signals],
            },
            assumptions={
                "paper_only": self.settings.is_paper,
                "human_approval_required": True,
                "committee_required_before_promotion": True,
                "live_orders_disabled": True,
            },
        )
        try:
            run = PaperAdviceRun(
                signal_run_id=latest_run.id,
                readiness_score=readiness_score,
                readiness_ok=readiness_score >= READINESS_THRESHOLD,
                run_card_id=run_card.id,
            )
            if readiness_score < READINESS_THRESHOLD:
                items = self._blocked_for_readiness(run.id, signals, readiness)
            else:
                committee_service = InvestorFrameworkCommitteeService(self.settings, self.store)
                items = []
                for signal in signals:
                    committee = committee_service.run_for_signal(signal.id)
                    symbol_readiness = readiness_service.run_for_symbol(signal.symbol, signal)
                    items.append(self._item_from_committee(run.id, signal, committee, readiness_score, symbol_readiness))
            if not items and readiness_score >= READINESS_THRESHOLD:
                items = [
                    PaperAdviceItem(
                        run_id=run.id,
                        readiness_score=readiness_score,
                        final_status=PaperAdviceStatus.WATCH,
                        suggested_user_action="No BUY/SELL/ADD/REDUCE candidate cleared the signal selection layer.",
                    )
                ]
            run = run.model_copy(update={"items": items, "summary": _summary(items, readiness_score), "metrics": _metrics(items)})
            stored = self.store.create_paper_advice_run(run)
            RunCardService(self.store).complete_run(
                run_card.id,
                metrics=stored.metrics,
                warnings=[warning for item in stored.items for warning in item.vetoes + item.missing_evidence][:12],
                outputs={
                    "paper_advice_run_id": stored.id,
                    "summary": stored.summary,
                    "status_counts": stored.metrics.get("status_counts", {}),
                },
                dataset={
                    "readiness": readiness,
                    "items": [item.model_dump(mode="json") for item in stored.items],
                },
            )
            return stored
        except Exception as exc:
            RunCardService(self.store).fail_run(run_card.id, error=str(exc), write_artifacts=True)
            raise

    def latest(self) -> PaperAdviceRun | None:
        return self.store.get_latest_paper_advice_run()

    def _select_signals(self, signals: list[Signal]) -> list[Signal]:
        selected = [
            signal
            for signal in signals
            if signal.status == SignalStatus.ACTIVE and signal.side in ADVICE_SIGNAL_SIDES
        ]
        selected.sort(key=lambda item: (_side_rank(item.side), item.score, item.confidence), reverse=True)
        return selected[: self.settings.signal_max_per_run]

    def _blocked_for_readiness(self, run_id: str, signals: list[Signal], readiness: dict[str, Any]) -> list[PaperAdviceItem]:
        failed = [
            f"{name}: {check.get('message')}"
            for name, check in (readiness.get("checks") or {}).items()
            if check.get("status") != "ok"
        ]
        selected = signals or [None]
        items = []
        readiness_by_symbol = readiness.get("by_symbol") or {}
        for signal in selected:
            symbol_readiness = (readiness_by_symbol.get(signal.symbol) if signal else {}) or {}
            items.append(PaperAdviceItem(
                run_id=run_id,
                signal_id=signal.id if signal else None,
                symbol=signal.symbol if signal else None,
                side=signal.side if signal else None,
                readiness_score=float(readiness.get("score") or 0.0),
                base_score=signal.score if signal else None,
                adjusted_score=None,
                final_status=PaperAdviceStatus.BLOCKED,
                committee_stance="not_run_readiness_below_threshold",
                committee_blocked=True,
                vetoes=["advice_readiness_below_75"],
                missing_evidence=failed[:8],
                gates=signal.gates if signal else {},
                symbol_readiness=symbol_readiness,
                suggested_user_action="Supporting data is insufficient; refresh data and rerun paper advice before treating BUY/SELL as actionable.",
                promotable=False,
            ))
        return items

    def _item_from_committee(
        self,
        run_id: str,
        signal: Signal,
        committee: InvestorCommitteeRun,
        readiness_score: float,
        symbol_readiness: dict[str, Any] | None = None,
    ) -> PaperAdviceItem:
        status = _final_status(signal, committee, self.settings)
        return PaperAdviceItem(
            run_id=run_id,
            signal_id=signal.id,
            committee_run_id=committee.id,
            symbol=signal.symbol,
            side=signal.side,
            readiness_score=readiness_score,
            base_score=signal.score,
            adjusted_score=committee.committee_adjusted_score,
            final_status=status,
            committee_stance=committee.final_stance,
            committee_blocked=committee.committee_blocked,
            vetoes=committee.vetoes,
            missing_evidence=committee.missing_evidence,
            gates=signal.gates,
            symbol_readiness=symbol_readiness or {},
            suggested_user_action=_suggested_user_action(status, committee),
            promotable=PromotionGateService(self.settings, self.store).evaluate(signal, committee)["ok"],
        )


def _source_for_actor(actor: RunCardActor | str) -> SignalSource:
    value = actor.value if isinstance(actor, RunCardActor) else str(actor)
    if value == RunCardActor.API.value:
        return SignalSource.API
    if value == RunCardActor.MCP.value:
        return SignalSource.MANUAL_RUN
    if value == RunCardActor.SCHEDULER.value:
        return SignalSource.AUTONOMY
    return SignalSource.CLI


def _side_rank(side: SignalSide) -> int:
    return {
        SignalSide.BUY_SIGNAL: 8,
        SignalSide.ADD_SIGNAL: 7,
        SignalSide.SELL_SIGNAL: 7,
        SignalSide.REDUCE_SIGNAL: 7,
        SignalSide.BLOCKED: 6,
    }.get(side, 0)


def _final_status(signal: Signal, committee: InvestorCommitteeRun, settings: Settings) -> PaperAdviceStatus:
    if committee.committee_blocked or committee.vetoes:
        return PaperAdviceStatus.BLOCKED
    if signal.side == SignalSide.BLOCKED or signal.gates.get("blocking_reasons"):
        return PaperAdviceStatus.BLOCKED
    if committee.final_stance in {"blocked", "oppose"}:
        return PaperAdviceStatus.BLOCKED
    if committee.final_stance == "research_more":
        return PaperAdviceStatus.RESEARCH_MORE
    if committee.final_stance == "watch":
        return PaperAdviceStatus.WATCH
    if committee.committee_adjusted_score < _directional_threshold(settings, signal):
        return PaperAdviceStatus.WATCH
    if committee.final_stance == "support_with_caution":
        return PaperAdviceStatus.SUPPORT_WITH_CAUTION
    return PaperAdviceStatus.ACTIONABLE_PAPER


def _directional_threshold(settings: Settings, signal: Signal) -> int:
    return directional_threshold(settings, signal)


def _suggested_user_action(status: PaperAdviceStatus, committee: InvestorCommitteeRun) -> str:
    if status == PaperAdviceStatus.ACTIONABLE_PAPER:
        return "Eligible for user-reviewed paper proposal promotion; human approval is still required."
    if status == PaperAdviceStatus.SUPPORT_WITH_CAUTION:
        return "Paper advice is support-with-caution; promote only after reviewing committee missing evidence and veto list."
    if status == PaperAdviceStatus.BLOCKED:
        return "Do not promote; resolve committee vetoes, signal gates, sizing, catalyst, or evidence blockers first."
    if status == PaperAdviceStatus.RESEARCH_MORE:
        return "Add missing evidence and rerun the signal plus committee workflow."
    return "Keep watching; score or committee stance is not strong enough for paper action."


def _summary(items: list[PaperAdviceItem], readiness_score: float) -> str:
    counts = Counter(item.final_status.value for item in items)
    if readiness_score < READINESS_THRESHOLD:
        return f"Paper advice blocked because readiness is {readiness_score:.1f}/100."
    if not items:
        return "No paper advice items generated."
    return ", ".join(f"{status}: {count}" for status, count in sorted(counts.items()))


def _metrics(items: list[PaperAdviceItem]) -> dict[str, Any]:
    counts = Counter(item.final_status.value for item in items)
    return {
        "item_count": len(items),
        "promotable_count": sum(1 for item in items if item.promotable),
        "status_counts": dict(counts),
        "veto_count": sum(len(item.vetoes) for item in items),
        "missing_evidence_count": sum(len(item.missing_evidence) for item in items),
    }
