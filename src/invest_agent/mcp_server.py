from __future__ import annotations

from typing import Literal

from mcp.server.fastmcp import FastMCP

from .advisor import AdvisorService
from .advisor_orchestrator import AdvisorOrchestrator
from .autonomy import SafeAutonomyRunner, autonomy_status
from .committee_reviews import CommitteeReviewService
from .daily_briefs import DailyBriefService
from .data_quality import DataQualityService
from .dividend_lens import DividendLensService
from .catalysts import CatalystCalendarService, mcp_catalyst_request
from .deps import get_service, get_store
from .config import get_settings
from .earnings_preview import EarningsPreviewService
from .earnings_review import EarningsReviewService
from .event_replay import DEFAULT_REPLAY_PATH, export_event_replay, replay_event_file as replay_events_from_file
from .futu_adapter import get_futu_status, refresh_futu_readonly
from .hypotheses import HypothesisRegistryService
from .idea_inbox import IdeaInboxService
from .ir_feeds import IrFeedIngestor
from .market_context import MarketContextService
from .market_regime import MarketRegimeService
from .market_news import MarketNewsIngestor, external_ticker, resolve_watchlist_symbols
from .options_lens import OptionsLensService
from .portfolio_studio import PortfolioStudioService
from .quote_history import QuoteHistoryService
from .sector_lens import SectorLensService
from .models import (
    AdvisorBriefRequest,
    AdvisorFullBriefType,
    AdvisorProfileConfirmationRequest,
    AdvisorProfileUpdateRequest,
    AdvisorQuestionRequest,
    CommitteeReviewRunRequest,
    CorrelationRunRequest,
    DailyBriefRunRequest,
    DataQualityRunRequest,
    DividendReviewRunRequest,
    EarningsPreviewRunRequest,
    HypothesisCreate,
    HypothesisInvalidateRequest,
    HypothesisLinkCreate,
    HypothesisLinkType,
    HypothesisScope,
    ProposalCreate,
    ProposalStatus,
    CatalystCompleteRequest,
    CatalystCreate,
    CatalystEventType,
    CatalystExpectedImpact,
    CatalystStatus,
    EarningsReviewRunRequest,
    ResearchEvidenceCreate,
    ResearchGoalCreate,
    ResearchGoalStatus,
    RunCardActor,
    RunCardStatus,
    RunCardTriggerSource,
    RunCardType,
    Side,
    CreatedBy,
    CreatedVia,
    ThesisActionBias,
    ThesisConviction,
    ThesisCreate,
    ThesisImpact,
    ThesisPillarInput,
    ThesisRiskInput,
    ThesisSide,
    ThesisStatus,
    ThesisUpdateCreate,
    OptionsSnapshotCreate,
    PeerGroupCreate,
    SectorSnapshotRunRequest,
    IdeaCandidateCreate,
    IdeaScreenRunRequest,
)
from .primary_sources import refresh_primary_sources
from .proposal_drafts import ProposalDraftEngine
from .research_goals import ResearchGoalService
from .run_cards import RunCardService
from .sec_companyfacts import SecCompanyFactsIngestor
from .sec_edgar import SecEdgarIngestor
from .thesis_tracker import ThesisTrackerService

mcp = FastMCP("AI Investment Agent Control Plane")


def _json(model):
    if isinstance(model, list):
        return [_json(item) for item in model]
    if hasattr(model, "model_dump"):
        return model.model_dump(mode="json")
    return model


@mcp.tool()
def get_portfolio_snapshot() -> dict:
    """Return the latest local portfolio snapshot."""
    return _json(get_store().get_portfolio())


@mcp.tool()
def get_watchlist_quotes() -> list[dict]:
    """Return locally cached watchlist quotes."""
    return _json(get_store().list_quotes())


@mcp.tool()
def get_watchlist_symbols() -> list[str]:
    """Return configured watchlist symbols, including locally held and quoted symbols."""
    return resolve_watchlist_symbols(get_settings(), get_store())


@mcp.tool()
def get_advisor_brief(run_light_analysis: bool = False, max_items: int = 8) -> dict:
    """Return the legacy advisor research brief. For front-door user advice, prefer ask_advisor or full advisor brief tools."""
    return _json(
        AdvisorService(get_store(), paper_only=get_settings().is_paper).build_brief(
            AdvisorBriefRequest(run_light_analysis=run_light_analysis, max_items=max_items)
        )
    )


@mcp.tool()
def ask_advisor(question: str, symbol: str | None = None, style: str = "concise") -> dict:
    """Preferred first tool for buy/sell/hold/watch questions. Returns a concise research-only decision card."""
    return _json(
        AdvisorOrchestrator(get_store(), settings=get_settings()).answer_user_question(
            AdvisorQuestionRequest(question=question, symbol=symbol, style=style),
            actor=RunCardActor.MCP,
        )
    )


@mcp.tool()
def get_advisor_profile() -> dict:
    """Return the confirmed Advisor Profile plus pending profile updates. Read-only and research-only."""
    return _json(AdvisorOrchestrator(get_store(), settings=get_settings()).get_advisor_profile())


