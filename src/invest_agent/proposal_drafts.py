from __future__ import annotations

from datetime import timedelta

from .config import Settings
from .market_news import external_ticker, resolve_watchlist_symbols
from .models import DraftProposalResult, NewsItem, Position, ProposalCreate, ProposalDraft, Quote, Side, utc_now
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
        ticker = external_ticker(symbol)
        return [
            item
            for item in news
            if item.symbol is not None
            and external_ticker(item.symbol) == ticker
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
        confidence = min(
            0.82,
            0.42 + min(abs(score), 5) * 0.055 + min(len(signal_items), 4) * 0.025 + (0.04 if primary_items else 0.0),
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
        thesis = (
            f"Watchlist news flow is {direction} for {symbol}. "
            f"The draft keeps notional small and sends the idea through policy checks before approval."
        )
        trigger = f"{len(signal_items)} directional item(s), {len(primary_items)} primary-source item(s), score {score}"

        return ProposalDraft(
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
        ticker = external_ticker(symbol)
        return next((item for item in self.store.list_quotes() if external_ticker(item.symbol) == ticker), None)

    def _find_position(self, symbol: str) -> Position | None:
        ticker = external_ticker(symbol)
        return next((item for item in self.store.get_portfolio().positions if external_ticker(item.symbol) == ticker), None)


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
