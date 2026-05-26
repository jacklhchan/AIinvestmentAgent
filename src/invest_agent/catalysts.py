from __future__ import annotations

from datetime import timedelta

from .models import (
    Catalyst,
    CatalystActionBias,
    CatalystCompleteRequest,
    CatalystCreate,
    CatalystEventType,
    CatalystExpectedImpact,
    CatalystReview,
    CatalystReviewCreate,
    CatalystSourceType,
    CatalystStatus,
    CatalystThesisDelta,
    CatalystVerificationStatus,
    CreatedBy,
    CreatedVia,
    ResearchGoalCreate,
    RunCardActor,
    RunCardTriggerSource,
    RunCardType,
    ThesisActionBias,
    ThesisImpact,
    ThesisUpdateCreate,
    utc_now,
)
from .research_goals import ResearchGoalService, compute_evidence_hash
from .run_cards import RunCardService
from .store import Store
from .thesis_tracker import ThesisTrackerService


OFFICIAL_CATALYST_SOURCE_TYPES = {
    CatalystSourceType.SEC_EDGAR,
    CatalystSourceType.COMPANY_IR,
    CatalystSourceType.EXCHANGE_CALENDAR,
    CatalystSourceType.MACRO_CALENDAR,
}
HIGH_IMPACT_BLOCK_HOURS = 48
MEDIUM_IMPACT_WARNING_HOURS = 24
RECENT_COMPLETED_REVIEW_DAYS = 7