@mcp.tool()
def suggest_advisor_profile_update(
    rationale: str,
    risk_profile: str | None = None,
    max_single_stock_weight: float | None = None,
    max_tech_exposure: float | None = None,
    max_sector_exposure: float | None = None,
    min_cash_weight: float | None = None,
    prefer_core_etf: bool | None = None,
    avoid_chasing_after_big_move: bool | None = None,
    allow_options: bool | None = None,
    allow_ipo_or_private: bool | None = None,
    notes: list[str] | None = None,
    source_question_id: str | None = None,
) -> dict:
    """Suggest a pending Advisor Profile update. It is not applied until the user confirms it."""
    return _json(
        AdvisorOrchestrator(get_store(), settings=get_settings()).suggest_profile_update(
            AdvisorProfileUpdateRequest(
                rationale=rationale,
                risk_profile=risk_profile,
                max_single_stock_weight=max_single_stock_weight,
                max_tech_exposure=max_tech_exposure,
                max_sector_exposure=max_sector_exposure,
                min_cash_weight=min_cash_weight,
                prefer_core_etf=prefer_core_etf,
                avoid_chasing_after_big_move=avoid_chasing_after_big_move,
                allow_options=allow_options,
                allow_ipo_or_private=allow_ipo_or_private,
                notes=notes or [],
                source_question_id=source_question_id,
                proposed_by="hermes",
            )
        )
    )


@mcp.tool()
def confirm_advisor_profile_update(
    update_id: str,
    confirmed: bool = True,
    confirmed_by: str = "telegram-user",
    rejection_reason: str | None = None,
) -> dict:
    """Confirm or reject a pending Advisor Profile update after explicit user approval."""
    return _json(
        AdvisorOrchestrator(get_store(), settings=get_settings()).confirm_profile_update(
            update_id,
            AdvisorProfileConfirmationRequest(
                confirmed=confirmed,
                confirmed_by=confirmed_by,
                rejection_reason=rejection_reason,
            ),
        )
    )


@mcp.tool()
def run_hourly_advisor_pulse() -> dict:
    """Run the hourly urgent detector. Stores pulse results and never creates proposals, approvals, or trades."""
    return _json(AdvisorOrchestrator(get_store(), settings=get_settings()).run_hourly_pulse(actor=RunCardActor.MCP))


@mcp.tool()
def run_pre_market_advisor_brief() -> dict:
    """Preferred tool for market-open or pre-market advice. Returns grouped ACTION/WATCH/BLOCKED/INFO recommendations."""
    return _json(
        AdvisorOrchestrator(get_store(), settings=get_settings()).run_full_advisor_brief(
            AdvisorFullBriefType.PRE_MARKET,
            actor=RunCardActor.MCP,
        )
    )


@mcp.tool()
def run_post_close_advisor_brief() -> dict:
    """Preferred tool for post-close review. Returns grouped ACTION/WATCH/BLOCKED/INFO recommendations."""
    return _json(
        AdvisorOrchestrator(get_store(), settings=get_settings()).run_full_advisor_brief(
            AdvisorFullBriefType.POST_CLOSE,
            actor=RunCardActor.MCP,
        )
    )


@mcp.tool()
def get_latest_advisor_brief(brief_type: Literal["pre_market", "post_close"] | None = None) -> dict:
    """Return the latest stored Hermes Advisor Mode brief; use before reconstructing advice from low-level tools."""
    item = get_store().get_latest_advisor_brief(brief_type=brief_type)
    return _json(item) if item else {"brief": None}


@mcp.tool()
def get_market_context() -> dict:
    """Return broad-market context symbols, quote/news coverage, and risk notes. Research-only."""
    return _json(MarketContextService(get_settings(), get_store()).build_context())


@mcp.tool()
def get_market_regime() -> dict:
    """Return deterministic market regime and proposal-bias background. Research-only and no proposal creation."""
    return _json(MarketRegimeService(get_settings(), get_store()).build_snapshot())


@mcp.tool()
def refresh_market_context_news(
    days: int | None = None,
    max_per_symbol: int | None = None,
    include_gdelt: bool = True,
    include_google_news: bool | None = None,
    include_finnhub: bool = True,
) -> dict:
    """Refresh broad-market context news without creating proposals or approvals."""
    service = MarketContextService(get_settings(), get_store())
    result = service.refresh_news(
        days=days,
        max_per_symbol=max_per_symbol,
        include_gdelt=include_gdelt,
        include_google_news=include_google_news,
        include_finnhub=include_finnhub,
    )
    return {"refresh": _json(result), "context": _json(service.build_context())}


@mcp.tool()
def get_news_digest(symbol: str | None = None, limit: int = 10) -> list[dict]:
    """Return locally cached market and watchlist news items."""
    return _json(get_store().list_news(limit=limit, symbol=symbol))


@mcp.tool()
def refresh_market_news(
    symbols: list[str] | None = None,
    days: int | None = None,
    max_per_symbol: int | None = None,
    max_symbols: int | None = None,
    include_google_news: bool | None = None,
) -> dict:
    """Refresh watchlist market news from free GDELT and optional Finnhub sources."""
    return _json(
        MarketNewsIngestor(get_settings(), get_store()).refresh_news(
            symbols=symbols,
            days=days,
            max_per_symbol=max_per_symbol,
            max_symbols=max_symbols,
            include_google_news=include_google_news,
        )
    )


