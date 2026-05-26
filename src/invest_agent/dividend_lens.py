from __future__ import annotations

from .models import (
    DividendReview,
    DividendReviewRunRequest,
    RunCardActor,
    RunCardTriggerSource,
    RunCardType,
    ThesisActionBias,
    ThesisImpact,
    ThesisUpdateCreate,
)
from .run_cards import RunCardService, stable_hash
from .store import Store
from .thesis_tracker import ThesisTrackerService


DIVIDEND_REVIEW_RULE_VERSION = "dividend_review_v1"


class DividendLensService:
    def __init__(self, store: Store):
        self.store = store

    def run_review(
        self,
        request: DividendReviewRunRequest,
        *,
        actor: RunCardActor | str = RunCardActor.API,
    ) -> DividendReview:
        shareholder_yield = (request.dividend_yield or 0.0) + (request.buyback_yield if hasattr(request, "buyback_yield") and request.buyback_yield else 0.0)
        warning = ""
        if request.payout_ratio is not None and request.payout_ratio > 1.0:
            warning = "Payout ratio exceeds 100%; possible yield-trap risk."
        if request.fcf_coverage is not None and request.fcf_coverage < 1.0:
            warning = "Free-cash-flow coverage is below 1.0; dividend sustainability needs review."
        payload = request.model_dump(mode="json")
        run_card = RunCardService(self.store).start_run(
            RunCardType.DIVIDEND_REVIEW,
            title=f"Dividend Review: {request.symbol}",
            symbol=request.symbol,
            actor=actor,
            trigger_source=RunCardTriggerSource.MANUAL,
            rule_version=DIVIDEND_REVIEW_RULE_VERSION,
            inputs=payload,
            dataset=payload,
            assumptions={"high_yield_alone_cannot_create_buy_proposal": True},
            links={"thesis_id": request.thesis_id},
        )
        review = DividendReview(
            symbol=request.symbol,
            dividend_yield=request.dividend_yield,
            payout_ratio=request.payout_ratio,
            dividend_growth_3y=request.dividend_growth_3y,
            fcf_coverage=request.fcf_coverage,
            shareholder_yield=shareholder_yield,
            yield_trap_warning=warning,
            ex_dividend_date=request.ex_dividend_date,
            source_summary="Manual/local dividend inputs; research-only review.",
            evidence_hash=stable_hash(payload),
            run_card_id=run_card.id,
        )
        stored = self.store.create_dividend_review(review)
        if request.thesis_id:
            ThesisTrackerService(self.store).add_update(
                request.thesis_id,
                ThesisUpdateCreate(
                    impact=ThesisImpact.WEAKENS if warning else ThesisImpact.STRENGTHENS,
                    summary=f"Dividend review for {request.symbol}: {warning or 'shareholder yield context updated.'}",
                    action_bias=ThesisActionBias.WATCH_ONLY,
                    evidence_hash=stored.evidence_hash,
                ),
            )
        RunCardService(self.store).complete_run(
            run_card.id,
            metrics={"shareholder_yield": stored.shareholder_yield or 0.0, "has_yield_trap_warning": bool(warning)},
            warnings=[warning] if warning else [],
            outputs={"dividend_review_id": stored.id},
            dataset=stored.model_dump(mode="json"),
            evidence_hash=stored.evidence_hash,
            links={"thesis_id": request.thesis_id},
        )
        return stored

