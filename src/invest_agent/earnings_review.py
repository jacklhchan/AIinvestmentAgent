from __future__ import annotations

from .catalysts import CatalystCalendarService
from .market_news import external_ticker
from .models import (
    CashflowQuality,
    CatalystActionBias,
    CatalystEventType,
    CatalystReviewCreate,
    CatalystThesisDelta,
    EarningsReview,
    EarningsReviewRunRequest,
    FundamentalMetric,
    FundamentalSnapshot,
    GuidanceTone,
    ResearchEvidenceCreate,
    ResearchGoalCreate,
    ThesisActionBias,
    ThesisImpact,
    ThesisUpdateCreate,
)
from .research_goals import ResearchGoalService, compute_evidence_hash
from .store import Store
from .thesis_tracker import ThesisTrackerService


POSITIVE_YOY_THRESHOLD = 5.0
NEGATIVE_YOY_THRESHOLD = -5.0
OCF_QUALITY_TOLERANCE = 10.0


class EarningsReviewService:
    def __init__(self, store: Store):
        self.store = store

    def run_review(self, request: EarningsReviewRunRequest) -> EarningsReview:
        symbol = request.symbol.upper()
        catalyst = self.store.get_catalyst(request.catalyst_id) if request.catalyst_id else None
        if request.catalyst_id and not catalyst:
            raise ValueError(f"catalyst not found: {request.catalyst_id}")
        if catalyst and catalyst.event_type != CatalystEventType.EARNINGS:
            raise ValueError("earnings review can only attach to earnings catalysts")
        if catalyst and catalyst.symbol and catalyst.symbol != symbol:
            raise ValueError(f"catalyst symbol {catalyst.symbol} does not match earnings review symbol {symbol}")

        snapshot = self._find_fundamentals(symbol)
        if not snapshot:
            raise ValueError(f"fundamental snapshot not found for {symbol}; refresh SEC companyfacts first")

        thesis_id = request.thesis_id or (catalyst.linked_thesis_id if catalyst else None)
        goal_id = request.research_goal_id or (catalyst.linked_research_goal_id if catalyst else None)
        goal = self._get_or_create_goal(symbol, goal_id)
        metrics = _earnings_metrics(snapshot)
        score, warnings = _score_metrics(metrics)
        thesis_delta = _thesis_delta(score, warnings)
        action_bias = _action_bias(thesis_delta)
        evidence_text = _source_summary(symbol, snapshot, score, metrics, warnings)
        ResearchGoalService(self.store).add_evidence(
            ResearchEvidenceCreate(
                goal_id=goal.id,
                symbol=symbol,
                source_type="sec-companyfacts",
                source_uri=f"sec-companyfacts://CIK{snapshot.cik}",
                text=evidence_text,
                data_as_of=_latest_filed_at(snapshot),
                freshness_status="fresh",
                verification_status="verified",
                source_verified=True,
                added_via="system",
                confidence=0.78,
                caveat="Deterministic earnings review from local SEC companyfacts snapshot; no trade execution intent.",
            ),
            trusted_source=True,
        )
        goal = ResearchGoalService(self.store).require_goal(goal.id)
        evidence_hash = compute_evidence_hash(
            goal=goal,
            proposal_evidence=[evidence_text],
            counter_evidence=warnings,
            thesis_id=thesis_id,
            catalyst_id=catalyst.id if catalyst else None,
        )

        catalyst_review_id = None
        if catalyst:
            if thesis_id and catalyst.linked_thesis_id != thesis_id:
                catalyst.linked_thesis_id = thesis_id
                self.store.update_catalyst(catalyst)
            catalyst_review = CatalystCalendarService(self.store).create_review(
                catalyst.id,
                CatalystReviewCreate(
                    research_goal_id=goal.id,
                    evidence_hash=evidence_hash,
                    actual_outcome_summary=_beat_miss_summary(score, metrics, warnings),
                    thesis_delta=thesis_delta,
                    action_bias=action_bias,
                ),
                apply_to_thesis=False,
            )
            catalyst_review_id = catalyst_review.id

        review = EarningsReview(
            symbol=symbol,
            period=request.period or _period(snapshot),
            fiscal_year=_primary_metric(snapshot).fiscal_year if _primary_metric(snapshot) else None,
            fiscal_quarter=_primary_metric(snapshot).fiscal_period if _primary_metric(snapshot) else "",
            release_date=catalyst.event_date if catalyst else None,
            filing_date=_latest_filed_at(snapshot),
            catalyst_id=catalyst.id if catalyst else None,
            catalyst_review_id=catalyst_review_id,
            research_goal_id=goal.id,
            thesis_id=thesis_id,
            revenue_yoy=metrics["revenue"],
            net_income_yoy=metrics["net_income"],
            operating_income_yoy=metrics["operating_income"],
            operating_cash_flow_yoy=metrics["operating_cash_flow"],
            diluted_eps_yoy=metrics["eps_diluted"],
            cashflow_quality=_cashflow_quality(metrics),
            guidance_tone=GuidanceTone.UNKNOWN,
            beat_miss_summary=_beat_miss_summary(score, metrics, warnings),
            source_summary=evidence_text,
            thesis_delta=thesis_delta,
            action_bias=action_bias,
            evidence_hash=evidence_hash,
            score=score,
            warnings=warnings,
        )
        stored = self.store.create_earnings_review(review)
        self._summarize_goal(goal.id, stored)
        return stored

    def apply_to_thesis(
        self,
        review_id: str,
        *,
        thesis_id: str | None = None,
        human_confirmed: bool = False,
    ):
        review = self.require_review(review_id)
        target_thesis_id = thesis_id or review.thesis_id or self._linked_thesis_id(review)
        if not target_thesis_id:
            raise ValueError("earnings review is not linked to a thesis")
        if _requires_human_confirmation(review) and not human_confirmed:
            raise ValueError("human confirmation required before applying severe earnings review thesis delta")
        return ThesisTrackerService(self.store).add_update(
            target_thesis_id,
            ThesisUpdateCreate(
                research_goal_id=review.research_goal_id,
                evidence_hash=review.evidence_hash,
                impact=_thesis_impact(review.thesis_delta),
                summary=f"Earnings review {review.period}: {review.beat_miss_summary}",
                action_bias=_thesis_action_bias(review.action_bias),
            ),
        )

    def require_review(self, review_id: str) -> EarningsReview:
        review = self.store.get_earnings_review(review_id)
        if not review:
            raise ValueError(f"earnings review not found: {review_id}")
        return review

    def _find_fundamentals(self, symbol: str) -> FundamentalSnapshot | None:
        snapshot = self.store.get_fundamentals(symbol)
        if snapshot:
            return snapshot
        ticker = external_ticker(symbol)
        return next((item for item in self.store.list_fundamentals() if external_ticker(item.symbol) == ticker), None)

    def _get_or_create_goal(self, symbol: str, goal_id: str | None):
        service = ResearchGoalService(self.store)
        if goal_id:
            goal = service.require_goal(goal_id)
            if goal.symbol and goal.symbol != symbol:
                raise ValueError(f"research goal symbol {goal.symbol} does not match earnings review symbol {symbol}")
            return goal
        return service.create_goal(
            ResearchGoalCreate(
                symbol=symbol,
                objective=f"Review {symbol} earnings fundamentals before any post-event proposal is created.",
                claims=[f"{symbol} latest SEC companyfacts snapshot changes thesis context."],
                criteria=[
                    "Attach source-verified SEC/companyfacts evidence.",
                    "Compute deterministic YoY metrics and thesis delta.",
                    "Keep output research-only; do not approve or execute trades.",
                ],
            )
        )

    def _summarize_goal(self, goal_id: str, review: EarningsReview) -> None:
        goal = ResearchGoalService(self.store).require_goal(goal_id)
        goal.summary = (
            f"earnings review created: {review.thesis_delta.value}; "
            f"score={review.score}; evidence_hash={review.evidence_hash[:12]}"
        )
        self.store.update_research_goal(goal, "earnings_review_goal_updated")

    def _linked_thesis_id(self, review: EarningsReview) -> str | None:
        catalyst = self.store.get_catalyst(review.catalyst_id) if review.catalyst_id else None
        return catalyst.linked_thesis_id if catalyst else None


