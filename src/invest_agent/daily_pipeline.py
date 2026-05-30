from __future__ import annotations

from typing import Any

from .advice_readiness import AdviceReadinessService
from .committee_reviews import CommitteeReviewService
from .config import Settings
from .daily_briefs import DailyBriefService
from .futu_adapter import refresh_futu_readonly
from .market_context import MarketContextService
from .market_news import MarketNewsIngestor
from .models import (
    CommitteeReviewRunRequest,
    DailyBriefRunRequest,
    DailyBriefType,
    QuoteHistoryBatchRefreshRequest,
    RunCardActor,
    RunCardTriggerSource,
    SignalRunRequest,
    SignalSide,
    SignalSource,
)
from .quote_history import QuoteHistoryService
from .sec_companyfacts import SecCompanyFactsIngestor
from .signal_outcomes import SignalOutcomeEvaluator
from .signals import SignalEngine
from .store import Store


class DailySignalPipeline:
    def __init__(self, settings: Settings, store: Store):
        self.settings = settings
        self.store = store

    def pre_market(self) -> dict[str, Any]:
        steps: list[dict[str, Any]] = []
        steps.append(self._step("futu_readonly", lambda: refresh_futu_readonly(self.settings, self.store).as_dict()))
        steps.append(self._step("market_news", lambda: MarketNewsIngestor(self.settings, self.store).refresh_news()))
        steps.append(self._step("market_context", lambda: MarketContextService(self.settings, self.store).refresh_news()))
        signal_result = SignalEngine(self.settings, self.store).run(
            SignalRunRequest(source=SignalSource.CLI),
            actor=RunCardActor.CLI,
            trigger_source=RunCardTriggerSource.SCHEDULED,
        )
        steps.append({"name": "signals", "status": "ok", "result": signal_result.metrics})
        readiness = AdviceReadinessService(self.settings, self.store).run()
        brief = DailyBriefService(self.settings, self.store).run(
            DailyBriefRunRequest(brief_type=DailyBriefType.MORNING),
            actor=RunCardActor.CLI,
        )
        result = {"pipeline": "daily-pre-market", "steps": steps, "signals": signal_result.metrics, "readiness": readiness, "brief": brief}
        self.store.audit("daily_pipeline_completed", "daily_pipeline", "pre_market", _json_summary(result))
        return result

    def post_close(self) -> dict[str, Any]:
        steps: list[dict[str, Any]] = []
        steps.append(self._step("futu_readonly", lambda: refresh_futu_readonly(self.settings, self.store).as_dict()))
        steps.append(self._step("market_news", lambda: MarketNewsIngestor(self.settings, self.store).refresh_news()))
        steps.append(self._step("market_context", lambda: MarketContextService(self.settings, self.store).refresh_news()))
        steps.append(self._step("fundamentals", lambda: SecCompanyFactsIngestor(self.settings, self.store).refresh_fundamentals()))
        steps.append(
            self._step(
                "quote_history_batch",
                lambda: QuoteHistoryService(self.store, self.settings).refresh_batch(
                    QuoteHistoryBatchRefreshRequest(symbols="watchlist,positions,benchmarks,recent_signals", source="futu"),
                    actor=RunCardActor.CLI,
                ),
            )
        )
        signal_result = SignalEngine(self.settings, self.store).run(
            SignalRunRequest(source=SignalSource.CLI),
            actor=RunCardActor.CLI,
            trigger_source=RunCardTriggerSource.SCHEDULED,
        )
        steps.append({"name": "signals", "status": "ok", "result": signal_result.metrics})
        committee_reviews = []
        for signal in [item for item in signal_result.signals if item.side in _COMMITTEE_SIDES][:3]:
            review = CommitteeReviewService(self.store, settings=self.settings).run_review(
                CommitteeReviewRunRequest(
                    topic=f"Post-close committee review for {signal.side.value} {signal.symbol} score {signal.score}",
                    symbols=[signal.symbol],
                    research_goal_id=signal.research_goal_id,
                    hydrate_missing_data=True,
                ),
                actor=RunCardActor.CLI,
            )
            committee_reviews.append(review)
        outcomes = SignalOutcomeEvaluator(self.settings, self.store).evaluate(limit=200)
        readiness = AdviceReadinessService(self.settings, self.store).run()
        brief = DailyBriefService(self.settings, self.store).run(
            DailyBriefRunRequest(brief_type=DailyBriefType.CLOSE),
            actor=RunCardActor.CLI,
        )
        result = {
            "pipeline": "daily-post-close",
            "steps": steps,
            "signals": signal_result.metrics,
            "committee_reviews": committee_reviews,
            "outcomes": outcomes,
            "readiness": readiness,
            "brief": brief,
        }
        self.store.audit("daily_pipeline_completed", "daily_pipeline", "post_close", _json_summary(result))
        return result

    def _step(self, name: str, fn) -> dict[str, Any]:
        try:
            result = fn()
            return {"name": name, "status": "ok", "result": _json_summary(result)}
        except Exception as exc:
            return {"name": name, "status": "error", "error": str(exc)}


_COMMITTEE_SIDES = {SignalSide.BUY_SIGNAL, SignalSide.ADD_SIGNAL, SignalSide.SELL_SIGNAL, SignalSide.REDUCE_SIGNAL, SignalSide.BLOCKED}


def _json_summary(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if isinstance(value, dict):
        return {key: _json_summary(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_summary(item) for item in value]
    return value
