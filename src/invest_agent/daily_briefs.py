from __future__ import annotations

from .advisor import AdvisorService
from .config import Settings
from .market_regime import MarketRegimeService
from .models import (
    AdvisorSeverity,
    DailyBrief,
    DailyBriefRunRequest,
    RunCardActor,
    RunCardTriggerSource,
    RunCardType,
    utc_now,
)
from .run_cards import RunCardService, stable_hash
from .store import Store


DAILY_BRIEF_RULE_VERSION = "daily_brief_v1"


class DailyBriefService:
    def __init__(self, settings: Settings, store: Store):
        self.settings = settings
        self.store = store

    def run(
        self,
        request: DailyBriefRunRequest,
        *,
        actor: RunCardActor | str = RunCardActor.API,
    ) -> DailyBrief:
        advisor = AdvisorService(self.store, paper_only=self.settings.is_paper).build_brief()
        regime = MarketRegimeService(self.settings, self.store).build_snapshot()
        advisor_hash = stable_hash(advisor.model_dump(mode="json"))
        run_card = RunCardService(self.store).start_run(
            RunCardType.DAILY_BRIEF,
            title=f"{request.brief_type.value.title()} Brief",
            actor=actor,
            trigger_source=RunCardTriggerSource.MANUAL,
            rule_version=DAILY_BRIEF_RULE_VERSION,
            inputs=request.model_dump(mode="json"),
            dataset={"advisor_brief_hash": advisor_hash, "market_regime": regime.model_dump(mode="json")},
            assumptions={"brief_creation_has_no_side_effects": True, "cannot_create_proposals": True},
        )
        brief = DailyBrief(
            date=utc_now().date().isoformat(),
            brief_type=request.brief_type,
            market_regime_snapshot_id=regime.id,
            advisor_brief_hash=advisor_hash,
            blocked_items=_items(advisor.advice, AdvisorSeverity.BLOCKED),
            action_items=_items(advisor.advice, AdvisorSeverity.ACTION),
            watch_items=_items(advisor.advice, AdvisorSeverity.WATCH),
            info_items=_items(advisor.advice, AdvisorSeverity.INFO),
            delivered_to=request.delivered_to,
            delivered_at=utc_now() if request.delivered_to else None,
            run_card_id=run_card.id,
        )
        stored = self.store.create_daily_brief(brief)
        RunCardService(self.store).complete_run(
            run_card.id,
            metrics={
                "blocked": len(stored.blocked_items),
                "action": len(stored.action_items),
                "watch": len(stored.watch_items),
                "info": len(stored.info_items),
            },
            warnings=[],
            outputs={"daily_brief_id": stored.id, "brief_type": stored.brief_type.value},
            dataset=stored.model_dump(mode="json"),
        )
        return stored


def _items(items, severity: AdvisorSeverity) -> list[dict]:
    return [item.model_dump(mode="json") for item in items if item.severity == severity]