@mcp.tool()
def refresh_primary_source_filings(
    symbols: list[str] | None = None,
    include_sec: bool = True,
    include_ir: bool = True,
    forms: list[str] | None = None,
    max_filings: int | None = None,
    max_symbols: int | None = None,
) -> dict:
    """Refresh SEC EDGAR filings and configured company IR RSS feeds as primary-source evidence."""
    settings = get_settings()
    store = get_store()
    return _json(
        refresh_primary_sources(
            SecEdgarIngestor(settings, store),
            IrFeedIngestor(settings, store),
            symbols=symbols,
            include_sec=include_sec,
            include_ir=include_ir,
            forms=forms,
            max_filings=max_filings,
            max_symbols=max_symbols,
        )
    )


@mcp.tool()
def refresh_sec_company_facts(
    symbols: list[str] | None = None,
    max_symbols: int | None = None,
    forms: list[str] | None = None,
) -> dict:
    """Refresh SEC XBRL companyfacts fundamentals for watchlist symbols and store local snapshots."""
    return _json(
        SecCompanyFactsIngestor(get_settings(), get_store()).refresh_fundamentals(
            symbols=symbols,
            max_symbols=max_symbols,
            forms=forms,
        )
    )


@mcp.tool()
def get_fundamental_snapshot(symbol: str | None = None) -> dict | list[dict]:
    """Return stored SEC companyfacts fundamentals for one symbol, or all cached watchlist snapshots."""
    store = get_store()
    if symbol:
        snapshot = store.get_fundamentals(symbol)
        if not snapshot:
            ticker = external_ticker(symbol)
            snapshot = next((item for item in store.list_fundamentals() if external_ticker(item.symbol) == ticker), None)
        return _json(snapshot) if snapshot else {"error": f"fundamental snapshot not found for {symbol.upper()}"}
    return _json(store.list_fundamentals())


@mcp.tool()
def list_research_goals(
    status: Literal["ACTIVE", "COMPLETED", "INSUFFICIENT", "REJECTED"] | None = None,
    symbol: str | None = None,
    limit: int = 20,
) -> list[dict]:
    """List research-only goals and evidence gate summaries before proposal creation."""
    parsed_status = ResearchGoalStatus(status) if status else None
    return _json(get_store().list_research_goals(status=parsed_status, symbol=symbol, limit=limit))


@mcp.tool()
def create_research_goal(
    objective: str,
    symbol: str | None = None,
    claims: list[str] | None = None,
    criteria: list[str] | None = None,
) -> dict:
    """Create a research-only goal. Objectives that ask for approval, unlock, or broker execution are rejected."""
    goal = ResearchGoalService(get_store()).create_goal(
        ResearchGoalCreate(
            symbol=symbol,
            objective=objective,
            claims=claims or [],
            criteria=criteria or [],
        )
    )
    return _json(goal)


@mcp.tool()
def add_research_evidence(
    goal_id: str,
    source_type: str,
    text: str,
    symbol: str | None = None,
    source_uri: str | None = None,
    confidence: float = 0.5,
    caveat: str = "",
) -> dict:
    """Attach an unverified evidence row to a research goal. MCP text cannot mark itself source-verified."""
    evidence = ResearchGoalService(get_store()).add_evidence(
        ResearchEvidenceCreate(
            goal_id=goal_id,
            symbol=symbol,
            source_type=source_type,
            source_uri=source_uri,
            text=text,
            verification_status="unverified",
            source_verified=False,
            added_via="mcp",
            confidence=confidence,
            caveat=caveat,
        )
    )
    return _json(evidence)


@mcp.tool()
def get_research_goal_snapshot(goal_id: str) -> dict:
    """Return one research goal with claims, criteria, and evidence rows."""
    goal = get_store().get_research_goal(goal_id)
    return _json(goal) if goal else {"error": f"research goal not found: {goal_id}"}


@mcp.tool()
def list_hypotheses(symbol: str | None = None, limit: int = 20) -> list[dict]:
    """List durable research hypotheses. Read-only; hypotheses cannot create proposals."""
    return _json(get_store().list_hypotheses(symbol=symbol, limit=limit))


@mcp.tool()
def get_hypothesis(hypothesis_id: str) -> dict:
    """Return one research hypothesis with links."""
    item = get_store().get_hypothesis(hypothesis_id)
    return _json(item) if item else {"error": f"hypothesis not found: {hypothesis_id}"}


@mcp.tool()
def create_hypothesis_draft(
    title: str,
    statement: str,
    scope: Literal["symbol", "sector", "portfolio", "macro", "behavior", "strategy"] = "symbol",
    symbols: list[str] | None = None,
    confidence: float = 0.5,
) -> dict:
    """Create an unconfirmed research hypothesis draft. It cannot create or approve proposals."""
    return _json(
        HypothesisRegistryService(get_store()).create(
            HypothesisCreate(
                title=title,
                statement=statement,
                scope=HypothesisScope(scope),
                symbols=symbols or [],
                confidence=confidence,
            ),
            actor=RunCardActor.MCP,
        )
    )


@mcp.tool()
def link_run_card_to_hypothesis(hypothesis_id: str, run_card_id: str) -> dict:
    """Link an existing run card to a hypothesis as supplementary research evidence."""
    try:
        return _json(
            HypothesisRegistryService(get_store()).link(
                hypothesis_id,
                HypothesisLinkCreate(linked_type=HypothesisLinkType.RUN_CARD, linked_id=run_card_id),
            )
        )
    except ValueError as exc:
        return {"error": str(exc)}