def _earnings_metrics(snapshot: FundamentalSnapshot) -> dict[str, float | None]:
    return {
        "revenue": _metric_yoy(snapshot, "revenue"),
        "net_income": _metric_yoy(snapshot, "net_income"),
        "operating_income": _metric_yoy(snapshot, "operating_income"),
        "operating_cash_flow": _metric_yoy(snapshot, "operating_cash_flow"),
        "eps_diluted": _metric_yoy(snapshot, "eps_diluted"),
    }


def _score_metrics(metrics: dict[str, float | None]) -> tuple[int, list[str]]:
    score = 0
    warnings: list[str] = []
    for name in ("revenue", "net_income", "operating_cash_flow", "eps_diluted"):
        value = metrics.get(name)
        if value is None:
            warnings.append(f"{name} YoY is unavailable")
            continue
        if value > POSITIVE_YOY_THRESHOLD:
            score += 1
        elif value < NEGATIVE_YOY_THRESHOLD:
            score -= 1

    net_income = metrics.get("net_income")
    operating_cash_flow = metrics.get("operating_cash_flow")
    if net_income is not None and operating_cash_flow is not None:
        if net_income > POSITIVE_YOY_THRESHOLD and operating_cash_flow < NEGATIVE_YOY_THRESHOLD:
            score -= 1
            warnings.append("net income improved while operating cash flow deteriorated")
        if operating_cash_flow < net_income - 25:
            warnings.append("operating cash flow materially lagged net income")
    return score, warnings


