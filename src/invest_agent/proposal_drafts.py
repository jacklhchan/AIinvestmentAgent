from __future__ import annotations

from datetime import timedelta

from .config import Settings
from .market_news import economic_exposure_ticker, resolve_watchlist_symbols
from .models import (
    DraftProposalResult,
    FundamentalMetric,
    FundamentalSnapshot,
    NewsItem,
    Position,
    ProposalCreate,
    ProposalDraft,
    Quote,
    ResearchEvidenceCreate,
    Side,
    ThesisPillarStatus,
    ThesisRiskStatus,
    utc_now,
)
from .research_goals import evidence_from_news, research_goal_from_draft
from .services import InvestmentService
from .store import Store


POSITIVE_TERMS = {
    "accelerate",
    "approval",
    "beat",
    "beats",
    "boost",
    "demand",
    "expands",
    "growth",
    "guidance",
    "higher",
    "launch",
    "partnership",
    "record",
    "raises",
    "strong",
    "upgrade",
    "upside",
}

NEGATIVE_TERMS = {
    "cut",
    "cuts",
    "delay",
    "decline",
    "downgrade",
    "falls",
    "lawsuit",
    "miss",
    "misses",
    "probe",
    "recall",
    "risk",
    "slower",
    "weak",
    "warning",
}


