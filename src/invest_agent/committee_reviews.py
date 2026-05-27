from __future__ import annotations

import re
from typing import Any

from .config import Settings, get_settings
from .market_context import MarketContextService
from .market_news import economic_exposure_ticker, external_ticker
from .market_regime import MarketRegimeService
from .models import (
    CatalystExpectedImpact,
    CatalystStatus,
    CommitteeConclusion,
    CommitteeFindingSeverity,
    CommitteeFindingType,
    CommitteeMemberRole,
    CommitteeReview,
    CommitteeReviewRunRequest,
    CreatedVia,
    ProposalBias,
    RunCardActor,
    RunCardTriggerSource,
    RunCardType,
    ThesisStatus,
    utc_now,
)
from .run_cards import RunCardService, stable_hash
from .store import Store


COMMITTEE_REVIEW_RULE_VERSION = "committee_review_v2"
TECH_EXPOSURE_TICKERS = {"AAPL", "AMD", "GOOG", "GOOGL", "META", "MSFT", "NVDA", "QQQ", "QQQM", "SMH", "SOXX"}
SYMBOL_STOP_WORDS = {
    "AI",
    "API",
    "BUY",
    "ETF",
    "FULL",
    "IPO",
    "MCP",
    "SEC",
    "SELL",
    "THE",
    "US",
}