def _thesis_delta(score: int, warnings: list[str]) -> CatalystThesisDelta:
    if score >= 2:
        return CatalystThesisDelta.STRENGTHENS
    if score <= -3:
        return CatalystThesisDelta.INVALIDATES
    if score <= -1 or any("operating cash flow materially lagged" in warning for warning in warnings):
        return CatalystThesisDelta.WEAKENS
    return CatalystThesisDelta.NEUTRAL


def _action_bias(delta: CatalystThesisDelta) -> CatalystActionBias:
    if delta == CatalystThesisDelta.INVALIDATES:
        return CatalystActionBias.BLOCK_NEW_PROPOSAL
    if delta == CatalystThesisDelta.WEAKENS:
        return CatalystActionBias.WATCH_ONLY
    return CatalystActionBias.NO_CHANGE


def _cashflow_quality(metrics: dict[str, float | None]) -> CashflowQuality:
    net_income = metrics.get("net_income")
    operating_cash_flow = metrics.get("operating_cash_flow")
    if operating_cash_flow is None:
        return CashflowQuality.UNKNOWN
    if net_income is None:
        return CashflowQuality.HEALTHY if operating_cash_flow > POSITIVE_YOY_THRESHOLD else CashflowQuality.MIXED
    if operating_cash_flow > 0 and operating_cash_flow >= net_income - OCF_QUALITY_TOLERANCE:
        return CashflowQuality.HEALTHY
    if operating_cash_flow < NEGATIVE_YOY_THRESHOLD:
        return CashflowQuality.WEAK
    return CashflowQuality.MIXED


def _beat_miss_summary(score: int, metrics: dict[str, float | None], warnings: list[str]) -> str:
    metric_text = ", ".join(
        f"{name} YoY {_format_pct(value)}" for name, value in metrics.items() if value is not None
    )
    warning_text = f"; warnings: {'; '.join(warnings)}" if warnings else ""
    return f"Deterministic earnings score {score}; {metric_text or 'no YoY metrics available'}{warning_text}."


def _source_summary(
    symbol: str,
    snapshot: FundamentalSnapshot,
    score: int,
    metrics: dict[str, float | None],
    warnings: list[str],
) -> str:
    entity = snapshot.entity_name or symbol
    return f"SEC companyfacts earnings snapshot for {entity}: {_beat_miss_summary(score, metrics, warnings)}"


def _period(snapshot: FundamentalSnapshot) -> str:
    metric = _primary_metric(snapshot)
    if not metric:
        return "unknown"
    if metric.fiscal_year and metric.fiscal_period:
        return f"FY{metric.fiscal_year} {metric.fiscal_period}"
    return metric.end_date or "unknown"


def _primary_metric(snapshot: FundamentalSnapshot) -> FundamentalMetric | None:
    for name in ("revenue", "net_income", "operating_cash_flow", "eps_diluted"):
        metric = snapshot.metrics.get(name)
        if metric:
            return metric
    return next(iter(snapshot.metrics.values()), None)


def _latest_filed_at(snapshot: FundamentalSnapshot):
    filed_dates = [metric.filed_at for metric in snapshot.metrics.values() if metric.filed_at]
    return max(filed_dates) if filed_dates else snapshot.updated_at


def _metric_yoy(snapshot: FundamentalSnapshot, metric_name: str) -> float | None:
    metric = snapshot.metrics.get(metric_name)
    return metric.yoy_change_pct if metric else None


def _format_pct(value: float | None) -> str:
    return "n/a" if value is None else f"{value:+.2f}%"


def _requires_human_confirmation(review: EarningsReview) -> bool:
    return review.thesis_delta == CatalystThesisDelta.INVALIDATES or review.action_bias in {
        CatalystActionBias.TRIM,
        CatalystActionBias.EXIT,
        CatalystActionBias.BLOCK_NEW_PROPOSAL,
    }


def _thesis_impact(delta: CatalystThesisDelta) -> ThesisImpact:
    mapping = {
        CatalystThesisDelta.STRENGTHENS: ThesisImpact.STRENGTHENS,
        CatalystThesisDelta.WEAKENS: ThesisImpact.WEAKENS,
        CatalystThesisDelta.NEUTRAL: ThesisImpact.NEUTRAL,
        CatalystThesisDelta.INVALIDATES: ThesisImpact.INVALIDATES,
        CatalystThesisDelta.UNKNOWN: ThesisImpact.NEUTRAL,
    }
    return mapping[delta]


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
