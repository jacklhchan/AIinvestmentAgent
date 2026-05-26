from __future__ import annotations

from typing import Literal

from mcp.server.fastmcp import FastMCP

from .autonomy import SafeAutonomyRunner, autonomy_status
from .catalysts import CatalystCalendarService, mcp_catalyst_request
from .deps import get_service, get_store
from .config import get_settings
from .earnings_review import EarningsReviewService
from .event_replay import DEFAULT_REPLAY_PATH, export_event_replay, replay_event_file as replay_events_from_file
from .futu_adapter import get_futu_status, refresh_futu_readonly
from .ir_feeds import IrFeedIngestor
from .market_news import MarketNewsIngestor, external_ticker, resolve_watchlist_symbols
from .models import (
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
        "trade_journal_import",
        "behavior_report",
        "shadow_strategy_extract",
        "shadow_report",
        "safe_autonomy_cycle",
        "proposal_draft",
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
    """Refresh local portfolio and quotes from Futu OpenD without unlocking trading."""
    return refresh_futu_readonly(get_settings(), get_store(), refresh_cache=refresh_cache).as_dict()


@mcp.tool()
def list_pending_proposals(limit: int = 20) -> list[dict]:
    """List pending trade proposals awaiting human approval."""
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