class CatalystCalendarService:
    def __init__(self, store: Store):
        self.store = store

    def create_catalyst(
        self,
        request: CatalystCreate,
        *,
        trusted_source: bool = False,
        human_verified: bool = False,
    ) -> Catalyst:
        source_verified = (
            trusted_source
            and request.source_type in OFFICIAL_CATALYST_SOURCE_TYPES
            and request.verification_status == CatalystVerificationStatus.SOURCE_VERIFIED
        )
        verification_status = CatalystVerificationStatus.UNVERIFIED
        if source_verified:
            verification_status = CatalystVerificationStatus.SOURCE_VERIFIED
        elif human_verified:
            verification_status = CatalystVerificationStatus.HUMAN_VERIFIED

        catalyst = Catalyst(
            symbol=request.symbol,
            event_type=request.event_type,
            title=request.title.strip(),
            description=request.description.strip(),
            event_date=request.event_date,
            event_time_hint=request.event_time_hint,
            timezone=request.timezone,
            expected_impact=request.expected_impact,
            source_uri=request.source_uri,
            source_type=request.source_type,
            verification_status=verification_status,
            source_verified=source_verified,
            linked_thesis_id=request.linked_thesis_id,
            created_via=request.created_via,
            created_by=request.created_by,
        )
        return self.store.create_catalyst(catalyst)

    def list_upcoming(self, *, days: int = 14, symbol: str | None = None, limit: int = 50) -> list[Catalyst]:
        now = utc_now()
        horizon = now + timedelta(days=max(1, days))
        candidates = self.store.list_catalysts(
            status=CatalystStatus.UPCOMING,
            symbol=symbol,
            limit=max(limit * 4, 200),
        )
        upcoming = [
            catalyst
            for catalyst in candidates
            if now <= catalyst.event_date <= horizon
        ]
        return upcoming[:limit]

    def complete_catalyst(self, catalyst_id: str, request: CatalystCompleteRequest) -> Catalyst:
        catalyst = self.require_catalyst(catalyst_id)
        catalyst.status = CatalystStatus.COMPLETED
        catalyst.actual_outcome_summary = request.actual_outcome_summary.strip()
        catalyst.updated_at = utc_now()
        if request.create_research_goal and not catalyst.linked_research_goal_id:
            goal = self.create_post_event_research_goal(catalyst)
            catalyst.linked_research_goal_id = goal.id
        return self.store.update_catalyst(catalyst, "catalyst_completed")

    def create_review(
        self,
        catalyst_id: str,
        request: CatalystReviewCreate,
        *,
        apply_to_thesis: bool = True,
        actor: RunCardActor | str = RunCardActor.SYSTEM,
        trigger_source: RunCardTriggerSource | str = RunCardTriggerSource.MANUAL,
    ) -> CatalystReview:
        catalyst = self.require_catalyst(catalyst_id)
        run_card_id = request.run_card_id
        created_run_card = not run_card_id
        if not run_card_id:
            run_card = RunCardService(self.store).start_run(
                RunCardType.CATALYST_REVIEW,
                title=f"Catalyst Review: {catalyst.title}",
                symbol=catalyst.symbol,
                actor=actor,
                trigger_source=trigger_source,
                rule_version="catalyst_review_v1",
                inputs=request.model_dump(mode="json"),
                dataset={
                    "catalyst_id": catalyst.id,
                    "symbol": catalyst.symbol,
                    "event_type": catalyst.event_type.value,
                    "event_date": catalyst.event_date.isoformat(),
                    "expected_impact": catalyst.expected_impact.value,
                    "source_type": catalyst.source_type.value,
                    "verification_status": catalyst.verification_status.value,
                },
                assumptions={
                    "review_requires_research_goal_for_evidence_hash": bool(request.research_goal_id),
                    "output_is_research_only": True,
                },
                links={
                    "research_goal_id": request.research_goal_id,
                    "thesis_id": catalyst.linked_thesis_id,
                    "catalyst_id": catalyst.id,
                },
            )
            run_card_id = run_card.id
        evidence_hash = request.evidence_hash or ""
        if request.research_goal_id:
            goal = self.store.get_research_goal(request.research_goal_id)
            if not goal:
                raise ValueError(f"research goal not found: {request.research_goal_id}")
            if catalyst.symbol and goal.symbol and catalyst.symbol != goal.symbol:
                raise ValueError(f"research goal symbol {goal.symbol} does not match catalyst symbol {catalyst.symbol}")
            evidence_hash = compute_evidence_hash(
                goal=goal,
                proposal_evidence=[],
                counter_evidence=[],
                catalyst_id=catalyst.id,
            )

        review = CatalystReview(
            catalyst_id=catalyst.id,
            research_goal_id=request.research_goal_id,
            evidence_hash=evidence_hash,
            actual_outcome_summary=request.actual_outcome_summary.strip(),
            thesis_delta=request.thesis_delta,
            action_bias=request.action_bias,
            run_card_id=run_card_id,
        )
        catalyst.status = CatalystStatus.COMPLETED
        catalyst.actual_outcome_summary = review.actual_outcome_summary
        catalyst.thesis_delta = review.thesis_delta
        catalyst.linked_research_goal_id = request.research_goal_id or catalyst.linked_research_goal_id
        catalyst.updated_at = utc_now()
        self.store.update_catalyst(catalyst, "catalyst_review_applied")
        saved = self.store.create_catalyst_review(review)
        if created_run_card:
            RunCardService(self.store).complete_run(
                run_card_id,
                metrics={
                    "expected_impact": catalyst.expected_impact.value,
                    "review_count": len(self.store.list_catalyst_reviews(catalyst.id)),
                },
                warnings=[],
                outputs={
                    "thesis_delta": saved.thesis_delta.value,
                    "action_bias": saved.action_bias.value,
                    "evidence_hash": saved.evidence_hash,
                    "actual_outcome_summary": saved.actual_outcome_summary,
                },
                evidence_hash=saved.evidence_hash,
                links={
                    "research_goal_id": saved.research_goal_id,
                    "thesis_id": catalyst.linked_thesis_id,
                    "catalyst_id": catalyst.id,
                    "catalyst_review_id": saved.id,
                },
            )
        if apply_to_thesis:
            self._maybe_update_linked_thesis(catalyst, saved)
        return saved

    def create_post_event_research_goal(self, catalyst: Catalyst):
        objective = f"Review {catalyst.title} outcome before any post-event proposal is created."
        criteria = [
            "Attach primary-source or human-verified catalyst outcome evidence.",
            "Classify thesis delta as strengthens, weakens, neutral, or invalidates.",
            "Keep output research-only; do not approve or execute trades.",
        ]
        return ResearchGoalService(self.store).create_goal(
            ResearchGoalCreate(
                symbol=catalyst.symbol,
                objective=objective,
                claims=[f"{catalyst.title} may affect thesis and proposal eligibility."],
                criteria=criteria,
            )
        )

    def create_post_event_goals_for_completed(self, *, limit: int = 20) -> list[str]:
        created: list[str] = []
        for catalyst in self.store.list_catalysts(status=CatalystStatus.COMPLETED, limit=limit):
            if catalyst.linked_research_goal_id or self.store.list_catalyst_reviews(catalyst.id):
                continue
            goal = self.create_post_event_research_goal(catalyst)
            catalyst.linked_research_goal_id = goal.id
            catalyst.updated_at = utc_now()
            self.store.update_catalyst(catalyst, "catalyst_post_event_goal_created")
            created.append(goal.id)
        return created

    def proposal_catalyst_findings(self, symbol: str, *, has_manual_override: bool = False) -> tuple[list[str], list[str]]:
        now = utc_now()
        reasons: list[str] = []
        warnings: list[str] = []
        upcoming = self._proposal_scope_catalysts(CatalystStatus.UPCOMING, symbol)
        completed = self._proposal_scope_catalysts(CatalystStatus.COMPLETED, symbol)
        for catalyst in upcoming:
            hours_until = (catalyst.event_date - now).total_seconds() / 3600
            if hours_until < 0:
                continue
            if catalyst.expected_impact == CatalystExpectedImpact.HIGH and hours_until <= HIGH_IMPACT_BLOCK_HOURS:
                message = f"high-impact catalyst within {HIGH_IMPACT_BLOCK_HOURS}h: {catalyst.title}"
                if has_manual_override:
                    warnings.append(f"manual override acknowledges {message}")
                else:
                    reasons.append(message)
            if catalyst.expected_impact == CatalystExpectedImpact.MEDIUM and hours_until <= MEDIUM_IMPACT_WARNING_HOURS:
                warnings.append(
                    f"medium-impact catalyst within {MEDIUM_IMPACT_WARNING_HOURS}h; confidence haircut applies: {catalyst.title}"
                )
        for catalyst in completed:
            if catalyst.expected_impact in {
                CatalystExpectedImpact.HIGH,
                CatalystExpectedImpact.MEDIUM,
            }:
                days_since = (now - catalyst.event_date).total_seconds() / 86400
                if 0 <= days_since <= RECENT_COMPLETED_REVIEW_DAYS and not self.store.list_catalyst_reviews(catalyst.id):
                    message = f"completed catalyst lacks post-event review: {catalyst.title}"
                    if has_manual_override:
                        warnings.append(f"manual override acknowledges {message}")
                    else:
                        reasons.append(message)
        try:
            from .options_lens import OptionsLensService

            warnings.extend(OptionsLensService(self.store).catalyst_warnings(symbol))
        except Exception:
            pass
        return reasons, warnings

    def require_catalyst(self, catalyst_id: str) -> Catalyst:
        catalyst = self.store.get_catalyst(catalyst_id)
        if not catalyst:
            raise ValueError(f"catalyst not found: {catalyst_id}")
        return catalyst

    def _proposal_scope_catalysts(self, status: CatalystStatus, symbol: str) -> list[Catalyst]:
        symbol_specific = self.store.list_catalysts(status=status, symbol=symbol, limit=200)
        macro_global = [
            catalyst
            for catalyst in self.store.list_catalysts(status=status, limit=200)
            if catalyst.symbol is None and catalyst.event_type == CatalystEventType.MACRO
        ]
        by_id = {catalyst.id: catalyst for catalyst in symbol_specific}
        by_id.update({catalyst.id: catalyst for catalyst in macro_global})
        return sorted(by_id.values(), key=lambda catalyst: catalyst.event_date)

    def _maybe_update_linked_thesis(self, catalyst: Catalyst, review: CatalystReview) -> None:
        if not catalyst.linked_thesis_id or review.thesis_delta == CatalystThesisDelta.UNKNOWN:
            return
        thesis_impact = _thesis_impact(review.thesis_delta)
        action_bias = _thesis_action_bias(review.action_bias)
        ThesisTrackerService(self.store).add_update(
            catalyst.linked_thesis_id,
            ThesisUpdateCreate(
                research_goal_id=review.research_goal_id,
                evidence_hash=review.evidence_hash,
                impact=thesis_impact,
                summary=f"Catalyst review: {review.actual_outcome_summary}",
                action_bias=action_bias,
            ),
        )