@mcp.tool()
def invalidate_hypothesis(hypothesis_id: str, invalidation_note: str) -> dict:
    """Invalidate a research hypothesis. This is research state only and cannot approve trades."""
    try:
        return _json(HypothesisRegistryService(get_store()).invalidate(hypothesis_id, HypothesisInvalidateRequest(invalidation_note=invalidation_note)))
    except ValueError as exc:
        return {"error": str(exc)}


@mcp.tool()
def get_portfolio_risk_snapshot(limit: int = 1) -> list[dict]:
    """Return recent portfolio risk snapshots. Read-only and not a proposal source."""
    return _json(get_store().list_portfolio_risk_snapshots(limit=limit))


@mcp.tool()
def list_rebalance_reviews(limit: int = 10) -> list[dict]:
    """List rebalance reviews and candidates. Candidates are not proposals."""
    return _json(get_store().list_rebalance_reviews(limit=limit))


@mcp.tool()
def get_rebalance_review(review_id: str) -> dict:
    """Return one rebalance review."""
    item = get_store().get_rebalance_review(review_id)
    return _json(item) if item else {"error": f"rebalance review not found: {review_id}"}


@mcp.tool()
def create_thesis(
    symbol: str,
    thesis_statement: str,
    side: Literal["long", "short", "neutral_watch"] = "long",
    conviction: Literal["high", "medium", "low"] = "medium",
    target_price: float | None = None,
    stop_loss_trigger: str = "",
    pillars: list[str] | None = None,
    risks: list[str] | None = None,
    invalidation_conditions: list[str] | None = None,
) -> dict:
    """Create a research-only thesis with pillars and invalidating risks. It does not approve or execute trades."""
    risk_texts = risks or []
    conditions = invalidation_conditions or []
    request = ThesisCreate(
        symbol=symbol,
        side=ThesisSide(side),
        thesis_statement=thesis_statement,
        status=ThesisStatus.WATCH,
        conviction=ThesisConviction(conviction),
        target_price=target_price,
        stop_loss_trigger=stop_loss_trigger,
        created_via=CreatedVia.MCP,
        created_by=CreatedBy.HERMES,
        human_confirmed=False,
        confirmed_by="",
        pillars=[ThesisPillarInput(text=text) for text in (pillars or [])],
        risks=[
            ThesisRiskInput(
                text=text,
                invalidation_condition=conditions[index] if index < len(conditions) else text,
            )
            for index, text in enumerate(risk_texts)
        ],
    )
    return _json(ThesisTrackerService(get_store()).create_thesis(request))


@mcp.tool()
def list_theses(
    symbol: str | None = None,
    status: Literal["active", "watch", "invalidated", "archived"] | None = None,
    limit: int = 20,
) -> list[dict]:
    """List tracked investment theses, including pillars, risks, and recent thesis updates."""
    parsed_status = ThesisStatus(status) if status else None
    return _json(get_store().list_theses(status=parsed_status, symbol=symbol, limit=limit))


@mcp.tool()
def get_thesis_snapshot(thesis_id: str) -> dict:
    """Return one tracked thesis with pillars, risks, and evidence-linked updates."""
    thesis = get_store().get_thesis(thesis_id)
    return _json(thesis) if thesis else {"error": f"thesis not found: {thesis_id}"}


@mcp.tool()
def list_catalysts(
    symbol: str | None = None,
    status: Literal["upcoming", "completed", "cancelled", "missed"] | None = None,
    days: int | None = None,
    limit: int = 20,
) -> list[dict]:
    """List catalyst calendar events. Use days for an upcoming-event preview."""
    parsed_status = CatalystStatus(status) if status else None
    service = CatalystCalendarService(get_store())
    if days is not None:
        return _json(service.list_upcoming(days=days, symbol=symbol, limit=limit))
    return _json(get_store().list_catalysts(status=parsed_status, symbol=symbol, limit=limit))


@mcp.tool()
def create_catalyst(
    title: str,
    event_date: str,
    symbol: str | None = None,
    event_type: Literal[
        "earnings",
        "investor_day",
        "analyst_day",
        "product",
        "regulatory",
        "conference",
        "macro",
        "industry_data",
        "shareholder_meeting",
        "other",
    ] = "other",
    expected_impact: Literal["high", "medium", "low"] = "medium",
    description: str = "",
    source_uri: str | None = None,
    linked_thesis_id: str | None = None,
) -> dict:
    """Create an unverified research-only catalyst calendar event. MCP-created catalysts never count as source-verified."""
    request = mcp_catalyst_request(
        symbol=symbol,
        event_type=CatalystEventType(event_type),
        title=title,
        event_date=event_date,
        expected_impact=CatalystExpectedImpact(expected_impact),
        description=description,
        source_uri=source_uri,
        linked_thesis_id=linked_thesis_id,
    )
    return _json(CatalystCalendarService(get_store()).create_catalyst(request))


