from __future__ import annotations

from .models import CommitteeConclusion, CommitteeReview, CommitteeReviewRunRequest, RunCardActor, RunCardTriggerSource, RunCardType
from .run_cards import RunCardService
from .store import Store


COMMITTEE_REVIEW_RULE_VERSION = "committee_review_v1"


class CommitteeReviewService:
    def __init__(self, store: Store):
        self.store = store

    def run_review(
        self,
        request: CommitteeReviewRunRequest,
        *,
        actor: RunCardActor | str = RunCardActor.API,
    ) -> CommitteeReview:
        missing = list(request.missing_evidence)
        if request.research_goal_id:
            goal = self.store.get_research_goal(request.research_goal_id)
            if not goal:
                missing.append(f"research goal not found: {request.research_goal_id}")
            elif not goal.evidence:
                missing.append("research goal has no evidence rows")
        conclusion = request.conclusion
        if missing and conclusion == CommitteeConclusion.ELIGIBLE_FOR_PROPOSAL:
            conclusion = CommitteeConclusion.RESEARCH_MORE
        run_card = RunCardService(self.store).start_run(
            RunCardType.COMMITTEE_REVIEW,
            title=f"Committee Review: {request.topic}",
            actor=actor,
            trigger_source=RunCardTriggerSource.MANUAL,
            rule_version=COMMITTEE_REVIEW_RULE_VERSION,
            inputs=request.model_dump(mode="json"),
            assumptions={"committee_memo_cannot_approve": True, "cannot_create_pending_proposal_directly": True},
            links={"research_goal_id": request.research_goal_id, "proposal_id": request.proposal_id},
        )
        review = CommitteeReview(
            topic=request.topic,
            proposal_id=request.proposal_id,
            research_goal_id=request.research_goal_id,
            hypothesis_id=request.hypothesis_id,
            bull_case=request.bull_case,
            bear_case=request.bear_case,
            risk_memo=request.risk_memo,
            missing_evidence=missing,
            conclusion=conclusion,
            run_card_id=run_card.id,
        )
        stored = self.store.create_committee_review(review)
        RunCardService(self.store).complete_run(
            run_card.id,
            metrics={"missing_evidence_count": len(missing)},
            warnings=missing,
            outputs={"committee_review_id": stored.id, "conclusion": stored.conclusion.value},
            dataset=stored.model_dump(mode="json"),
            links={"research_goal_id": stored.research_goal_id, "proposal_id": stored.proposal_id},
        )
        return stored