class CommitteeReviewService:
    def __init__(self, store: Store, *, settings: Settings | None = None):
        self.store = store
        self.settings = settings or get_settings()

    def run_review(
        self,
        request: CommitteeReviewRunRequest,
        *,
        actor: RunCardActor | str = RunCardActor.API,
    ) -> CommitteeReview:
        symbols = _symbols_from_request(request)
        data_pack = self._build_data_pack(request, symbols)
        data_pack_hash = stable_hash(data_pack)
        missing = _clean_list([*request.missing_evidence, *data_pack["missing_evidence"]])
        findings = self._build_findings(data_pack, missing)
        members = self._build_members(data_pack, findings)
        conclusion = self._decision(request.conclusion, missing, findings, data_pack)
        output = {
            "conclusion": conclusion.value,
            "members": members,
            "findings": findings,
            "missing_evidence": missing,
        }
        output_hash = stable_hash(output)

        run_card = RunCardService(self.store).start_run(
            RunCardType.COMMITTEE_REVIEW,
            title=f"Committee Review: {request.topic}",
            symbol=symbols[0] if len(symbols) == 1 else None,
            actor=actor,
            trigger_source=RunCardTriggerSource.MANUAL,
            rule_version=COMMITTEE_REVIEW_RULE_VERSION,
            inputs=request.model_dump(mode="json"),
            dataset=data_pack,
            assumptions={
                "committee_memo_is_research_only": True,
                "committee_memo_cannot_approve": True,
                "cannot_create_pending_proposal_directly": True,
                "cannot_execute_trades": True,
                "members_read_same_frozen_data_pack": True,
            },
            links={"research_goal_id": request.research_goal_id, "proposal_id": request.proposal_id},
        )
        review = CommitteeReview(
            topic=request.topic,
            symbols=symbols,
            review_type=request.review_type,
            proposal_id=request.proposal_id,
            research_goal_id=request.research_goal_id,
            hypothesis_id=request.hypothesis_id,
            bull_case=_member_memo(members, CommitteeMemberRole.BULL_ANALYST) or request.bull_case,
            bear_case=_member_memo(members, CommitteeMemberRole.BEAR_ANALYST) or request.bear_case,
            risk_memo=_member_memo(members, CommitteeMemberRole.RISK_MANAGER) or request.risk_memo,
            missing_evidence=missing,
            conclusion=conclusion,
            data_pack_json=data_pack,
            data_pack_hash=data_pack_hash,
            output_hash=output_hash,
            members_json=members,
            findings_json=findings,
            created_via=_created_via(actor, request.created_via),
            run_card_id=run_card.id,
            completed_at=utc_now(),
        )
        stored = self.store.create_committee_review(review)
        RunCardService(self.store).complete_run(
            run_card.id,
            metrics={
                "symbol_count": len(symbols),
                "member_count": len(members),
                "finding_count": len(findings),
                "blocking_finding_count": sum(
                    1 for item in findings if item["severity"] == CommitteeFindingSeverity.BLOCKING.value
                ),
                "missing_evidence_count": len(missing),
                "proposal_created": False,
                "proposal_approved": False,
                "trade_executed": False,
            },
            warnings=missing + [item["text"] for item in findings if item["severity"] == CommitteeFindingSeverity.BLOCKING.value],
            outputs={"committee_review_id": stored.id, "conclusion": stored.conclusion.value, "output_hash": output_hash},
            dataset=data_pack,
            links={"research_goal_id": stored.research_goal_id, "proposal_id": stored.proposal_id},
        )
        return stored

    def _build_data_pack(self, request: CommitteeReviewRunRequest, symbols: list[str]) -> dict[str, Any]:
        portfolio = self.store.get_portfolio()
        context = MarketContextService(self.settings, self.store).build_context()
        regime = MarketRegimeService(self.settings, self.store).build_snapshot()
        research_goal = self.store.get_research_goal(request.research_goal_id) if request.research_goal_id else None
        missing: list[str] = []
        if request.research_goal_id:
            if not research_goal:
                missing.append(f"research goal not found: {request.research_goal_id}")
            elif not research_goal.evidence:
                missing.append("research goal has no evidence rows")

        symbol_packs = [self._symbol_pack(symbol, research_goal, missing) for symbol in symbols]
        portfolio_value = portfolio.total_value_usd or portfolio.cash_usd + sum(item.market_value for item in portfolio.positions)
        tech_value = sum(
            item.market_value
            for item in portfolio.positions
            if economic_exposure_ticker(item.symbol) in TECH_EXPOSURE_TICKERS
        )
        return {
            "topic": request.topic,
            "symbols": symbols,
            "review_type": request.review_type.value,
            "portfolio": {
                "cash_usd": portfolio.cash_usd,
                "total_value_usd": portfolio_value,
                "tech_exposure_weight": tech_value / portfolio_value if portfolio_value else 0.0,
                "positions": [
                    {
                        "symbol": item.symbol,
                        "qty": item.qty,
                        "market_value": item.market_value,
                        "weight": item.market_value / portfolio_value if portfolio_value else 0.0,
                    }
                    for item in portfolio.positions
                ],
            },
            "market_context": context.model_dump(mode="json"),
            "market_regime": regime.model_dump(mode="json"),
            "research_goal": research_goal.model_dump(mode="json") if research_goal else None,
            "symbols_context": symbol_packs,
            "latest_behavior_reports": [
                item.model_dump(mode="json") for item in self.store.list_behavior_reports(limit=3)
            ],
            "latest_shadow_reports": [
                item.model_dump(mode="json") for item in self.store.list_shadow_reports(limit=3)
            ],
            "missing_evidence": missing,
            "side_effects": {
                "proposal_created": False,
                "proposal_approved": False,
                "trade_executed": False,
            },
        }

    def _symbol_pack(self, symbol: str, research_goal, missing: list[str]) -> dict[str, Any]:
        ticker = economic_exposure_ticker(symbol)
        quote = self._quote(symbol)
        position = next(
            (
                item
                for item in self.store.get_portfolio().positions
                if economic_exposure_ticker(item.symbol) == ticker
            ),
            None,
        )
        theses = [
            item
            for item in self.store.list_theses(status=ThesisStatus.ACTIVE, limit=200)
            if economic_exposure_ticker(item.symbol) == ticker
        ]
        catalysts = [
            item
            for item in self.store.list_catalysts(limit=200)
            if item.symbol and economic_exposure_ticker(item.symbol) == ticker
        ]
        fundamentals = next(
            (
                item
                for item in self.store.list_fundamentals()
                if economic_exposure_ticker(item.symbol) == ticker
            ),
            None,
        )
        news = [
            item
            for item in self.store.list_news(limit=100)
            if item.symbol and economic_exposure_ticker(item.symbol) == ticker
        ][:10]
        earnings_reviews = [
            item
            for item in self.store.list_earnings_reviews(limit=100)
            if economic_exposure_ticker(item.symbol) == ticker
        ][:5]
        goals = [
            self.store.get_research_goal(goal.id) or goal
            for goal in self.store.list_research_goals(symbol=symbol, limit=5)
        ]
        goal_evidence = [
            evidence
            for goal in goals
            for evidence in goal.evidence
            if not evidence.symbol or economic_exposure_ticker(evidence.symbol) == ticker
        ]
        if research_goal:
            goal_evidence.extend(
                evidence
                for evidence in research_goal.evidence
                if not evidence.symbol or economic_exposure_ticker(evidence.symbol) == ticker
            )
        source_verified = [item for item in goal_evidence if item.source_verified]
        primary_news = [item for item in news if _is_primary_source(item.source)]
        known = bool(quote or position or theses or catalysts or fundamentals or news or goals)
        if not known:
            missing.append(f"{symbol} is outside local known universe")
        if not source_verified and not fundamentals and not primary_news:
            missing.append(f"{symbol} has no source-verified SEC/IR/companyfacts evidence in local data pack")
        return {
            "symbol": symbol,
            "known_universe_status": "known" if known else "unknown",
            "quote": quote.model_dump(mode="json") if quote else None,
            "position": position.model_dump(mode="json") if position else None,
            "active_theses": [item.model_dump(mode="json") for item in theses],
            "catalysts": [item.model_dump(mode="json") for item in catalysts[:10]],
            "earnings_reviews": [item.model_dump(mode="json") for item in earnings_reviews],
            "fundamentals": fundamentals.model_dump(mode="json") if fundamentals else None,
            "news_digest": [item.model_dump(mode="json") for item in news],
            "research_goals": [goal.model_dump(mode="json") for goal in goals],
            "source_verified_evidence_count": len(source_verified),
            "primary_source_news_count": len(primary_news),
        }

    def _quote(self, symbol: str):
        quote = self.store.get_quote(symbol)
        if quote:
            return quote
        ticker = economic_exposure_ticker(symbol)
        return next(
            (item for item in self.store.list_quotes() if economic_exposure_ticker(item.symbol) == ticker),
            None,
        )

    def _build_findings(self, data_pack: dict[str, Any], missing: list[str]) -> list[dict[str, Any]]:
        findings: list[dict[str, Any]] = []
        for item in data_pack["symbols_context"]:
            symbol = item["symbol"]
            if item["active_theses"]:
                findings.append(_finding(symbol, CommitteeFindingType.BULL_CASE, "Active thesis exists in local data pack."))
            if item["known_universe_status"] == "unknown":
                findings.append(
                    _finding(
                        symbol,
                        CommitteeFindingType.MISSING_EVIDENCE,
                        f"{symbol} is unknown to local universe; committee decision must stay research-only.",
                        CommitteeFindingSeverity.WARNING,
                    )
                )
            if not item["source_verified_evidence_count"] and not item["fundamentals"] and not item["primary_source_news_count"]:
                findings.append(
                    _finding(
                        symbol,
                        CommitteeFindingType.MISSING_EVIDENCE,
                        f"{symbol} has no source-verified SEC/IR/companyfacts evidence.",
                        CommitteeFindingSeverity.WARNING,
                    )
                )
            quote = item.get("quote") or {}
            change_pct = quote.get("change_pct")
            if change_pct is not None and change_pct >= 3:
                findings.append(
                    _finding(
                        symbol,
                        CommitteeFindingType.ENTRY_QUALITY,
                        f"{symbol} is up {change_pct:+.2f}%; entry quality has chasing risk.",
                        CommitteeFindingSeverity.WARNING,
                    )
                )
            for catalyst in item["catalysts"]:
                if (
                    catalyst.get("status") == CatalystStatus.UPCOMING.value
                    and catalyst.get("expected_impact") == CatalystExpectedImpact.HIGH.value
                ):
                    findings.append(
                        _finding(
                            symbol,
                            CommitteeFindingType.RISK,
                            f"{symbol} has upcoming high-impact catalyst; avoid action before review.",
                            CommitteeFindingSeverity.BLOCKING,
                        )
                    )
            position = item.get("position") or {}
            weight = position.get("market_value", 0) / data_pack["portfolio"]["total_value_usd"] if data_pack["portfolio"]["total_value_usd"] else 0
            if weight >= 0.2:
                findings.append(
                    _finding(
                        symbol,
                        CommitteeFindingType.PORTFOLIO_FIT,
                        f"{symbol} already represents {weight:.1%} of portfolio.",
                        CommitteeFindingSeverity.BLOCKING,
                    )
                )

        if data_pack["portfolio"]["tech_exposure_weight"] >= 0.4:
            findings.append(
                _finding(
                    None,
                    CommitteeFindingType.PORTFOLIO_FIT,
                    f"Tech/AI related exposure is {data_pack['portfolio']['tech_exposure_weight']:.1%}; new high-beta tech ideas need stronger evidence.",
                    CommitteeFindingSeverity.WARNING,
                )
            )
        if data_pack["market_regime"].get("proposal_bias") == ProposalBias.DEFENSIVE_ONLY.value:
            findings.append(
                _finding(
                    None,
                    CommitteeFindingType.RISK,
                    "Market regime is defensive_only; committee cannot support new risk-taking.",
                    CommitteeFindingSeverity.BLOCKING,
                )
            )
        for item in missing:
            findings.append(_finding(None, CommitteeFindingType.MISSING_EVIDENCE, item, CommitteeFindingSeverity.WARNING))
        return _dedupe_findings(findings)

    def _build_members(self, data_pack: dict[str, Any], findings: list[dict[str, Any]]) -> list[dict[str, Any]]:
        symbols = ", ".join(data_pack["symbols"]) or "portfolio idea"
        blocking = [item["text"] for item in findings if item["severity"] == CommitteeFindingSeverity.BLOCKING.value]
        missing = [item["text"] for item in findings if item["finding_type"] == CommitteeFindingType.MISSING_EVIDENCE.value]
        risks = [item["text"] for item in findings if item["finding_type"] in {CommitteeFindingType.RISK.value, CommitteeFindingType.ENTRY_QUALITY.value}]
        portfolio = [item["text"] for item in findings if item["finding_type"] == CommitteeFindingType.PORTFOLIO_FIT.value]
        bull_support = [
            item["symbol"]
            for item in data_pack["symbols_context"]
            if item["active_theses"] or item["fundamentals"] or item["source_verified_evidence_count"]
        ]
        return [
            _member(CommitteeMemberRole.BULL_ANALYST, f"{symbols}: bull case is {'present' if bull_support else 'not yet source-backed'} in the frozen data pack.", score=1 if bull_support else 0),
            _member(CommitteeMemberRole.BEAR_ANALYST, "; ".join(missing[:3]) or "No major missing-evidence objection found in the frozen data pack.", warnings=missing[:3], score=-len(missing)),
            _member(CommitteeMemberRole.RISK_MANAGER, "; ".join(risks[:3] + blocking[:2]) or "No blocking risk finding from deterministic checks.", warnings=risks[:3] + blocking[:2], score=-2 * len(blocking) - len(risks)),
            _member(CommitteeMemberRole.PORTFOLIO_MANAGER, "; ".join(portfolio[:3]) or "Portfolio fit does not show a major concentration block.", warnings=portfolio[:3], score=-len(portfolio)),
            _member(CommitteeMemberRole.EVIDENCE_AUDITOR, "; ".join(missing[:3]) or "Evidence coverage is acceptable for research memo purposes.", warnings=missing[:3], score=-len(missing)),
            _member(CommitteeMemberRole.EXECUTION_SKEPTIC, "Even if thesis improves, this memo cannot create a proposal; entry must still pass evidence, catalyst, policy, and human confirmation.", score=0),
        ]

    def _decision(
        self,
        requested: CommitteeConclusion,
        missing: list[str],
        findings: list[dict[str, Any]],
        data_pack: dict[str, Any],
    ) -> CommitteeConclusion:
        if missing and requested == CommitteeConclusion.ELIGIBLE_FOR_PROPOSAL:
            return CommitteeConclusion.RESEARCH_MORE
        if requested not in {CommitteeConclusion.RESEARCH_MORE, CommitteeConclusion.RESEARCH_NEEDED}:
            return requested
        if any(item["severity"] == CommitteeFindingSeverity.BLOCKING.value for item in findings):
            return CommitteeConclusion.BLOCKED
        if any(item["known_universe_status"] == "unknown" for item in data_pack["symbols_context"]):
            return CommitteeConclusion.RESEARCH_NEEDED
        if missing:
            return CommitteeConclusion.RESEARCH_NEEDED
        if any(item["source_verified_evidence_count"] or item["fundamentals"] for item in data_pack["symbols_context"]):
            return CommitteeConclusion.WATCH
        return CommitteeConclusion.INFO_ONLY