@mcp.tool()
def get_catalyst_snapshot(catalyst_id: str) -> dict:
    """Return one catalyst event plus any local review rows."""
    store = get_store()
    catalyst = store.get_catalyst(catalyst_id)
    if not catalyst:
        return {"error": f"catalyst not found: {catalyst_id}"}
    return {"catalyst": _json(catalyst), "reviews": _json(store.list_catalyst_reviews(catalyst_id))}


@mcp.tool()
def complete_catalyst_with_research_goal(catalyst_id: str, actual_outcome_summary: str) -> dict:
    """Mark a catalyst completed and create a post-event research goal candidate. It does not create proposals."""
    catalyst = CatalystCalendarService(get_store()).complete_catalyst(
        catalyst_id,
        CatalystCompleteRequest(actual_outcome_summary=actual_outcome_summary, create_research_goal=True),
    )
    return _json(catalyst)


@mcp.tool()
def run_earnings_preview(
    symbol: str,
    catalyst_id: str | None = None,
    thesis_id: str | None = None,
    implied_move_pct: float | None = None,
) -> dict:
    """Run a research-only pre-earnings preview. It cannot create proposals."""
    try:
        return _json(
            EarningsPreviewService(get_store()).run_preview(
                EarningsPreviewRunRequest(
                    symbol=symbol,
                    catalyst_id=catalyst_id,
                    thesis_id=thesis_id,
                    implied_move_pct=implied_move_pct,
                ),
                actor=RunCardActor.MCP,
            )
        )
    except ValueError as exc:
        return {"error": str(exc)}


@mcp.tool()
def list_earnings_previews(symbol: str | None = None, limit: int = 20) -> list[dict]:
    """List pre-earnings preview artifacts."""
    return _json(get_store().list_earnings_previews(symbol=symbol, limit=limit))


@mcp.tool()
def get_earnings_preview(preview_id: str) -> dict:
    """Return one earnings preview artifact."""
    item = get_store().get_earnings_preview(preview_id)
    return _json(item) if item else {"error": f"earnings preview not found: {preview_id}"}


@mcp.tool()
def run_earnings_review(
    symbol: str,
    catalyst_id: str | None = None,
    research_goal_id: str | None = None,
    thesis_id: str | None = None,
) -> dict:
    """Run a research-only earnings review from local SEC companyfacts. It can create review artifacts but never approvals."""
    try:
        review = EarningsReviewService(get_store()).run_review(
            EarningsReviewRunRequest(
                symbol=symbol,
                catalyst_id=catalyst_id,
                research_goal_id=research_goal_id,
                thesis_id=thesis_id,
                refresh_fundamentals=False,
            ),
            actor=RunCardActor.MCP,
            trigger_source=RunCardTriggerSource.MANUAL,
        )
        return _json(review)
    except ValueError as exc:
        return {"error": str(exc)}


@mcp.tool()
def list_earnings_reviews(symbol: str | None = None, limit: int = 20) -> list[dict]:
    """List local earnings review artifacts."""
    return _json(get_store().list_earnings_reviews(symbol=symbol, limit=limit))


@mcp.tool()
def get_earnings_review(review_id: str) -> dict:
    """Return one earnings review artifact."""
    review = get_store().get_earnings_review(review_id)
    return _json(review) if review else {"error": f"earnings review not found: {review_id}"}


@mcp.tool()
def apply_earnings_review_to_thesis(review_id: str, thesis_id: str | None = None) -> dict:
    """Apply a non-severe earnings review thesis delta. Severe deltas require human confirmation outside MCP."""
    try:
        return _json(EarningsReviewService(get_store()).apply_to_thesis(review_id, thesis_id=thesis_id))
    except ValueError as exc:
        return {"error": str(exc)}


@mcp.tool()
def list_run_cards(
    run_type: Literal[
        "earnings_review",
        "catalyst_review",
        "event_replay",
        "market_regime",
        "hypothesis_review",
        "portfolio_risk",
        "rebalance_review",
        "earnings_preview",
        "quote_history_import",
        "external_backtest_import",
        "data_import",
        "daily_brief",
        "correlation_snapshot",
        "sector_snapshot",
        "options_snapshot",
        "dividend_review",
        "idea_screen",
        "committee_review",
        "skill_validation",
        "data_quality_report",
        "trade_journal_import",
        "behavior_report",
        "shadow_strategy_extract",
        "shadow_report",
        "safe_autonomy_cycle",
        "proposal_draft",
        "advisor_question",
        "advisor_pulse",
        "advisor_brief",
        "opportunity_radar",
        "future_backtest_import",
        "future_behavior_report",
    ]
    | None = None,
    status: Literal["running", "completed", "failed", "cancelled"] | None = None,
    symbol: str | None = None,
    limit: int = 20,
) -> list[dict]:
    """List system-generated research run cards. MCP can read run cards but cannot create arbitrary ones."""
    parsed_type = RunCardType(run_type) if run_type else None
    parsed_status = RunCardStatus(status) if status else None
    return _json(get_store().list_run_cards(run_type=parsed_type, status=parsed_status, symbol=symbol, limit=limit))


@mcp.tool()
def get_run_card(run_card_id: str) -> dict:
    """Return one research run card."""
    run_card = get_store().get_run_card(run_card_id)
    return _json(run_card) if run_card else {"error": f"run card not found: {run_card_id}"}


