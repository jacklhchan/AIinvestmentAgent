from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone

from .models import (
    ResearchClaim,
    ResearchClaimStatus,
    ResearchCriterion,
    ResearchCriterionStatus,
    ResearchEvidence,
    ResearchEvidenceCreate,
    ResearchGoal,
    ResearchGoalCreate,
    ResearchGoalStatus,
    utc_now,
)
from .store import Store


FORBIDDEN_EXECUTION_TERMS = {
    "unlock_trade",
    "place_order",
    "modify_order",
    "live order",
    "live trade",
    "execute trade",
    "approve trade",
    "broker execution",
    "實盤下單",
    "直接下單",
    "解鎖交易",
    "批准交易",
}

VERIFIED_SOURCE_TYPES = {"sec-edgar", "company-ir", "sec-companyfacts", "primary-source"}
DIRECTIONAL_SOURCE_TYPES = {"demo", "gdelt", "google-news", "finnhub", "market-news"}
DEFAULT_MAX_VERIFIED_EVIDENCE_AGE_DAYS = 120


class ResearchGoalService:
    def __init__(self, store: Store):
        self.store = store

    def create_goal(self, request: ResearchGoalCreate) -> ResearchGoal:
        _reject_execution_objective(request.objective)
        goal = ResearchGoal(
            symbol=request.symbol,
            objective=request.objective,
            protocol=request.protocol,
            risk_tier="research-only",
            token_budget=request.token_budget,
            turn_budget=request.turn_budget,
            claims=[ResearchClaim(text=text) for text in request.claims],
            criteria=[ResearchCriterion(text=text) for text in request.criteria],
        )
        goal.claims = [claim.model_copy(update={"goal_id": goal.id}) for claim in goal.claims]
        goal.criteria = [criterion.model_copy(update={"goal_id": goal.id}) for criterion in goal.criteria]
        return self.store.create_research_goal(goal)

    def add_evidence(self, request: ResearchEvidenceCreate, *, trusted_source: bool = False) -> ResearchEvidence:
        if not self.store.get_research_goal(request.goal_id):
            raise ValueError(f"research goal not found: {request.goal_id}")
        source_verified = trusted_source and request.source_type in VERIFIED_SOURCE_TYPES
        verification_status = "verified" if source_verified and request.verification_status == "verified" else "unverified"
        normalized = request.model_copy(
            update={
                "source_verified": source_verified,
                "verification_status": verification_status,
                "added_via": request.added_via or ("system" if trusted_source else "local"),
            }
        )
        evidence = ResearchEvidence(**normalized.model_dump())
        return self.store.add_research_evidence(evidence)

    def complete_if_sufficient(self, goal_id: str, *, max_verified_age_days: int = DEFAULT_MAX_VERIFIED_EVIDENCE_AGE_DAYS) -> ResearchGoal:
        goal = self.require_goal(goal_id)
        gate = evaluate_research_gate(goal, max_verified_age_days=max_verified_age_days)
        goal.status = ResearchGoalStatus.COMPLETED if gate.passed else ResearchGoalStatus.INSUFFICIENT
        goal.summary = gate.summary
        goal.completed_at = utc_now()
        goal.claims = [
            claim.model_copy(update={"status": ResearchClaimStatus.SUPPORTED if gate.passed else claim.status})
            for claim in goal.claims
        ]
        updated_criteria = []
        for criterion in goal.criteria:
            status = ResearchCriterionStatus.SATISFIED if gate.passed else ResearchCriterionStatus.INSUFFICIENT
            updated_criteria.append(criterion.model_copy(update={"status": status}))
        goal.criteria = updated_criteria
        return self.store.update_research_goal(goal, "research_goal_completed" if gate.passed else "research_goal_insufficient")

    def require_goal(self, goal_id: str) -> ResearchGoal:
        goal = self.store.get_research_goal(goal_id)
        if not goal:
            raise ValueError(f"research goal not found: {goal_id}")
        return goal


class ResearchGateResult:
    def __init__(
        self,
        passed: bool,
        reasons: list[str],
        evidence_count: int,
        verified_count: int,
        goal_id: str | None = None,
    ):
        self.passed = passed
        self.reasons = reasons
        self.evidence_count = evidence_count
        self.verified_count = verified_count
        self.goal_id = goal_id

    @property
    def summary(self) -> str:
        state = "passed" if self.passed else "insufficient"
        detail = f"evidence gate {state}: {self.verified_count}/{self.evidence_count} verified evidence row(s)"
        if self.reasons:
            return f"{detail}; {'; '.join(self.reasons)}"
        return detail


