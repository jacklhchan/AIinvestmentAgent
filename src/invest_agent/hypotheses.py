from __future__ import annotations

from .models import (
    CreatedBy,
    CreatedVia,
    HypothesisCreate,
    HypothesisInvalidateRequest,
    HypothesisLink,
    HypothesisLinkCreate,
    HypothesisStatus,
    ResearchHypothesis,
    RunCardActor,
    utc_now,
)
from .run_cards import stable_hash
from .store import Store


class HypothesisRegistryService:
    def __init__(self, store: Store):
        self.store = store

    def create(self, request: HypothesisCreate, *, actor: RunCardActor | str = RunCardActor.API) -> ResearchHypothesis:
        actor_value = RunCardActor(actor)
        created_via = request.created_via
        created_by = request.created_by
        human_confirmed = request.human_confirmed
        if actor_value == RunCardActor.MCP:
            created_via = CreatedVia.MCP
            created_by = CreatedBy.HERMES
            human_confirmed = False
        hypothesis = ResearchHypothesis(
            title=request.title.strip(),
            statement=request.statement.strip(),
            scope=request.scope,
            symbols=request.symbols,
            status=HypothesisStatus.DRAFT,
            confidence=request.confidence,
            created_via=created_via,
            created_by=created_by,
            human_confirmed=human_confirmed,
        )
        return self.store.create_hypothesis(hypothesis)

    def link(self, hypothesis_id: str, request: HypothesisLinkCreate) -> HypothesisLink:
        hypothesis = self.require_hypothesis(hypothesis_id)
        evidence_hash = request.evidence_hash or stable_hash(
            {"hypothesis_id": hypothesis.id, "linked_type": request.linked_type.value, "linked_id": request.linked_id}
        )
        link = HypothesisLink(
            hypothesis_id=hypothesis.id,
            linked_type=request.linked_type,
            linked_id=request.linked_id,
            evidence_hash=evidence_hash,
        )
        return self.store.add_hypothesis_link(link)

    def invalidate(self, hypothesis_id: str, request: HypothesisInvalidateRequest) -> ResearchHypothesis:
        hypothesis = self.require_hypothesis(hypothesis_id)
        hypothesis.status = HypothesisStatus.REJECTED
        hypothesis.invalidation_note = request.invalidation_note.strip()
        hypothesis.updated_at = utc_now()
        return self.store.update_hypothesis(hypothesis, "research_hypothesis_invalidated")

    def require_hypothesis(self, hypothesis_id: str) -> ResearchHypothesis:
        hypothesis = self.store.get_hypothesis(hypothesis_id)
        if not hypothesis:
            raise ValueError(f"hypothesis not found: {hypothesis_id}")
        return hypothesis

