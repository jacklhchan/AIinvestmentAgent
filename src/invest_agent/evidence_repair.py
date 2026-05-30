from __future__ import annotations

from typing import Any

from .config import Settings
from .ir_feeds import IrFeedIngestor
from .market_news import MarketNewsIngestor
from .models import (
    PaperAdviceRequest,
    PaperAdviceStatus,
    ResearchEvidenceCreate,
    ResearchGoalCreate,
    RunCardActor,
    RunCardTriggerSource,
)
from .paper_advice import PaperAdviceFlowService
from .primary_sources import refresh_primary_sources
from .proposal_drafts import _is_primary_source, _score_news
from .research_goals import ResearchGoalService, evidence_from_news
from .sec_companyfacts import SecCompanyFactsIngestor
from .sec_edgar import SecEdgarIngestor
from .services import InvestmentService
from .store import Store


class EvidenceRepairService:
    """Controlled read-only hydration for blocked paper advice evidence gaps."""

    def __init__(self, settings: Settings, store: Store, service: InvestmentService | None = None):
        self.settings = settings
        self.store = store
        self.service = service or InvestmentService(settings, store)

    def repair_latest_blocked(self) -> dict[str, Any]:
        latest = self.store.get_latest_paper_advice_run()
        if not latest:
            return {"ok": False, "message": "No paper advice run found.", "repairs": []}
        repairs = []
        for item in latest.items:
            if item.final_status in {PaperAdviceStatus.BLOCKED, PaperAdviceStatus.RESEARCH_MORE} and item.signal_id:
                repairs.append(self.repair_signal(item.signal_id, rerun_advice=False))
        advice = PaperAdviceFlowService(self.settings, self.store, self.service).run(
            PaperAdviceRequest(),
            actor=RunCardActor.CLI,
            trigger_source=RunCardTriggerSource.MANUAL,
        )
        return {"ok": True, "latest_advice_run_id": latest.id, "repairs": repairs, "rerun_paper_advice": advice}

    def repair_signal(self, signal_id: str, *, rerun_advice: bool = True) -> dict[str, Any]:
        signal = self.store.get_signal(signal_id)
        if not signal:
            raise ValueError(f"signal not found: {signal_id}")
        symbol = signal.symbol
        goal = self._ensure_goal(signal_id)
        hydration = self._hydrate(symbol)
        evidence_added = self._write_evidence(goal.id, symbol)
        refreshed_goal = ResearchGoalService(self.store).complete_if_sufficient(goal.id)
        result = {
            "ok": True,
            "signal_id": signal_id,
            "symbol": symbol,
            "research_goal_id": refreshed_goal.id,
            "research_goal_status": refreshed_goal.status.value,
            "hydration": hydration,
            "evidence_added": evidence_added,
            "paper_only": True,
            "created_proposals": 0,
            "approved_trades": 0,
        }
        self.store.audit("evidence_repair_completed", "signal", signal_id, result)
        if rerun_advice:
            result["rerun_paper_advice"] = PaperAdviceFlowService(self.settings, self.store, self.service).run(
                PaperAdviceRequest(symbols=[symbol]),
                actor=RunCardActor.CLI,
                trigger_source=RunCardTriggerSource.MANUAL,
            )
        return result

    def _ensure_goal(self, signal_id: str):
        signal = self.store.get_signal(signal_id)
        if not signal:
            raise ValueError(f"signal not found: {signal_id}")
        if signal.research_goal_id:
            goal = self.store.get_research_goal(signal.research_goal_id)
            if goal:
                return goal
        return ResearchGoalService(self.store).create_goal(
            ResearchGoalCreate(
                symbol=signal.symbol,
                objective=f"Repair missing evidence for paper signal {signal.id}; remain research-only.",
                claims=[f"Evidence repair should verify whether {signal.symbol} {signal.side.value} has enough support."],
                criteria=[
                    "At least one recent directional market/news evidence row is attached.",
                    "At least one verified primary-source or SEC fundamentals evidence row is attached.",
                    "No proposal, approval, or trade is created by evidence repair.",
                ],
            )
        )

    def _hydrate(self, symbol: str) -> dict[str, Any]:
        results: dict[str, Any] = {}
        results["news"] = MarketNewsIngestor(self.settings, self.store).refresh_news(symbols=[symbol], max_symbols=1)
        try:
            results["primary_sources"] = refresh_primary_sources(
                SecEdgarIngestor(self.settings, self.store),
                IrFeedIngestor(self.settings, self.store),
                symbols=[symbol],
                max_symbols=1,
                max_filings=2,
            )
        except Exception as exc:
            results["primary_sources_error"] = str(exc)
        try:
            results["fundamentals"] = SecCompanyFactsIngestor(self.settings, self.store).refresh_fundamentals(
                symbols=[symbol],
                max_symbols=1,
            )
        except Exception as exc:
            results["fundamentals_error"] = str(exc)
        return _json_summary(results)

    def _write_evidence(self, goal_id: str, symbol: str) -> dict[str, Any]:
        service = ResearchGoalService(self.store)
        added = 0
        added_ids: list[str] = []
        for item in self.store.list_news(symbol=symbol, limit=20):
            if _score_news(item) == 0 and not _is_primary_source(item):
                continue
            evidence = service.add_evidence(
                evidence_from_news(
                    goal_id=goal_id,
                    symbol=symbol,
                    source_type=item.source or "market-news",
                    title=item.title,
                    source_uri=item.url,
                    published_at=item.published_at,
                    verified=_is_primary_source(item),
                ),
                trusted_source=_is_primary_source(item),
            )
            added += 1
            added_ids.append(evidence.id)
        fundamentals = self.store.get_fundamentals(symbol)
        if fundamentals:
            text = f"SEC companyfacts snapshot for {symbol}: {', '.join(sorted(fundamentals.metrics)[:6])}"
            evidence = service.add_evidence(
                ResearchEvidenceCreate(
                    goal_id=goal_id,
                    symbol=symbol,
                    source_type="sec-companyfacts",
                    text=text,
                    data_as_of=fundamentals.updated_at,
                    freshness_status="latest-local",
                    verification_status="verified",
                    source_verified=True,
                    added_via="evidence-repair",
                    confidence=0.72,
                    caveat="Local SEC companyfacts snapshot; review interpretation before any paper proposal.",
                ),
                trusted_source=True,
            )
            added += 1
            added_ids.append(evidence.id)
        return {"count": added, "evidence_ids": added_ids[:20]}


def _json_summary(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if isinstance(value, dict):
        return {key: _json_summary(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_summary(item) for item in value]
    return value