@mcp.tool()
def get_run_card_artifact(run_card_id: str, kind: Literal["json", "markdown"] = "json") -> dict:
    """Return a JSON or Markdown run-card artifact as text."""
    try:
        return {"run_card_id": run_card_id, "kind": kind, "text": RunCardService(get_store()).get_artifact_text(run_card_id, kind=kind)}
    except ValueError as exc:
        return {"error": str(exc)}


@mcp.tool()
def list_quote_history(symbol: str | None = None, limit: int = 20) -> list[dict]:
    """List quote-history imports. Read-only; MCP cannot refresh local files."""
    return _json(get_store().list_quote_history_imports(symbol=symbol, limit=limit))


@mcp.tool()
def get_quote_history_summary(symbol: str | None = None) -> dict:
    """Return cached quote-history coverage summary. It is diagnostic only."""
    return QuoteHistoryService(get_store()).summary(symbol=symbol)


@mcp.tool()
def list_backtest_imports(limit: int = 20) -> list[dict]:
    """List external backtest imports. Imported backtests are supplementary evidence only."""
    return _json(get_store().list_external_backtest_imports(limit=limit))


@mcp.tool()
def get_backtest_import(import_id: str) -> dict:
    """Return one external backtest import."""
    item = get_store().get_external_backtest_import(import_id)
    return _json(item) if item else {"error": f"backtest import not found: {import_id}"}


@mcp.tool()
def list_data_imports(limit: int = 20) -> list[dict]:
    """List safe local data imports. MCP cannot import arbitrary files."""
    return _json(get_store().list_data_imports(limit=limit))


@mcp.tool()
def get_data_import_summary(import_id: str) -> dict:
    """Return one data import summary."""
    item = get_store().get_data_import(import_id)
    return _json(item) if item else {"error": f"data import not found: {import_id}"}


@mcp.tool()
def get_latest_daily_brief() -> dict:
    """Return the latest daily brief. Briefs do not create proposals."""
    items = get_store().list_daily_briefs(limit=1)
    return _json(items[0]) if items else {"error": "daily brief not found"}


@mcp.tool()
def list_daily_briefs(limit: int = 20) -> list[dict]:
    """List daily research delivery briefs."""
    return _json(get_store().list_daily_briefs(limit=limit))


@mcp.tool()
def list_peer_groups(sector: str | None = None, limit: int = 20) -> list[dict]:
    """List peer groups used for sector/correlation context."""
    return _json(get_store().list_peer_groups(sector=sector, limit=limit))


@mcp.tool()
def get_correlation_snapshot(snapshot_id: str | None = None) -> dict:
    """Return a correlation snapshot. Correlation only adds context/warnings."""
    if snapshot_id:
        item = get_store().get_correlation_snapshot(snapshot_id)
    else:
        items = get_store().list_correlation_snapshots(limit=1)
        item = items[0] if items else None
    return _json(item) if item else {"error": "correlation snapshot not found"}


@mcp.tool()
def get_sector_snapshot(snapshot_id: str | None = None) -> dict:
    """Return a sector snapshot. Sector data cannot create proposals."""
    if snapshot_id:
        item = get_store().get_sector_snapshot(snapshot_id)
    else:
        items = get_store().list_sector_snapshots(limit=1)
        item = items[0] if items else None
    return _json(item) if item else {"error": "sector snapshot not found"}


@mcp.tool()
def list_options_snapshots(symbol: str | None = None, limit: int = 20) -> list[dict]:
    """List options implied-move snapshots. MCP reads context but does not trade options."""
    return _json(get_store().list_options_snapshots(symbol=symbol, limit=limit))


@mcp.tool()
def get_options_snapshot(symbol: str) -> dict:
    """Return the latest options snapshot for a symbol."""
    items = get_store().list_options_snapshots(symbol=symbol, limit=1)
    return _json(items[0]) if items else {"error": f"options snapshot not found for {symbol.upper()}"}


@mcp.tool()
def run_dividend_review(
    symbol: str,
    dividend_yield: float | None = None,
    payout_ratio: float | None = None,
    dividend_growth_3y: float | None = None,
    fcf_coverage: float | None = None,
    thesis_id: str | None = None,
) -> dict:
    """Run a research-only dividend review. High yield alone cannot create a BUY proposal."""
    return _json(
        DividendLensService(get_store()).run_review(
            DividendReviewRunRequest(
                symbol=symbol,
                dividend_yield=dividend_yield,
                payout_ratio=payout_ratio,
                dividend_growth_3y=dividend_growth_3y,
                fcf_coverage=fcf_coverage,
                thesis_id=thesis_id,
            ),
            actor=RunCardActor.MCP,
        )
    )


@mcp.tool()
def list_dividend_reviews(symbol: str | None = None, limit: int = 20) -> list[dict]:
    """List dividend review artifacts."""
    return _json(get_store().list_dividend_reviews(symbol=symbol, limit=limit))


@mcp.tool()
def get_dividend_review(review_id: str) -> dict:
    """Return one dividend review artifact."""
    items = [item for item in get_store().list_dividend_reviews(limit=200) if item.id == review_id]
    return _json(items[0]) if items else {"error": f"dividend review not found: {review_id}"}