class ProposalDraftEngine:
    def __init__(self, settings: Settings, store: Store, service: InvestmentService | None = None):
        self.settings = settings
        self.store = store
        self.service = service or InvestmentService(settings, store)

    def draft_from_watchlist(
        self,
        symbols: list[str] | None = None,
        *,
        lookback_hours: int = 72,
        max_drafts: int | None = None,
        create_proposals: bool = False,
    ) -> DraftProposalResult:
        watchlist = resolve_watchlist_symbols(self.settings, self.store, symbols)
        draft_limit = max_drafts or self.settings.draft_max_candidates
        skipped: list[str] = []
        drafts: list[ProposalDraft] = []

        for symbol in watchlist:
            news = self._recent_news(symbol, lookback_hours=lookback_hours)
            if not news:
                skipped.append(f"{symbol}: no recent market news")
                continue

            score = sum(_score_news(item) for item in news)
            if score == 0:
                skipped.append(f"{symbol}: no directional news score")
                continue

            draft = self._build_draft(symbol, news, score)
            if not draft:
                skipped.append(f"{symbol}: quote or position context insufficient")
                continue
            drafts.append(draft)

        drafts.sort(key=lambda item: (abs(item.score), item.confidence, item.news_count), reverse=True)
        drafts = drafts[:draft_limit]

        created = []
        if create_proposals:
            for draft in drafts:
                if not draft.evidence_gate_passed:
                    skipped.append(f"{draft.symbol}: research evidence gate insufficient before proposal creation")
                    continue
                proposal = self.service.create_proposal(
                    ProposalCreate(
                        symbol=draft.symbol,
                        side=draft.side,
                        qty=draft.qty,
                        limit_price=draft.limit_price,
                        thesis=draft.thesis,
                        trigger=draft.trigger,
                        confidence=draft.confidence,
                        evidence=draft.evidence,
                        counter_evidence=draft.counter_evidence,
                        research_goal_id=draft.research_goal_id,
                        thesis_id=draft.thesis_id,
                    )
                )
                created.append(proposal)

        self.store.audit(
            "proposal_drafts_generated",
            "proposal",
            "watchlist",
            {
                "watchlist": watchlist,
                "draft_count": len(drafts),
                "created_count": len(created),
                "skipped": skipped[:12],
                "create_proposals": create_proposals,
            },
        )

        return DraftProposalResult(watchlist=watchlist, drafts=drafts, created=created, skipped=skipped)

    def _recent_news(self, symbol: str, *, lookback_hours: int) -> list[NewsItem]:
        cutoff = utc_now() - timedelta(hours=max(1, lookback_hours))
        primary_cutoff = utc_now() - timedelta(days=max(1, self.settings.primary_source_lookback_days))
        news = self.store.list_news(limit=30, symbol=symbol)
        ticker = economic_exposure_ticker(symbol)
        return [
            item
            for item in news
            if item.symbol is not None
            and economic_exposure_ticker(item.symbol) == ticker
            and (item.published_at >= cutoff or (_is_primary_source(item) and item.published_at >= primary_cutoff))
        ]

    def _build_draft(self, symbol: str, news: list[NewsItem], score: int) -> ProposalDraft | None:
        quote = self._find_quote(symbol)
        position = self._find_position(symbol)
        last_price = quote.last_price if quote else (position.last_price if position else 0.0)
        if last_price <= 0:
            return None

        side = Side.BUY if score > 0 else Side.SELL
        qty = self._draft_qty(side, last_price, position.qty if position else 0.0)
        if qty < 1:
            return None

        direction = "positive" if score > 0 else "negative"
        signal_items = [item for item in news if _score_news(item) != 0]
        primary_items = [item for item in news if _is_primary_source(item)]
        top_news = signal_items[:3]
        top_primary = [item for item in primary_items[:2] if item.id not in {news_item.id for news_item in top_news}]
        evidence = [_news_reference(item) for item in [*top_news, *top_primary]]
        fundamentals = self._find_fundamentals(symbol)
        fundamental_reference = _fundamental_reference(fundamentals)
        if fundamental_reference:
            evidence.append(fundamental_reference)
        fundamental_counter_evidence = _fundamental_counter_evidence(fundamentals, side)
        fundamental_adjustment = 0.03 if fundamentals and not fundamental_counter_evidence else -0.05 if fundamental_counter_evidence else 0.0
        confidence = min(
            0.82,
            max(
                0.35,
                0.42
                + min(abs(score), 5) * 0.055
                + min(len(signal_items), 4) * 0.025
                + (0.04 if primary_items else 0.0)
                + fundamental_adjustment,
            ),
        )
        counter_evidence = (
            [
                "SEC/IR primary-source context is attached but not fully interpreted in this slice.",
                "Draft is generated from news cadence only; human review is required.",
            ]
            if primary_items
            else [
                "No SEC/IR primary-source confirmation ingested in this slice.",
                "Draft is generated from news cadence only; human review is required.",
            ]
        )
        if fundamentals:
            counter_evidence.extend(fundamental_counter_evidence)
            if not fundamental_counter_evidence:
                counter_evidence.append("SEC companyfacts fundamentals are parsed locally, but the draft still requires human approval.")
        else:
            counter_evidence.append("No SEC companyfacts fundamentals snapshot is available for this symbol.")
        tracked_thesis = self._find_active_thesis(symbol)
        thesis = (
            f"Watchlist news flow is {direction} for {symbol}. "
            f"The draft keeps notional small and sends the idea through policy checks before approval."
        )
        thesis_id = None
        if tracked_thesis:
            thesis_id = tracked_thesis.id
            thesis = (
                f"Tracked thesis: {tracked_thesis.thesis_statement} "
                f"Latest watchlist news flow is {direction} for {symbol}; the draft still requires evidence gate, "
                "policy check, and human approval."
            )
            evidence.append(
                f"thesis-tracker: {tracked_thesis.id} ({tracked_thesis.side.value}, conviction {tracked_thesis.conviction.value})"
            )
            triggered_risks = [risk for risk in tracked_thesis.risks if risk.status == ThesisRiskStatus.TRIGGERED]
            broken_pillars = [pillar for pillar in tracked_thesis.pillars if pillar.status == ThesisPillarStatus.BROKEN]
            if triggered_risks:
                confidence = max(0.25, confidence - 0.18)
                counter_evidence.extend(
                    f"Tracked thesis risk triggered: {risk.text} ({risk.invalidation_condition})"
                    for risk in triggered_risks[:3]
                )
            if broken_pillars:
                confidence = max(0.25, confidence - 0.12)
                counter_evidence.extend(f"Tracked thesis pillar is broken: {pillar.text}" for pillar in broken_pillars[:3])
        trigger = f"{len(signal_items)} directional item(s), {len(primary_items)} primary-source item(s), score {score}"

        draft = ProposalDraft(
            symbol=symbol,
            side=side,
            qty=qty,
            limit_price=round(last_price, 2),
            confidence=round(confidence, 2),
            trigger=trigger,
            thesis=thesis,
            evidence=evidence,
            counter_evidence=counter_evidence,
            score=score,
            news_count=len(news),
            source_news_ids=[item.id for item in [*top_news, *top_primary]],
            thesis_id=thesis_id,
        )
        gate = self._record_research_goal(
            draft=draft,
            news_items=top_news,
            primary_items=top_primary,
            fundamentals=fundamentals,
            fundamental_reference=fundamental_reference,
            score=score,
        )
        draft.research_goal_id = gate.goal_id
        draft.evidence_gate_passed = gate.passed
        draft.evidence_gate_reasons = gate.reasons
        draft.research_evidence_count = gate.evidence_count
        if not gate.passed:
            draft.counter_evidence.extend(gate.reasons)
        return draft

    def _record_research_goal(
        self,
        *,
        draft: ProposalDraft,
        news_items: list[NewsItem],
        primary_items: list[NewsItem],
        fundamentals: FundamentalSnapshot | None,
        fundamental_reference: str | None,
        score: int,
    ):
        news_evidence = [
            evidence_from_news(
                goal_id="_pending",
                symbol=draft.symbol,
                source_type=item.source or "market-news",
                title=item.title,
                source_uri=item.url,
                published_at=item.published_at,
                verified=_is_primary_source(item),
            )
            for item in news_items
        ]
        verified_evidence = [
            evidence_from_news(
                goal_id="_pending",
                symbol=draft.symbol,
                source_type=item.source or "primary-source",
                title=item.title,
                source_uri=item.url,
                published_at=item.published_at,
                verified=True,
            )
            for item in primary_items
        ]
        if fundamentals and fundamental_reference:
            verified_evidence.append(
                ResearchEvidenceCreate(
                    goal_id="_pending",
                    symbol=draft.symbol,
                    source_type="sec-companyfacts",
                    source_uri=None,
                    text=fundamental_reference,
                    data_as_of=fundamentals.updated_at,
                    freshness_status="latest-local",
                    verification_status="verified",
                    source_verified=True,
                    added_via="system",
                    confidence=0.68,
                    caveat="SEC companyfacts snapshot parsed locally; still requires human interpretation.",
                )
            )
        return research_goal_from_draft(
            store=self.store,
            symbol=draft.symbol,
            side=draft.side.value,
            score=score,
            thesis=draft.thesis,
            news_evidence=news_evidence,
            verified_evidence=verified_evidence,
        )

    def _draft_qty(self, side: Side, last_price: float, position_qty: float) -> int:
        if side == Side.SELL:
            return int(max(0, min(position_qty, max(1, round(position_qty * 0.2)))))
        budget = min(self.settings.draft_notional_usd, self.settings.max_trade_notional_usd)
        return int(max(1, budget // last_price))

    def _find_quote(self, symbol: str) -> Quote | None:
        quote = self.store.get_quote(symbol)
        if quote:
            return quote
        ticker = economic_exposure_ticker(symbol)
        return next((item for item in self.store.list_quotes() if economic_exposure_ticker(item.symbol) == ticker), None)

    def _find_position(self, symbol: str) -> Position | None:
        ticker = economic_exposure_ticker(symbol)
        return next((item for item in self.store.get_portfolio().positions if economic_exposure_ticker(item.symbol) == ticker), None)

    def _find_fundamentals(self, symbol: str) -> FundamentalSnapshot | None:
        snapshot = self.store.get_fundamentals(symbol)
        if snapshot:
            return snapshot
        ticker = economic_exposure_ticker(symbol)
        return next((item for item in self.store.list_fundamentals() if economic_exposure_ticker(item.symbol) == ticker), None)

    def _find_active_thesis(self, symbol: str):
        thesis = self.store.get_active_thesis_for_symbol(symbol)
        if thesis:
            return thesis
        ticker = economic_exposure_ticker(symbol)
        return next(
            (
                item
                for item in self.store.list_theses(limit=200)
                if item.human_confirmed
                and item.status.value == "active"
                and economic_exposure_ticker(item.symbol) == ticker
            ),
            None,
        )


def _score_news(item: NewsItem) -> int:
    haystack = f"{item.title} {item.summary}".lower()
    score = 0
    for term in POSITIVE_TERMS:
        if term in haystack:
            score += 1
    for term in NEGATIVE_TERMS:
        if term in haystack:
            score -= 1
    return score


def _is_primary_source(item: NewsItem) -> bool:
    return item.source in {"sec-edgar", "company-ir"} or "primary-source" in item.tags


def _news_reference(item: NewsItem) -> str:
    if item.url:
        return f"{item.source}: {item.title} ({item.url})"
    return f"{item.source}: {item.title}"


def _fundamental_reference(snapshot: FundamentalSnapshot | None) -> str | None:
    if not snapshot:
        return None
    metric_parts = []
    for metric_name in ("revenue", "net_income", "operating_cash_flow"):
        metric = snapshot.metrics.get(metric_name)
        if metric:
            metric_parts.append(_metric_summary(metric))
    if not metric_parts:
        return None
    return f"sec-companyfacts: {snapshot.entity_name or snapshot.symbol} · " + "; ".join(metric_parts)


def _metric_summary(metric: FundamentalMetric) -> str:
    period = " ".join(part for part in [str(metric.fiscal_year or ""), metric.fiscal_period] if part).strip()
    yoy = f", YoY {metric.yoy_change_pct:+.1f}%" if metric.yoy_change_pct is not None else ""
    filed = f", filed {metric.filed_at.date().isoformat()}" if metric.filed_at else ""
    return f"{metric.label} {_format_metric_value(metric)} ({period or metric.end_date}{yoy}{filed})"


def _fundamental_counter_evidence(snapshot: FundamentalSnapshot | None, side: Side) -> list[str]:
    if not snapshot:
        return []
    notes: list[str] = []
    deterioration = _deteriorating_metrics(snapshot)
    improvement = _improving_metrics(snapshot)
    if side == Side.BUY and deterioration:
        notes.append(f"SEC companyfacts counter-signal: {', '.join(deterioration)} declined YoY.")
    if side == Side.SELL and improvement:
        notes.append(f"SEC companyfacts counter-signal: {', '.join(improvement)} improved YoY.")
    net_income = snapshot.metrics.get("net_income")
    if side == Side.BUY and net_income and net_income.value is not None and net_income.value < 0:
        notes.append("SEC companyfacts counter-signal: latest net income is negative.")
    return notes


def _deteriorating_metrics(snapshot: FundamentalSnapshot) -> list[str]:
    names = []
    for metric_name in ("revenue", "net_income", "operating_cash_flow"):
        metric = snapshot.metrics.get(metric_name)
        if metric and metric.yoy_change_pct is not None and metric.yoy_change_pct < -2:
            names.append(metric.label)
    return names


def _improving_metrics(snapshot: FundamentalSnapshot) -> list[str]:
    names = []
    for metric_name in ("revenue", "net_income", "operating_cash_flow"):
        metric = snapshot.metrics.get(metric_name)
        if metric and metric.yoy_change_pct is not None and metric.yoy_change_pct > 2:
            names.append(metric.label)
    return names


def _format_metric_value(metric: FundamentalMetric) -> str:
    if metric.value is None:
        return "n/a"
    if "share" in metric.unit.lower():
        return f"{metric.value:.2f}"
    prefix = "$" if metric.unit.upper() == "USD" else ""
    abs_value = abs(metric.value)
    if abs_value >= 1_000_000_000:
        return f"{prefix}{metric.value / 1_000_000_000:.1f}B"
    if abs_value >= 1_000_000:
        return f"{prefix}{metric.value / 1_000_000:.1f}M"
    return f"{prefix}{metric.value:,.2f}"
