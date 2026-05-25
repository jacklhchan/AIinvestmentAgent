from __future__ import annotations

from typing import Literal

from mcp.server.fastmcp import FastMCP

from .autonomy import SafeAutonomyRunner, autonomy_status
from .deps import get_service, get_store
from .config import get_settings
from .event_replay import DEFAULT_REPLAY_PATH, export_event_replay, replay_event_file as replay_events_from_file
from .futu_adapter import get_futu_status, refresh_futu_readonly
from .ir_feeds import IrFeedIngestor
from .market_news import MarketNewsIngestor, external_ticker, resolve_watchlist_symbols
from .models import ProposalCreate, ProposalStatus, ResearchEvidenceCreate, ResearchGoalCreate, ResearchGoalStatus, Side
from .primary_sources import refresh_primary_sources
from .proposal_drafts import ProposalDraftEngine
from .research_goals import ResearchGoalService
from .sec_companyfacts import SecCompanyFactsIngestor
from .sec_edgar import SecEdgarIngestor

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
    return _json(export_event_replay(get_store(), path, news_limit=news_limit))


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
