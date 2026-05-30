from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .advice_readiness import AdviceReadinessService
from .config import Settings
from .market_regime import MarketRegimeService
from .models import (
    CatalystExpectedImpact,
    CatalystStatus,
    FundamentalSnapshot,
    InvestorCommitteeRun,
    InvestorCommitteeStance,
    InvestorCommitteeVote,
    InvestorFrameworkProfile,
    ProposalBias,
    RiskAppetite,
    RunCardActor,
    RunCardTriggerSource,
    RunCardType,
    Signal,
    SignalSide,
    utc_now,
)
from .run_cards import RunCardService, stable_hash
from .signal_outcomes import SignalOutcomeEvaluator
from .store import Store


INVESTOR_FRAMEWORK_PROFILE_VERSION = "investor_framework_profiles_v1"
INVESTOR_COMMITTEE_RULE_VERSION = "investor_framework_committee_v1"


@dataclass(frozen=True)
class _ProfileSpec:
    key: str
    name: str
    description: str
    theory_notes: tuple[str, ...]
    weight: float = 1.0


PROFILE_SPECS = (
    _ProfileSpec(
        "quality_value",
        "Quality Value",
        "Looks for durable economics, cash generation, reasonable valuation, and margin of safety.",
        ("Inspired by quality and value investing theory.", "Does not represent or impersonate any real investor."),
    ),
    _ProfileSpec(
        "deep_value",
        "Deep Value",
        "Looks for severe mispricing, downside protection, and asset or earnings support.",
        ("Inspired by public deep-value frameworks.", "Does not represent or impersonate any real investor."),
    ),
    _ProfileSpec(
        "growth_quality",
        "Growth Quality",
        "Looks for durable growth, improving fundamentals, and strong evidence of compounding.",
        ("Inspired by growth-quality analysis.", "Does not represent or impersonate any real investor."),
    ),
    _ProfileSpec(
        "canslim_momentum",
        "CANSLIM Momentum",
        "Looks for earnings growth, price momentum, leadership, and market regime alignment.",
        ("Inspired by public momentum and CANSLIM-style concepts.", "Does not represent or impersonate any real investor."),
    ),
    _ProfileSpec(
        "macro_liquidity",
        "Macro Liquidity",
        "Looks at risk appetite, liquidity proxies, rates, and broad market conditions.",
        ("Inspired by macro liquidity frameworks.", "Does not represent or impersonate any real investor."),
    ),
    _ProfileSpec(
        "risk_cycle",
        "Risk Cycle",
        "Looks for where the idea sits in the risk cycle and whether exposure should expand or contract.",
        ("Inspired by cycle-aware risk management.", "Does not represent or impersonate any real investor."),
    ),
    _ProfileSpec(
        "diversification_pm",
        "Diversification PM",
        "Evaluates position sizing, concentration, portfolio fit, and correlation risk.",
        ("Inspired by portfolio management practice.", "Does not represent or impersonate any real investor."),
    ),
    _ProfileSpec(
        "index_skeptic",
        "Index Skeptic",
        "Challenges whether the signal has enough edge versus broad ETF alternatives such as SPY or QQQ.",
        ("Inspired by benchmark-aware portfolio thinking.", "Does not represent or impersonate any real investor."),
    ),
    _ProfileSpec(
        "evidence_auditor",
        "Evidence Auditor",
        "Checks source quality, missing evidence, research gate status, and whether claims are verified.",
        ("Inspired by audit and evidence-led research practice.", "Does not represent or impersonate any real investor."),
        weight=1.25,
    ),
    _ProfileSpec(
        "execution_skeptic",
        "Execution Skeptic",
        "Checks sizing, entry quality, catalyst proximity, liquidity, and whether promotion should be blocked.",
        ("Inspired by execution risk review.", "Does not represent or impersonate any real investor."),
        weight=1.25,
    ),
)