def _symbols_from_request(request: CommitteeReviewRunRequest) -> list[str]:
    symbols = list(request.symbols)
    symbols.extend(token for token in re.findall(r"\b[A-Z][A-Z0-9.]{0,5}\b", request.topic) if token not in SYMBOL_STOP_WORDS)
    seen: set[str] = set()
    out: list[str] = []
    for raw in symbols:
        symbol = raw.strip().upper()
        if not symbol or symbol in seen:
            continue
        seen.add(symbol)
        out.append(symbol)
    return out


def _created_via(actor: RunCardActor | str, fallback: CreatedVia) -> CreatedVia:
    value = actor.value if isinstance(actor, RunCardActor) else str(actor)
    if value == RunCardActor.CLI.value:
        return CreatedVia.CLI
    if value == RunCardActor.MCP.value:
        return CreatedVia.MCP
    if value == RunCardActor.API.value:
        return CreatedVia.REST
    return fallback


def _is_primary_source(source: str | None) -> bool:
    text = (source or "").lower()
    return any(token in text for token in ["sec", "edgar", "ir", "investor", "companyfacts", "8-k", "10-q", "10-k"])


def _finding(
    symbol: str | None,
    finding_type: CommitteeFindingType,
    text: str,
    severity: CommitteeFindingSeverity = CommitteeFindingSeverity.INFO,
) -> dict[str, Any]:
    return {
        "symbol": symbol,
        "finding_type": finding_type.value,
        "text": text,
        "severity": severity.value,
    }


def _member(
    role: CommitteeMemberRole,
    memo: str,
    *,
    score: int = 0,
    warnings: list[str] | None = None,
) -> dict[str, Any]:
    return {"role": role.value, "memo": memo, "score": score, "warnings_json": warnings or []}


def _member_memo(members: list[dict[str, Any]], role: CommitteeMemberRole) -> str:
    return next((item["memo"] for item in members if item["role"] == role.value), "")


def _clean_list(values: list[str]) -> list[str]:
    out: list[str] = []
    for item in values:
        value = item.strip()
        if value and value not in out:
            out.append(value)
    return out


def _dedupe_findings(findings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[str | None, str, str]] = set()
    out: list[dict[str, Any]] = []
    for item in findings:
        key = (item.get("symbol"), item["finding_type"], item["text"])
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out
