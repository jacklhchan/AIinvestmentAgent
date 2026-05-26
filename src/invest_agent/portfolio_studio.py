from __future__ import annotations

from .config import Settings
from .market_regime import MarketRegimeService
from .models import (
    PortfolioActionBias,
    PortfolioRiskSnapshot,
    RebalanceAction,
    RebalanceCandidate,
    RebalanceCandidateStatus,
    RebalanceReview,
    ResearchGoalCreate,
    RunCardActor,
    RunCardTriggerSource,
    RunCardType,
)
from .research_goals import ResearchGoalService
from .run_cards import RunCardService
from .store import Store


PORTFOLIO_RISK_RULE_VERSION = "portfolio_risk_v1"
REBALANCE_REVIEW_RULE_VERSION = "rebalance_review_v1"


class PortfolioStudioService:
    def __init__(self, settings: Settings, store: Store):
        self.settings = settings
        self.store = store

    def refresh_risk_snapshot(
        self,
        *,
        actor: RunCardActor | str = RunCardActor.API,
        trigger_source: RunCardTriggerSource | str = RunCardTriggerSource.MANUAL,
    ) -> PortfolioRiskSnapshot:
        portfolio = self.store.get_portfolio()
        regime = MarketRegimeService(self.settings, self.store).build_snapshot()
        targets = self.store.list_portfolio_targets(limit=200)
        classifications = {item.symbol: item for item in self.store.list_symbol_classifications(limit=1000)}
        dataset = {
            "portfolio": portfolio.model_dump(mode="json"),
            "targets": [item.model_dump(mode="json") for item in targets],
            "classifications": [item.model_dump(mode="json") for item in classifications.values()],
            "market_regime": regime.model_dump(mode="json"),
        }
        run_card = RunCardService(self.store).start_run(
            RunCardType.PORTFOLIO_RISK,
            title="Portfolio Risk X-ray",
            actor=actor,
            trigger_source=trigger_source,
            rule_version=PORTFOLIO_RISK_RULE_VERSION,
            inputs={"paper_only": self.settings.is_paper},
            dataset=dataset,
            assumptions={"creates_proposals": False, "rebalance_candidates_are_research_only": True},
        )
        snapshot = _build_snapshot(portfolio, regime, targets, classifications, run_card.id)
        stored = self.store.create_portfolio_risk_snapshot(snapshot)
        RunCardService(self.store).complete_run(
            run_card.id,
            metrics={
                "total_value": stored.total_value,
                "cash_weight": stored.cash_weight,
                "top_5_weight": stored.top_5_weight,
                "warning_count": len(stored.concentration_warnings),
            },
            warnings=stored.concentration_warnings,
            outputs={"portfolio_risk_snapshot_id": stored.id, "drift": stored.drift},
            dataset=dataset,
        )
        return stored

    def run_rebalance_review(
        self,
        *,
        actor: RunCardActor | str = RunCardActor.API,
        trigger_source: RunCardTriggerSource | str = RunCardTriggerSource.MANUAL,
    ) -> RebalanceReview:
        snapshot = self.refresh_risk_snapshot(actor=actor, trigger_source=trigger_source)
        portfolio = self.store.get_portfolio()
        run_card = RunCardService(self.store).start_run(
            RunCardType.REBALANCE_REVIEW,
            title="Rebalance Review",
            actor=actor,
            trigger_source=trigger_source,
            rule_version=REBALANCE_REVIEW_RULE_VERSION,
            inputs={"snapshot_id": snapshot.id},
            dataset={"portfolio_risk_snapshot": snapshot.model_dump(mode="json")},
            assumptions={"candidates_are_not_proposals": True, "promotion_path": "candidate_to_research_goal_only"},
        )
        risk_notes = list(snapshot.concentration_warnings)
        action_bias = PortfolioActionBias.NO_CHANGE
        candidates: list[RebalanceCandidate] = []
        for drift in snapshot.drift.get("asset_classes", []):
            asset_class = drift["asset_class"]
            if drift["drift"] > 0.05:
                action_bias = PortfolioActionBias.CANDIDATE_REVIEW
                candidates.extend(_trim_candidates(portfolio.positions, asset_class, snapshot.id, "above max allocation band"))
            elif drift["drift"] < -0.05:
                action_bias = PortfolioActionBias.RESEARCH_NEEDED
                risk_notes.append(f"{asset_class} is below target band; create research goals before any add.")
        review = RebalanceReview(
            portfolio_value=snapshot.total_value,
            drift_summary=snapshot.drift,
            risk_notes=risk_notes,
            action_bias=action_bias,
            run_card_id=run_card.id,
        )
        candidates = [candidate.model_copy(update={"review_id": review.id}) for candidate in candidates[:8]]
        stored = self.store.create_rebalance_review(review, candidates)
        RunCardService(self.store).complete_run(
            run_card.id,
            metrics={"candidate_count": len(candidates), "risk_note_count": len(risk_notes)},
            warnings=risk_notes,
            outputs={"rebalance_review_id": stored.id, "action_bias": stored.action_bias.value},
            dataset={"review": stored.model_dump(mode="json")},
        )
        return stored

    def promote_candidate_to_research_goal(self, candidate_id: str) -> RebalanceCandidate:
        candidate = self.store.get_rebalance_candidate(candidate_id)
        if not candidate:
            raise ValueError(f"rebalance candidate not found: {candidate_id}")
        goal = ResearchGoalService(self.store).create_goal(
            ResearchGoalCreate(
                symbol=candidate.symbol,
                objective=f"Research rebalance candidate {candidate.action.value} for {candidate.symbol} before any proposal.",
                claims=[candidate.reason],
                criteria=[
                    "Attach directional and verified evidence before proposal creation.",
                    "Keep rebalance output research-only until evidence gate and policy checks pass.",
                ],
            )
        )
        candidate.status = RebalanceCandidateStatus.PROMOTED_TO_RESEARCH_GOAL
        candidate.linked_research_goal_id = goal.id
        return self.store.update_rebalance_candidate(candidate)