@mcp.tool()
def list_idea_candidates(symbol: str | None = None, limit: int = 20) -> list[dict]:
    """List idea inbox candidates. Ideas cannot create proposals directly."""
    return _json(get_store().list_idea_candidates(symbol=symbol, limit=limit))


@mcp.tool()
def get_idea_candidate(candidate_id: str) -> dict:
    """Return one idea candidate."""
    item = get_store().get_idea_candidate(candidate_id)
    return _json(item) if item else {"error": f"idea candidate not found: {candidate_id}"}


@mcp.tool()
def create_idea_candidate_draft(
    symbol: str,
    one_line_thesis: str,
    direction: Literal["long", "short", "neutral_watch"] = "neutral_watch",
    score: float = 0.0,
) -> dict:
    """Create a draft idea candidate. It cannot become a proposal without research-goal and evidence-gate flow."""
    from .models import IdeaDirection

    return _json(
        IdeaInboxService(get_settings(), get_store()).create_candidate(
            IdeaCandidateCreate(symbol=symbol, one_line_thesis=one_line_thesis, direction=IdeaDirection(direction), score=score)
        )
    )


@mcp.tool()
def run_committee_review(
    topic: str,
    symbols: list[str] | None = None,
    review_type: Literal["investment_committee", "risk_committee", "macro_committee", "earnings_committee"] = "investment_committee",
    research_goal_id: str | None = None,
    hypothesis_id: str | None = None,
    bull_case: str = "",
    bear_case: str = "",
    risk_memo: str = "",
    missing_evidence: list[str] | None = None,
) -> dict:
    """Create a committee-style research memo. It cannot approve or create pending proposals."""
    return _json(
        CommitteeReviewService(get_store()).run_review(
            CommitteeReviewRunRequest(
                topic=topic,
                symbols=symbols or [],
                review_type=review_type,
                research_goal_id=research_goal_id,
                hypothesis_id=hypothesis_id,
                bull_case=bull_case,
                bear_case=bear_case,
                risk_memo=risk_memo,
                missing_evidence=missing_evidence or [],
            ),
            actor=RunCardActor.MCP,
        )
    )


@mcp.tool()
def list_committee_reviews(limit: int = 20) -> list[dict]:
    """List committee review memos."""
    return _json(get_store().list_committee_reviews(limit=limit))


@mcp.tool()
def get_committee_review(review_id: str) -> dict:
    """Return one committee review memo."""
    item = get_store().get_committee_review(review_id)
    return _json(item) if item else {"error": f"committee review not found: {review_id}"}


@mcp.tool()
def list_data_quality_reports(limit: int = 20) -> list[dict]:
    """List data quality reports. QA only raises warnings and cannot create proposals."""
    return _json(get_store().list_data_quality_reports(limit=limit))


@mcp.tool()
def get_data_quality_report(report_id: str) -> dict:
    """Return one data quality report."""
    item = get_store().get_data_quality_report(report_id)
    return _json(item) if item else {"error": f"data quality report not found: {report_id}"}


@mcp.tool()
def list_behavior_reports(symbol: str | None = None, limit: int = 20) -> list[dict]:
    """List local trade behavior reports. MCP can read reports but cannot import local trade files."""
    return _json(get_store().list_behavior_reports(symbol=symbol, limit=limit))


@mcp.tool()
def get_behavior_report(report_id: str) -> dict:
    """Return one local trade behavior report."""
    report = get_store().get_behavior_report(report_id)
    return _json(report) if report else {"error": f"behavior report not found: {report_id}"}


@mcp.tool()
def list_trade_roundtrips(symbol: str | None = None, limit: int = 20) -> list[dict]:
    """List FIFO-paired closed trade roundtrips from imported trade journals."""
    return _json(get_store().list_trade_roundtrips(symbol=symbol, limit=limit))


@mcp.tool()
def list_shadow_strategies(status: Literal["draft", "active", "archived"] | None = None, limit: int = 20) -> list[dict]:
    """List research-only shadow account strategies. MCP can read strategies but cannot confirm or activate them."""
    from .models import ShadowStrategyStatus

    parsed_status = ShadowStrategyStatus(status) if status else None
    return _json(get_store().list_shadow_strategies(status=parsed_status, limit=limit))


@mcp.tool()
def get_shadow_strategy(strategy_id: str) -> dict:
    """Return one shadow strategy with deterministic rules."""
    strategy = get_store().get_shadow_strategy(strategy_id)
    return _json(strategy) if strategy else {"error": f"shadow strategy not found: {strategy_id}"}


@mcp.tool()
def list_shadow_reports(strategy_id: str | None = None, limit: int = 20) -> list[dict]:
    """List research-only shadow account counterfactual reports."""
    return _json(get_store().list_shadow_reports(strategy_id=strategy_id, limit=limit))


@mcp.tool()
def get_shadow_report(report_id: str) -> dict:
    """Return one shadow report. Reports are research artifacts and never create proposals."""
    report = get_store().get_shadow_report(report_id)
    return _json(report) if report else {"error": f"shadow report not found: {report_id}"}


@mcp.tool()
def list_shadow_events(report_id: str | None = None, symbol: str | None = None, limit: int = 50) -> list[dict]:
    """List shadow account rule violations and journal-internal counterfactual events."""
    return _json(get_store().list_shadow_events(shadow_report_id=report_id, symbol=symbol, limit=limit))