def evaluate_research_gate(
    goal: ResearchGoal,
    *,
    max_verified_age_days: int = DEFAULT_MAX_VERIFIED_EVIDENCE_AGE_DAYS,
) -> ResearchGateResult:
    evidence = [item for item in goal.evidence if _matches_goal_symbol(goal, item)]
    verified = [item for item in evidence if _is_verified(item, max_verified_age_days=max_verified_age_days)]
    directional = [item for item in evidence if item.source_type in DIRECTIONAL_SOURCE_TYPES]
    contradictions = [item for item in evidence if item.contradicts_claim_ids]
    reasons: list[str] = []
    if not directional:
        reasons.append("no recent directional market evidence attached")
    if not verified:
        reasons.append("no verified primary-source or fundamentals evidence attached")
    if len(evidence) != len(goal.evidence):
        reasons.append("one or more evidence rows do not match the research goal symbol")
    if contradictions:
        reasons.append("contradicting evidence is attached; gate is mixed and requires human review")
    if goal.risk_tier != "research-only":
        reasons.append("goal risk tier must stay research-only")
    return ResearchGateResult(
        passed=not reasons,
        reasons=reasons,
        evidence_count=len(evidence),
        verified_count=len(verified),
        goal_id=goal.id,
    )


def research_goal_from_draft(
    *,
    store: Store,
    symbol: str,
    side: str,
    score: int,
    thesis: str,
    news_evidence: list[ResearchEvidenceCreate],
    verified_evidence: list[ResearchEvidenceCreate],
) -> ResearchGateResult:
    service = ResearchGoalService(store)
    goal = service.create_goal(
        ResearchGoalCreate(
            symbol=symbol,
            objective=f"Evaluate {symbol} {side} proposal evidence before any paper proposal is created.",
            claims=[f"Watchlist evidence currently supports a {side} proposal for {symbol} with directional score {score}."],
            criteria=[
                "At least one recent directional market/news evidence row is attached.",
                "At least one verified primary-source or SEC fundamentals evidence row is attached.",
                "The output remains research-only and cannot approve or execute trades.",
            ],
        )
    )
    for item in news_evidence:
        service.add_evidence(item.model_copy(update={"goal_id": goal.id}), trusted_source=False)
    for item in verified_evidence:
        service.add_evidence(item.model_copy(update={"goal_id": goal.id}), trusted_source=True)
    refreshed = service.complete_if_sufficient(goal.id)
    gate = evaluate_research_gate(refreshed)
    refreshed.summary = f"{gate.summary}; thesis: {thesis[:160]}"
    store.update_research_goal(refreshed, "research_goal_evaluated")
    return gate


def evidence_from_news(
    *,
    goal_id: str,
    symbol: str,
    source_type: str,
    title: str,
    source_uri: str | None,
    published_at,
    verified: bool,
) -> ResearchEvidenceCreate:
    return ResearchEvidenceCreate(
        goal_id=goal_id,
        symbol=symbol,
        source_type=source_type,
        source_uri=source_uri,
        text=title,
        data_as_of=_coerce_datetime(published_at),
        freshness_status="fresh",
        verification_status="verified" if verified else "unverified",
        source_verified=verified,
        added_via="system" if verified else "market-ingest",
        confidence=0.74 if verified else 0.55,
        caveat="Primary-source evidence." if verified else "Market/news discovery evidence; requires primary-source confirmation.",
    )


def compute_evidence_hash(
    *,
    goal: ResearchGoal | None,
    proposal_evidence: list[str],
    counter_evidence: list[str],
    manual_override_reason: str | None = None,
) -> str:
    payload = {
        "goal_id": goal.id if goal else None,
        "goal_status": goal.status.value if goal else None,
        "manual_override_reason": manual_override_reason,
        "proposal_evidence": sorted(proposal_evidence),
        "counter_evidence": sorted(counter_evidence),
        "research_evidence": [
            {
                "id": item.id,
                "symbol": item.symbol,
                "source_type": item.source_type,
                "source_uri": item.source_uri,
                "text": item.text,
                "data_as_of": item.data_as_of.isoformat() if item.data_as_of else None,
                "verification_status": item.verification_status,
                "source_verified": item.source_verified,
                "contradicts_claim_ids": sorted(item.contradicts_claim_ids),
            }
            for item in sorted(goal.evidence, key=lambda item: item.id)
        ]
        if goal
        else [],
    }
    encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _is_verified(evidence: ResearchEvidence, *, max_verified_age_days: int) -> bool:
    return (
        evidence.source_verified
        and evidence.verification_status == "verified"
        and evidence.source_type in VERIFIED_SOURCE_TYPES
        and not _is_stale(evidence, max_verified_age_days=max_verified_age_days)
    )


def _matches_goal_symbol(goal: ResearchGoal, evidence: ResearchEvidence) -> bool:
    if not goal.symbol:
        return True
    return evidence.symbol == goal.symbol


def _is_stale(evidence: ResearchEvidence, *, max_verified_age_days: int) -> bool:
    observed_at = evidence.data_as_of or evidence.retrieved_at
    return observed_at < utc_now() - _timedelta_days(max_verified_age_days)


def _timedelta_days(days: int):
    from datetime import timedelta

    return timedelta(days=max(1, days))


def _coerce_datetime(value) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    return None


def _reject_execution_objective(objective: str) -> None:
    lowered = objective.lower()
    matched = [term for term in FORBIDDEN_EXECUTION_TERMS if term.lower() in lowered]
    if matched:
        raise ValueError(
            "research goals are research-only; execution, approval, unlock, and broker-order objectives are not allowed"
        )