def _build_snapshot(portfolio, regime, targets, classifications, run_card_id: str) -> PortfolioRiskSnapshot:
    total = portfolio.total_value_usd or portfolio.cash_usd + sum(position.market_value for position in portfolio.positions)
    if total <= 0:
        total = 1.0
    sector_exposure: dict[str, float] = {}
    asset_exposure: dict[str, float] = {}
    weighted_positions = sorted(portfolio.positions, key=lambda item: item.market_value, reverse=True)
    for position in portfolio.positions:
        classification = classifications.get(position.symbol)
        sector = classification.sector if classification else "unknown"
        asset_class = classification.asset_class if classification else "equity"
        weight = position.market_value / total
        sector_exposure[sector] = sector_exposure.get(sector, 0.0) + weight
        asset_exposure[asset_class] = asset_exposure.get(asset_class, 0.0) + weight
    cash_weight = max(0.0, portfolio.cash_usd / total)
    asset_exposure["cash"] = asset_exposure.get("cash", 0.0) + cash_weight
    top_5_weight = sum(position.market_value for position in weighted_positions[:5]) / total
    warnings: list[str] = []
    if weighted_positions and weighted_positions[0].market_value / total > 0.35:
        warnings.append(f"{weighted_positions[0].symbol} exceeds 35% of portfolio value.")
    if top_5_weight > 0.8:
        warnings.append("Top 5 positions exceed 80% of portfolio value.")
    if regime.proposal_bias.value in {"caution", "defensive_only"}:
        warnings.append(f"Market regime is {regime.proposal_bias.value}; rebalance review should stay cautious.")
    drift_rows = []
    target_by_class = {target.asset_class: target for target in targets}
    for asset_class, weight in sorted(asset_exposure.items()):
        target = target_by_class.get(asset_class)
        if not target:
            continue
        drift_rows.append(
            {
                "asset_class": asset_class,
                "current_weight": round(weight, 4),
                "target_weight": target.target_weight,
                "min_weight": target.min_weight,
                "max_weight": target.max_weight,
                "drift": round(weight - target.target_weight, 4),
            }
        )
    return PortfolioRiskSnapshot(
        total_value=round(total, 2),
        cash_weight=round(cash_weight, 4),
        top_5_weight=round(top_5_weight, 4),
        sector_exposure={key: round(value, 4) for key, value in sorted(sector_exposure.items())},
        asset_class_exposure={key: round(value, 4) for key, value in sorted(asset_exposure.items())},
        concentration_warnings=warnings,
        drift={"asset_classes": drift_rows},
        regime_context=regime.model_dump(mode="json"),
        run_card_id=run_card_id,
    )


def _trim_candidates(positions, asset_class: str, review_id: str, reason: str) -> list[RebalanceCandidate]:
    result: list[RebalanceCandidate] = []
    for position in sorted(positions, key=lambda item: item.market_value, reverse=True)[:3]:
        result.append(
            RebalanceCandidate(
                review_id=review_id,
                symbol=position.symbol,
                action=RebalanceAction.TRIM,
                reason=f"{asset_class} {reason}; candidate requires research goal before proposal.",
            )
        )
    return result