@mcp.tool()
def add_thesis_update_from_research_goal(
    thesis_id: str,
    research_goal_id: str,
    impact: Literal["strengthens", "weakens", "neutral", "invalidates"],
    summary: str,
    action_bias: Literal["no_change", "increase", "trim", "exit", "watch_only"] = "no_change",
    conviction: Literal["high", "medium", "low"] | None = None,
) -> dict:
    """Attach a research-goal-backed thesis update. This writes research state only and never creates approval."""
    request = ThesisUpdateCreate(
        research_goal_id=research_goal_id,
        impact=ThesisImpact(impact),
        summary=summary,
        action_bias=ThesisActionBias(action_bias),
        conviction=ThesisConviction(conviction) if conviction else None,
    )
    return _json(ThesisTrackerService(get_store()).add_update(thesis_id, request))


@mcp.tool()
def get_safe_autonomy_status() -> dict:
    """Return safe-autonomy scheduler settings and the latest completed cycle summary."""
    return autonomy_status(get_settings(), get_store())


@mcp.tool()
def run_safe_autonomy_cycle(create_proposals: bool | None = None, include_slow_sources: bool = True) -> dict:
    """Run one safe autonomy cycle now. It can create paper-only proposals, but never unlocks Futu or places live orders."""
    return _json(
        SafeAutonomyRunner(get_settings(), get_store(), get_service()).run_cycle(
            mode="mcp-once",
            create_proposals=create_proposals,
            include_slow_sources=include_slow_sources,
        )
    )


@mcp.tool()
def export_event_replay_file(path: str = str(DEFAULT_REPLAY_PATH), news_limit: int = 100) -> dict:
    """Export current portfolio, quotes, and news into a JSONL event replay file."""
    return _json(
        export_event_replay(
            get_store(),
            path,
            news_limit=news_limit,
            actor=RunCardActor.MCP,
            trigger_source=RunCardTriggerSource.REPLAY,
        )
    )


@mcp.tool()
def replay_event_file(path: str = str(DEFAULT_REPLAY_PATH), create_proposals: bool = False) -> dict:
    """Replay a local JSONL event file into the store and optionally create policy-checked proposals."""
    return _json(replay_events_from_file(get_settings(), get_store(), path, create_proposals=create_proposals))


@mcp.tool()
def draft_trade_proposals_from_watchlist(
    symbols: list[str] | None = None,
    lookback_hours: int = 72,
    max_drafts: int | None = None,
    create_proposals: bool = False,
) -> dict:
    """Draft structured trade proposal candidates from watchlist news. Creation is optional and still policy-checked."""
    return _json(
        ProposalDraftEngine(get_settings(), get_store(), get_service()).draft_from_watchlist(
            symbols=symbols,
            lookback_hours=lookback_hours,
            max_drafts=max_drafts,
            create_proposals=create_proposals,
        )
    )


@mcp.tool()
def get_futu_connection_status() -> dict:
    """Check whether local Futu OpenD read-only integration is enabled and reachable."""
    return get_futu_status(get_settings())


@mcp.tool()
def refresh_futu_readonly_snapshot(refresh_cache: bool = False) -> dict:
    """Low-level read-only Futu data refresh; not a user-facing advice path and never unlocks trading."""
    return refresh_futu_readonly(get_settings(), get_store(), refresh_cache=refresh_cache).as_dict()


@mcp.tool()
def list_pending_proposals(limit: int = 20) -> list[dict]:
    """Low-level audit list of pending proposals; do not use as the first path for general user-facing advice."""
    proposals = get_store().list_proposals(status=ProposalStatus.PENDING, limit=limit)
    return _json(proposals)


@mcp.tool()
def create_trade_proposal(
    symbol: str,
    side: Literal["BUY", "SELL"],
    qty: int,
    limit_price: float,
    thesis: str,
    trigger: str,
    confidence: float,
    ttl_minutes: int | None = None,
    evidence: list[str] | None = None,
    counter_evidence: list[str] | None = None,
    research_goal_id: str | None = None,
    manual_override_reason: str | None = None,
    thesis_id: str | None = None,
) -> dict:
    """Create a risk-checked trade proposal. A passed research_goal_id or explicit manual_override_reason is required."""
    request = ProposalCreate(
        symbol=symbol,
        side=Side(side),
        qty=qty,
        limit_price=limit_price,
        thesis=thesis,
        trigger=trigger,
        confidence=confidence,
        ttl_minutes=ttl_minutes,
        evidence=evidence or [],
        counter_evidence=counter_evidence or [],
        research_goal_id=research_goal_id,
        manual_override_reason=manual_override_reason,
        thesis_id=thesis_id,
    )
    proposal = get_service().create_proposal(request)
    return _json(proposal)


@mcp.tool()
def approve_trade_proposal(proposal_id: str, approved_by: str = "hermes") -> dict:
    """Approve a pending proposal after revalidation. This records paper execution in the MVP."""
    return _json(get_service().approve_proposal(proposal_id, approved_by=approved_by))


@mcp.tool()
def reject_trade_proposal(proposal_id: str, reason: str = "Rejected from Hermes") -> dict:
    """Reject a pending proposal."""
    return _json(get_service().reject_proposal(proposal_id, reason=reason))


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