class InvestorFrameworkCommitteeService:
    def __init__(self, settings: Settings, store: Store):
        self.settings = settings
        self.store = store

    def ensure_default_profiles(self) -> list[InvestorFrameworkProfile]:
        existing = {item.framework_key: item for item in self.store.list_investor_framework_profiles()}
        profiles: list[InvestorFrameworkProfile] = []
        for spec in PROFILE_SPECS:
            current = existing.get(spec.key)
            profile = InvestorFrameworkProfile(
                framework_key=spec.key,
                name=spec.name,
                description=spec.description,
                theory_notes=list(spec.theory_notes),
                weight=current.weight if current else spec.weight,
                enabled=current.enabled if current else True,
                version=INVESTOR_FRAMEWORK_PROFILE_VERSION,
                created_at=current.created_at if current else utc_now(),
                updated_at=utc_now(),
            )
            profiles.append(self.store.upsert_investor_framework_profile(profile))
        return profiles

    def run_for_signal(self, signal_id: str) -> InvestorCommitteeRun:
        signal = self.store.get_signal(signal_id)
        if not signal:
            raise ValueError(f"signal not found: {signal_id}")
        profiles = [item for item in self.ensure_default_profiles() if item.enabled]
        data_pack = self._build_data_pack(signal)
        data_pack_hash = stable_hash(data_pack)
        run = InvestorCommitteeRun(
            signal_id=signal.id,
            symbol=signal.symbol,
            base_signal_score=signal.score,
            committee_adjusted_score=float(signal.score),
            final_stance="neutral",
            actionability_status="research_only",
            data_pack_json=data_pack,
            data_pack_hash=data_pack_hash,
            readiness_score=_nested_float(data_pack, ("readiness", "score")),
            outcome_summary_json=data_pack.get("outcome_summary", {}),
            profile_version=INVESTOR_FRAMEWORK_PROFILE_VERSION,
        )
        votes = [self._vote(profile, signal, data_pack, run.id) for profile in profiles]
        aggregate = self._aggregate(signal, profiles, votes)
        run = run.model_copy(
            update={
                "committee_adjusted_score": aggregate["committee_adjusted_score"],
                "final_stance": aggregate["final_stance"],
                "actionability_status": aggregate["actionability_status"],
                "committee_blocked": aggregate["committee_blocked"],
                "vetoes": aggregate["vetoes"],
                "missing_evidence": aggregate["missing_evidence"],
                "votes": votes,
            }
        )
        run_card = RunCardService(self.store).start_run(
            RunCardType.INVESTOR_COMMITTEE,
            title=f"Investor Framework Committee: {signal.symbol}",
            symbol=signal.symbol,
            actor=RunCardActor.CLI,
            trigger_source=RunCardTriggerSource.MANUAL,
            rule_version=INVESTOR_COMMITTEE_RULE_VERSION,
            inputs={"signal_id": signal.id},
            dataset=data_pack,
            assumptions={
                "all_personas_read_same_frozen_data_pack": True,
                "personas_are_frameworks_not_real_people": True,
                "cannot_browse_freely": True,
                "cannot_create_new_facts": True,
                "cannot_create_proposals": True,
                "cannot_approve_or_execute": True,
            },
        )
        stored = self.store.create_investor_committee_run(run.model_copy(update={"run_card_id": run_card.id}))
        RunCardService(self.store).complete_run(
            run_card.id,
            metrics={
                "base_signal_score": stored.base_signal_score,
                "committee_adjusted_score": stored.committee_adjusted_score,
                "vote_count": len(stored.votes),
                "veto_count": len(stored.vetoes),
                "committee_blocked": stored.committee_blocked,
            },
            warnings=stored.vetoes + stored.missing_evidence,
            outputs={
                "investor_committee_run_id": stored.id,
                "final_stance": stored.final_stance,
                "actionability_status": stored.actionability_status,
            },
            dataset=data_pack,
        )
        return stored

    def latest(self) -> InvestorCommitteeRun | None:
        return self.store.get_latest_investor_committee_run()

    def _build_data_pack(self, signal: Signal) -> dict[str, Any]:
        readiness = AdviceReadinessService(self.settings, self.store).run()
        outcome_summary = SignalOutcomeEvaluator(self.settings, self.store).summary(limit=200)
        market_regime = MarketRegimeService(self.settings, self.store).build_snapshot()
        portfolio = self.store.get_portfolio()
        research_goal = self.store.get_research_goal(signal.research_goal_id) if signal.research_goal_id else None
        thesis = self.store.get_thesis(signal.thesis_id) if signal.thesis_id else self.store.get_active_thesis_for_symbol(signal.symbol)
        fundamentals = self.store.get_fundamentals(signal.symbol) or _equivalent_fundamentals(self.store.list_fundamentals(), signal.symbol)
        news = self.store.list_news(limit=12, symbol=signal.symbol)
        catalysts = self.store.list_catalysts(symbol=signal.symbol, limit=10)
        price_bars = self.store.list_price_bars(symbol=signal.symbol, limit=80, ascending=False)
        return {
            "frozen_at": utc_now().isoformat(),
            "signal": signal.model_dump(mode="json"),
            "evidence": _evidence_rows(signal, research_goal),
            "counter_evidence": signal.counter_evidence,
            "gates": signal.gates,
            "readiness": readiness,
            "outcome_summary": outcome_summary,
            "market_regime": market_regime.model_dump(mode="json"),
            "portfolio": portfolio.model_dump(mode="json"),
            "thesis": thesis.model_dump(mode="json") if thesis else None,
            "fundamentals": fundamentals.model_dump(mode="json") if fundamentals else None,
            "news": [item.model_dump(mode="json") for item in news],
            "catalysts": [item.model_dump(mode="json") for item in catalysts],
            "price_bars": [item.model_dump(mode="json") for item in price_bars],
            "side_effects": {"proposal_created": False, "proposal_approved": False, "trade_executed": False},
        }

    def _vote(
        self,
        profile: InvestorFrameworkProfile,
        signal: Signal,
        data_pack: dict[str, Any],
        run_id: str,
    ) -> InvestorCommitteeVote:
        fn = getattr(self, f"_vote_{profile.framework_key}", self._vote_neutral)
        payload = fn(signal, data_pack)
        return InvestorCommitteeVote(
            run_id=run_id,
            signal_id=signal.id,
            framework_key=profile.framework_key,
            stance=InvestorCommitteeStance(payload["stance"]),
            score_delta=int(max(-15, min(15, payload["score_delta"]))),
            confidence=float(max(0.0, min(1.0, payload["confidence"]))),
            veto=bool(payload.get("veto", False)),
            cited_evidence_ids=payload.get("cited_evidence_ids", []),
            missing_evidence=payload.get("missing_evidence", []),
            memo=payload["memo"],
        )

    def _aggregate(
        self,
        signal: Signal,
        profiles: list[InvestorFrameworkProfile],
        votes: list[InvestorCommitteeVote],
    ) -> dict[str, Any]:
        weights = {profile.framework_key: profile.weight for profile in profiles}
        total_weight = sum(weights.get(vote.framework_key, 1.0) for vote in votes) or 1.0
        weighted_delta = sum(vote.score_delta * weights.get(vote.framework_key, 1.0) for vote in votes) / total_weight
        missing = sorted({item for vote in votes for item in vote.missing_evidence})
        vetoes = [vote.framework_key for vote in votes if vote.veto]
        veto_penalty = 25 if vetoes else 0
        missing_penalty = min(12, len(missing) * 2)
        adjusted = round(max(0.0, min(100.0, signal.score + weighted_delta - veto_penalty - missing_penalty)), 2)
        evidence_veto = any(vote.framework_key == "evidence_auditor" and vote.veto for vote in votes)
        execution_veto = any(vote.framework_key == "execution_skeptic" and vote.veto for vote in votes)
        if evidence_veto or execution_veto or vetoes:
            final_stance = "blocked"
            actionability_status = "committee_blocked"
        elif missing:
            final_stance = "research_more"
            actionability_status = "research_more"
        elif adjusted < self.settings.signal_watch_threshold:
            final_stance = "research_more"
            actionability_status = "research_more"
        elif adjusted < _directional_threshold(self.settings, signal):
            final_stance = "watch"
            actionability_status = "watch"
        elif any(vote.stance in {InvestorCommitteeStance.OPPOSE, InvestorCommitteeStance.RESEARCH_MORE} for vote in votes):
            final_stance = "support_with_caution"
            actionability_status = "committee_supported_with_caution"
        else:
            final_stance = "support"
            actionability_status = "committee_supported"
        return {
            "committee_adjusted_score": adjusted,
            "final_stance": final_stance,
            "actionability_status": actionability_status,
            "committee_blocked": actionability_status == "committee_blocked",
            "vetoes": vetoes,
            "missing_evidence": missing,
        }

    def _vote_quality_value(self, signal: Signal, data_pack: dict[str, Any]) -> dict[str, Any]:
        strength = _fundamental_strength(data_pack.get("fundamentals"))
        gate_passed = _research_gate_passed(signal)
        if strength >= 2 and gate_passed:
            return _payload("support", 10, 0.75, "Strong fundamentals support the signal within the evidence gate.", data_pack)
        if strength >= 2:
            return _payload(
                "support_with_caution",
                3,
                0.55,
                "Fundamentals look strong, but this framework cannot override a failed evidence gate.",
                data_pack,
                missing=["passed research evidence gate"],
            )
        return _payload("neutral", 0, 0.45, "Quality/value evidence is not strong enough to move the signal.", data_pack)

    def _vote_deep_value(self, signal: Signal, data_pack: dict[str, Any]) -> dict[str, Any]:
        fundamentals = data_pack.get("fundamentals") or {}
        metrics = fundamentals.get("metrics") or {}
        cash_flow = _metric_yoy(metrics, "operating_cash_flow")
        if cash_flow is not None and cash_flow > 15 and signal.score >= 60:
            return _payload("support_with_caution", 4, 0.5, "Cash-flow improvement gives some valuation support, but valuation data is incomplete.", data_pack)
        return _payload("research_more", -2, 0.45, "No asset value, valuation multiple, or margin-of-safety evidence is available.", data_pack, missing=["valuation evidence"])

    def _vote_growth_quality(self, signal: Signal, data_pack: dict[str, Any]) -> dict[str, Any]:
        strength = _fundamental_strength(data_pack.get("fundamentals"))
        news_count = len(data_pack.get("news") or [])
        if strength >= 2 and news_count:
            return _payload("support", 8, 0.7, "Growth and quality evidence are aligned with fresh local news.", data_pack)
        if news_count:
            return _payload("support_with_caution", 2, 0.5, "There is fresh news, but growth-quality confirmation is incomplete.", data_pack)
        return _payload("research_more", -3, 0.45, "Growth-quality framework needs fresher growth evidence.", data_pack, missing=["growth-quality evidence"])

    def _vote_canslim_momentum(self, signal: Signal, data_pack: dict[str, Any]) -> dict[str, Any]:
        features = signal.feature_breakdown or {}
        momentum = float(features.get("price_momentum") or 0) + float(features.get("news_catalyst") or 0)
        defensive = _defensive_regime(data_pack)
        if momentum >= 25 and not defensive:
            return _payload("support", 9, 0.72, "Momentum and catalyst scores are strong in a usable market regime.", data_pack)
        if momentum >= 25 and defensive:
            return _payload("neutral", -5, 0.65, "Momentum is strong, but defensive market regime downgrades the signal.", data_pack)
        return _payload("neutral", 0, 0.45, "Momentum evidence is not decisive.", data_pack)

    def _vote_macro_liquidity(self, signal: Signal, data_pack: dict[str, Any]) -> dict[str, Any]:
        if _defensive_regime(data_pack):
            return _payload("oppose", -8, 0.65, "Macro liquidity/risk appetite is defensive; avoid expanding risk.", data_pack)
        return _payload("support_with_caution", 3, 0.55, "Macro regime is not blocking, but this is not a standalone buy/sell reason.", data_pack)

    def _vote_risk_cycle(self, signal: Signal, data_pack: dict[str, Any]) -> dict[str, Any]:
        risk_penalty = float((signal.feature_breakdown or {}).get("risk_penalty") or 0)
        if risk_penalty <= -10 or _defensive_regime(data_pack):
            return _payload("oppose", -7, 0.65, "Risk-cycle evidence argues against increasing exposure now.", data_pack)
        return _payload("neutral", 1, 0.5, "Risk cycle does not materially alter the signal.", data_pack)

    def _vote_diversification_pm(self, signal: Signal, data_pack: dict[str, Any]) -> dict[str, Any]:
        portfolio_fit = float((signal.feature_breakdown or {}).get("portfolio_fit") or 0)
        if portfolio_fit < 0:
            return _payload("oppose", -6, 0.65, "Portfolio fit is weak or concentration risk is elevated.", data_pack)
        return _payload("support_with_caution", 3, 0.55, "Position sizing appears compatible with portfolio fit, subject to gates.", data_pack)

    def _vote_index_skeptic(self, signal: Signal, data_pack: dict[str, Any]) -> dict[str, Any]:
        by_side = ((data_pack.get("outcome_summary") or {}).get("by_side") or {}).get(signal.side.value) or {}
        excess = by_side.get("avg_directional_excess_return_pct")
        if excess is not None and float(excess) <= 0:
            return _payload("oppose", -8, 0.7, "Recent same-side signal outcomes show weak edge versus SPY/QQQ.", data_pack)
        if excess is None and signal.score < 75:
            return _payload("research_more", -4, 0.55, "No outcome edge versus SPY/QQQ is proven for this side.", data_pack, missing=["benchmark edge evidence"])
        return _payload("neutral", 0, 0.5, "Benchmark edge is not disproven.", data_pack)

    def _vote_evidence_auditor(self, signal: Signal, data_pack: dict[str, Any]) -> dict[str, Any]:
        gate = (signal.gates or {}).get("research_gate") or {}
        if not gate.get("passed") or int(gate.get("verified_count") or 0) <= 0:
            return _payload(
                "veto",
                -15,
                0.9,
                "Evidence auditor veto: verified source evidence or research gate is insufficient.",
                data_pack,
                veto=True,
                missing=["verified primary-source/fundamental evidence", "passed research evidence gate"],
            )
        return _payload("support", 6, 0.75, "Evidence gate passed with verified evidence.", data_pack)

    def _vote_execution_skeptic(self, signal: Signal, data_pack: dict[str, Any]) -> dict[str, Any]:
        blockers = [str(item) for item in (signal.gates.get("blocking_reasons") or [])]
        catalyst_block = any("catalyst" in item.lower() for item in blockers)
        sizing_block = "price exceeds paper notional budget" in blockers or (
            signal.side in {SignalSide.BUY_SIGNAL, SignalSide.ADD_SIGNAL, SignalSide.BLOCKED}
            and signal.gates.get("blocked_action") in {SignalSide.BUY_SIGNAL.value, SignalSide.ADD_SIGNAL.value}
            and signal.suggested_qty <= 0
        )
        high_catalyst = any(
            item.get("status") == CatalystStatus.UPCOMING.value
            and item.get("expected_impact") == CatalystExpectedImpact.HIGH.value
            for item in data_pack.get("catalysts", [])
        )
        if sizing_block:
            return _payload("veto", -15, 0.95, "Execution skeptic veto: price exceeds paper notional budget.", data_pack, veto=True)
        if catalyst_block or high_catalyst:
            return _payload("veto", -12, 0.85, "Execution skeptic veto: catalyst or entry-timing risk blocks promotion.", data_pack, veto=True)
        if signal.suggested_limit_price is None:
            return _payload("research_more", -6, 0.65, "No executable paper limit price is available.", data_pack, missing=["entry price"])
        return _payload("support_with_caution", 3, 0.65, "Execution checks do not block promotion, but human approval is still required.", data_pack)

    def _vote_neutral(self, signal: Signal, data_pack: dict[str, Any]) -> dict[str, Any]:
        return _payload("neutral", 0, 0.5, "Framework has no deterministic adjustment.", data_pack)


