from __future__ import annotations

from .models import (
    Thesis,
    ThesisActionBias,
    ThesisConviction,
    ThesisCreate,
    ThesisImpact,
    ThesisPillar,
    ThesisRisk,
    ThesisStatus,
    ThesisUpdate,
    ThesisUpdateCreate,
    utc_now,
)
from .research_goals import compute_evidence_hash
from .store import Store


class ThesisTrackerService:
    def __init__(self, store: Store):
        self.store = store

    def create_thesis(self, request: ThesisCreate) -> Thesis:
        thesis = Thesis(
            symbol=request.symbol,
            side=request.side,
            thesis_statement=request.thesis_statement.strip(),
            conviction=request.conviction,
            target_price=request.target_price,
            stop_loss_trigger=request.stop_loss_trigger.strip(),
        )
        thesis.pillars = [
            ThesisPillar(thesis_id=thesis.id, text=pillar.text.strip(), status=pillar.status)
            for pillar in request.pillars
        ]
        thesis.risks = [
            ThesisRisk(
                thesis_id=thesis.id,
                text=risk.text.strip(),
                invalidation_condition=risk.invalidation_condition.strip(),
                status=risk.status,
            )
            for risk in request.risks
        ]
        return self.store.create_thesis(thesis)

    def add_update(self, thesis_id: str, request: ThesisUpdateCreate) -> Thesis:
        thesis = self.require_thesis(thesis_id)
        evidence_hash = request.evidence_hash or ""
        if request.research_goal_id:
            goal = self.store.get_research_goal(request.research_goal_id)
            if not goal:
                raise ValueError(f"research goal not found: {request.research_goal_id}")
            if goal.symbol and goal.symbol != thesis.symbol:
                raise ValueError(f"research goal symbol {goal.symbol} does not match thesis symbol {thesis.symbol}")
            evidence_hash = compute_evidence_hash(
                goal=goal,
                proposal_evidence=[],
                counter_evidence=[],
                thesis_id=thesis.id,
            )

        update = ThesisUpdate(
            thesis_id=thesis.id,
            research_goal_id=request.research_goal_id,
            evidence_hash=evidence_hash,
            impact=request.impact,
            summary=request.summary.strip(),
            action_bias=request.action_bias,
        )
        thesis.updated_at = utc_now()
        thesis = _apply_update_to_thesis(thesis, request)
        return self.store.add_thesis_update(thesis, update)

    def require_thesis(self, thesis_id: str) -> Thesis:
        thesis = self.store.get_thesis(thesis_id)
        if not thesis:
            raise ValueError(f"thesis not found: {thesis_id}")
        return thesis


def _apply_update_to_thesis(thesis: Thesis, request: ThesisUpdateCreate) -> Thesis:
    if request.conviction:
        thesis.conviction = request.conviction
    elif request.impact == ThesisImpact.WEAKENS:
        thesis.conviction = _lower_conviction(thesis.conviction)
    elif request.impact == ThesisImpact.INVALIDATES:
        thesis.conviction = ThesisConviction.LOW

    if request.impact == ThesisImpact.INVALIDATES or request.action_bias == ThesisActionBias.EXIT:
        thesis.status = ThesisStatus.INVALIDATED
    elif request.action_bias == ThesisActionBias.WATCH_ONLY and thesis.status == ThesisStatus.ACTIVE:
        thesis.status = ThesisStatus.WATCH
    elif request.impact == ThesisImpact.STRENGTHENS and thesis.status == ThesisStatus.WATCH:
        thesis.status = ThesisStatus.ACTIVE
    return thesis


def _lower_conviction(conviction: ThesisConviction) -> ThesisConviction:
    if conviction == ThesisConviction.HIGH:
        return ThesisConviction.MEDIUM
    if conviction == ThesisConviction.MEDIUM:
        return ThesisConviction.LOW
    return ThesisConviction.LOW
