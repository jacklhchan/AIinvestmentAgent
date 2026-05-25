from __future__ import annotations

from typing import Literal

from mcp.server.fastmcp import FastMCP

from .deps import get_service, get_store
from .config import get_settings
from .futu_adapter import get_futu_status, refresh_futu_readonly
from .market_news import MarketNewsIngestor, resolve_watchlist_symbols
from .models import ProposalCreate, ProposalStatus, Side
from .proposal_drafts import ProposalDraftEngine

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
) -> dict:
    """Create a risk-checked trade proposal. The MVP records paper proposals only."""
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