def _payload(
    stance: str,
    score_delta: int,
    confidence: float,
    memo: str,
    data_pack: dict[str, Any],
    *,
    veto: bool = False,
    missing: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "framework_key": "",
        "stance": stance,
        "score_delta": score_delta,
        "confidence": confidence,
        "veto": veto,
        "cited_evidence_ids": _cited_evidence_ids(data_pack),
        "missing_evidence": missing or [],
        "memo": memo,
    }


def _evidence_rows(signal: Signal, research_goal) -> list[dict[str, Any]]:
    rows = []
    if research_goal:
        rows.extend(
            {
                "id": item.id,
                "source_type": item.source_type,
                "source_verified": item.source_verified,
                "verification_status": item.verification_status,
                "text": item.text,
            }
            for item in research_goal.evidence
        )
    rows.extend({"id": f"signal_evidence_{index}", "text": text} for index, text in enumerate(signal.evidence))
    return rows


def _cited_evidence_ids(data_pack: dict[str, Any]) -> list[str]:
    return [str(item.get("id")) for item in (data_pack.get("evidence") or [])[:5] if item.get("id")]


def _equivalent_fundamentals(items: list[FundamentalSnapshot], symbol: str) -> FundamentalSnapshot | None:
    normalized = symbol.upper().split(".", 1)[-1]
    for item in items:
        if item.symbol.upper().split(".", 1)[-1] == normalized:
            return item
    return None