def mcp_catalyst_request(
    *,
    symbol: str | None,
    event_type,
    title: str,
    event_date,
    expected_impact,
    description: str = "",
    source_uri: str | None = None,
    linked_thesis_id: str | None = None,
) -> CatalystCreate:
    return CatalystCreate(
        symbol=symbol,
        event_type=event_type,
        title=title,
        description=description,
        event_date=event_date,
        expected_impact=expected_impact,
        source_uri=source_uri,
        source_type=CatalystSourceType.MANUAL,
        verification_status=CatalystVerificationStatus.UNVERIFIED,
        source_verified=False,
        linked_thesis_id=linked_thesis_id,
        created_via=CreatedVia.MCP,
        created_by=CreatedBy.HERMES,
    )


def _thesis_impact(delta: CatalystThesisDelta) -> ThesisImpact:
    mapping = {
        CatalystThesisDelta.STRENGTHENS: ThesisImpact.STRENGTHENS,
        CatalystThesisDelta.WEAKENS: ThesisImpact.WEAKENS,
        CatalystThesisDelta.NEUTRAL: ThesisImpact.NEUTRAL,
        CatalystThesisDelta.INVALIDATES: ThesisImpact.INVALIDATES,
    }
    return mapping.get(delta, ThesisImpact.NEUTRAL)


def _thesis_action_bias(action_bias: CatalystActionBias) -> ThesisActionBias:
    mapping = {
        CatalystActionBias.NO_CHANGE: ThesisActionBias.NO_CHANGE,
        CatalystActionBias.WATCH_ONLY: ThesisActionBias.WATCH_ONLY,
        CatalystActionBias.INCREASE: ThesisActionBias.INCREASE,
        CatalystActionBias.TRIM: ThesisActionBias.TRIM,
        CatalystActionBias.EXIT: ThesisActionBias.EXIT,
        CatalystActionBias.BLOCK_NEW_PROPOSAL: ThesisActionBias.WATCH_ONLY,
    }
    return mapping[action_bias]