def _metric_yoy(metrics: dict[str, Any], name: str) -> float | None:
    metric = metrics.get(name)
    if not metric:
        return None
    if isinstance(metric, dict):
        value = metric.get("yoy_change_pct")
    else:
        value = getattr(metric, "yoy_change_pct", None)
    return float(value) if value is not None else None


def _fundamental_strength(fundamentals: dict[str, Any] | None) -> int:
    if not fundamentals:
        return 0
    metrics = fundamentals.get("metrics") or {}
    positives = 0
    for name in ("revenue", "net_income", "operating_cash_flow", "eps_diluted"):
        yoy = _metric_yoy(metrics, name)
        if yoy is not None and yoy > 5:
            positives += 1
    return positives


def _research_gate_passed(signal: Signal) -> bool:
    gate = (signal.gates or {}).get("research_gate") or {}
    return bool(gate.get("passed")) and int(gate.get("verified_count") or 0) > 0


def _defensive_regime(data_pack: dict[str, Any]) -> bool:
    regime = data_pack.get("market_regime") or {}
    return regime.get("proposal_bias") in {ProposalBias.DEFENSIVE_ONLY.value, ProposalBias.CAUTION.value} or regime.get(
        "risk_appetite"
    ) == RiskAppetite.RISK_OFF.value


def _directional_threshold(settings: Settings, signal: Signal) -> int:
    action = signal.gates.get("blocked_action") or signal.side.value
    if action in {SignalSide.SELL_SIGNAL.value, SignalSide.REDUCE_SIGNAL.value}:
        return settings.signal_sell_threshold
    return settings.signal_buy_threshold


def _nested_float(payload: dict[str, Any], path: tuple[str, ...]) -> float | None:
    current: Any = payload
    for key in path:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    try:
        return float(current)
    except (TypeError, ValueError):
        return None
