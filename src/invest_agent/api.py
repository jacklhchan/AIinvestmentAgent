from __future__ import annotations

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, PlainTextResponse, Response
from pydantic import BaseModel

from .advisor import AdvisorService
from .autonomy import SafeAutonomyRunner, autonomy_status
from .catalysts import CatalystCalendarService
from .config import get_settings
from .deps import get_service, get_store
from .earnings_review import EarningsReviewService
from .event_replay import DEFAULT_REPLAY_PATH, export_event_replay, replay_event_file
from .futu_adapter import FutuIntegrationError, get_futu_status, refresh_futu_readonly
from .ir_feeds import IrFeedIngestor
from .market_news import MarketNewsIngestor, external_ticker, resolve_watchlist_symbols
from .models import (
    AdvisorBriefRequest,
    CatalystCompleteRequest,
    CatalystCreate,
    CatalystReviewCreate,
    CatalystStatus,
    BehaviorReportRunRequest,
    CreatedBy,
    CreatedVia,
    EarningsReviewApplyRequest,
    EarningsReviewRunRequest,
    ProposalCreate,
    ProposalStatus,
    ResearchEvidenceCreate,
    ResearchGoalCreate,
    ResearchGoalStatus,
    RunCardActor,
    RunCardStatus,
    RunCardTriggerSource,
    RunCardType,
    ShadowReportRunRequest,
    ShadowStrategyConfirmRequest,
    ShadowStrategyExtractRequest,
    ShadowStrategyStatus,
    ThesisCreate,
    ThesisStatus,
    ThesisUpdateCreate,
    TradeFillSide,
    TradeJournalImportRequest,
    TradeJournalSource,
)
from .primary_sources import refresh_primary_sources
from .proposal_drafts import ProposalDraftEngine
from .research_goals import ResearchGoalService
from .run_cards import RunCardService
from .shadow_account import ShadowAccountService
from .sec_companyfacts import SecCompanyFactsIngestor
from .sec_edgar import SecEdgarIngestor
from .thesis_tracker import ThesisTrackerService
from .trade_journal import TradeJournalService


class RejectRequest(BaseModel):
    reason: str = "Rejected by user"


class NewsRefreshRequest(BaseModel):
    symbols: list[str] | None = None
    days: int | None = None
    max_per_symbol: int | None = None
    max_symbols: int | None = None
    include_gdelt: bool = True
    include_google_news: bool | None = None
    include_finnhub: bool = True


class DraftRequest(BaseModel):
    symbols: list[str] | None = None
    lookback_hours: int = 72
    max_drafts: int | None = None
    create_proposals: bool = False


class PrimarySourceRefreshRequest(BaseModel):
    symbols: list[str] | None = None
    include_sec: bool = True
    include_ir: bool = True
    forms: list[str] | None = None
    max_filings: int | None = None
    max_symbols: int | None = None


class FundamentalsRefreshRequest(BaseModel):
    symbols: list[str] | None = None
    max_symbols: int | None = None
    forms: list[str] | None = None


class EventReplayRequest(BaseModel):
    path: str = str(DEFAULT_REPLAY_PATH)
    create_proposals: bool = False
    run_drafts: bool = True


class AutonomyRunRequest(BaseModel):
    create_proposals: bool | None = None
    include_slow_sources: bool = True


app = FastAPI(
    title="AI Investment Agent Control Plane",
    version="0.1.0",
    description="Local proposal, approval, risk and paper execution plane for Hermes Agent.",
)


@app.get("/", response_class=HTMLResponse)
def dashboard() -> str:
    return DASHBOARD_HTML


@app.get("/favicon.ico", include_in_schema=False)
def favicon() -> Response:
    return Response(status_code=204)


@app.get("/health")
def health() -> dict:
    settings = get_settings()
    return {
        "ok": True,
        "mode": settings.mode,
        "paper_only": settings.is_paper,
        "db_path": str(settings.db_path),
        "futu_read_enabled": settings.futu_read_enabled,
        "futu_host": settings.futu_host,
        "futu_monitor_port": settings.futu_monitor_port,
    }


@app.get("/api/portfolio")
def portfolio():
    return get_store().get_portfolio()


@app.get("/api/quotes")
def quotes():
    return get_store().list_quotes()


@app.get("/api/advisor/brief")
def advisor_brief():
    return AdvisorService(get_store(), paper_only=get_settings().is_paper).build_brief()


@app.post("/api/advisor/brief")
def run_advisor_brief(request: AdvisorBriefRequest | None = None):
    request = request or AdvisorBriefRequest(run_light_analysis=True)
    return AdvisorService(get_store(), paper_only=get_settings().is_paper).build_brief(request)


@app.get("/api/watchlist")
def watchlist():
    return {"symbols": resolve_watchlist_symbols(get_settings(), get_store())}


@app.get("/api/news")
def news(limit: int = 20, symbol: str | None = None):
    return get_store().list_news(limit=limit, symbol=symbol)


@app.post("/api/news/refresh")
def refresh_news(request: NewsRefreshRequest | None = None):
    request = request or NewsRefreshRequest()
    return MarketNewsIngestor(get_settings(), get_store()).refresh_news(
        symbols=request.symbols,
        days=request.days,
        max_per_symbol=request.max_per_symbol,
        max_symbols=request.max_symbols,
        include_gdelt=request.include_gdelt,
        include_google_news=request.include_google_news,
        include_finnhub=request.include_finnhub,
    )


@app.post("/api/primary-sources/refresh")
def refresh_primary_sources_api(request: PrimarySourceRefreshRequest | None = None):
    request = request or PrimarySourceRefreshRequest()
    settings = get_settings()
    store = get_store()
    return refresh_primary_sources(
        SecEdgarIngestor(settings, store),
        IrFeedIngestor(settings, store),
        symbols=request.symbols,
        include_sec=request.include_sec,
        include_ir=request.include_ir,
        forms=request.forms,
        max_filings=request.max_filings,
        max_symbols=request.max_symbols,
    )


@app.get("/api/fundamentals")
def fundamentals():
    return get_store().list_fundamentals()


@app.get("/api/fundamentals/{symbol}")
def fundamental_snapshot(symbol: str):
    store = get_store()
    item = store.get_fundamentals(symbol)
    if not item:
        ticker = external_ticker(symbol)
        item = next((snapshot for snapshot in store.list_fundamentals() if external_ticker(snapshot.symbol) == ticker), None)
    if not item:
        raise HTTPException(status_code=404, detail="fundamental snapshot not found")
    return item


@app.post("/api/fundamentals/refresh")
def refresh_fundamentals(request: FundamentalsRefreshRequest | None = None):
    request = request or FundamentalsRefreshRequest()
    return SecCompanyFactsIngestor(get_settings(), get_store()).refresh_fundamentals(
        symbols=request.symbols,
        max_symbols=request.max_symbols,
        forms=request.forms,
    )


@app.get("/api/research-goals")
def research_goals(status: ResearchGoalStatus | None = None, symbol: str | None = None, limit: int = 50):
    return get_store().list_research_goals(status=status, symbol=symbol, limit=limit)


@app.post("/api/research-goals")
def create_research_goal(request: ResearchGoalCreate):
    try:
        return ResearchGoalService(get_store()).create_goal(request)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/research-goals/{goal_id}")
def research_goal(goal_id: str):
    item = get_store().get_research_goal(goal_id)
    if not item:
        raise HTTPException(status_code=404, detail="research goal not found")
    return item


@app.post("/api/research-goals/{goal_id}/evidence")
def add_research_evidence(goal_id: str, request: ResearchEvidenceCreate):
    try:
        return ResearchGoalService(get_store()).add_evidence(request.model_copy(update={"goal_id": goal_id}))
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/api/theses")
def theses(status: ThesisStatus | None = None, symbol: str | None = None, limit: int = 50):
    return get_store().list_theses(status=status, symbol=symbol, limit=limit)


@app.post("/api/theses")
def create_thesis(request: ThesisCreate):
    return ThesisTrackerService(get_store()).create_thesis(
        request.model_copy(
            update={
                "created_via": CreatedVia.DASHBOARD,
                "created_by": CreatedBy.HUMAN,
                "human_confirmed": True,
                "confirmed_by": "dashboard",
            }
        )
    )


@app.get("/api/theses/{thesis_id}")
def thesis(thesis_id: str):
    item = get_store().get_thesis(thesis_id)
    if not item:
        raise HTTPException(status_code=404, detail="thesis not found")
    return item


@app.post("/api/theses/{thesis_id}/updates")
def add_thesis_update(thesis_id: str, request: ThesisUpdateCreate):
    try:
        return ThesisTrackerService(get_store()).add_update(thesis_id, request)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/api/catalysts/upcoming")
def upcoming_catalysts(days: int = 14, symbol: str | None = None, limit: int = 50):
    return CatalystCalendarService(get_store()).list_upcoming(days=days, symbol=symbol, limit=limit)


@app.get("/api/catalysts")
def catalysts(status: CatalystStatus | None = None, symbol: str | None = None, limit: int = 50):
    return get_store().list_catalysts(status=status, symbol=symbol, limit=limit)


@app.post("/api/catalysts")
def create_catalyst(request: CatalystCreate):
    return CatalystCalendarService(get_store()).create_catalyst(
        request.model_copy(update={"created_via": CreatedVia.DASHBOARD, "created_by": CreatedBy.HUMAN}),
        human_verified=True,
    )


@app.get("/api/catalysts/{catalyst_id}")
def catalyst(catalyst_id: str):
    store = get_store()
    item = store.get_catalyst(catalyst_id)
    if not item:
        raise HTTPException(status_code=404, detail="catalyst not found")
    return {"catalyst": item, "reviews": store.list_catalyst_reviews(catalyst_id)}


@app.post("/api/catalysts/{catalyst_id}/complete")
def complete_catalyst(catalyst_id: str, request: CatalystCompleteRequest):
    try:
        return CatalystCalendarService(get_store()).complete_catalyst(catalyst_id, request)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/api/catalysts/{catalyst_id}/review")
def review_catalyst(catalyst_id: str, request: CatalystReviewCreate):
    try:
        return CatalystCalendarService(get_store()).create_review(catalyst_id, request)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/api/earnings-reviews")
def earnings_reviews(symbol: str | None = None, limit: int = 50):
    return get_store().list_earnings_reviews(symbol=symbol, limit=limit)


@app.post("/api/earnings-reviews/run")
def run_earnings_review(request: EarningsReviewRunRequest):
    settings = get_settings()
    store = get_store()
    if request.refresh_fundamentals:
        SecCompanyFactsIngestor(settings, store).refresh_fundamentals(symbols=[request.symbol], max_symbols=1)
    try:
        return EarningsReviewService(store).run_review(
            request,
            actor=RunCardActor.API,
            trigger_source=RunCardTriggerSource.MANUAL,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/earnings-reviews/{review_id}")
def earnings_review(review_id: str):
    item = get_store().get_earnings_review(review_id)
    if not item:
        raise HTTPException(status_code=404, detail="earnings review not found")
    return item


@app.post("/api/earnings-reviews/{review_id}/apply-to-thesis")
def apply_earnings_review_to_thesis(review_id: str, request: EarningsReviewApplyRequest | None = None):
    request = request or EarningsReviewApplyRequest()
    try:
        return EarningsReviewService(get_store()).apply_to_thesis(
            review_id,
            thesis_id=request.thesis_id,
            human_confirmed=request.human_confirmed,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/run-cards")
def run_cards(
    run_type: RunCardType | None = None,
    status: RunCardStatus | None = None,
    symbol: str | None = None,
    limit: int = 50,
):
    return get_store().list_run_cards(run_type=run_type, status=status, symbol=symbol, limit=limit)


@app.get("/api/run-cards/{run_card_id}")
def run_card(run_card_id: str):
    item = get_store().get_run_card(run_card_id)
    if not item:
        raise HTTPException(status_code=404, detail="run card not found")
    return item


@app.get("/api/run-cards/{run_card_id}/artifact", response_class=PlainTextResponse)
def run_card_artifact(run_card_id: str, kind: str = "json"):
    try:
        return RunCardService(get_store()).get_artifact_text(run_card_id, kind=kind)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/api/trade-imports")
def trade_imports(source: TradeJournalSource | None = None, limit: int = 50):
    return get_store().list_trade_imports(source=source, limit=limit)


@app.post("/api/trade-journal/import")
def import_trade_journal(request: TradeJournalImportRequest):
    try:
        return TradeJournalService(get_store()).import_csv(request, actor=RunCardActor.API)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/trade-fills")
def trade_fills(symbol: str | None = None, side: TradeFillSide | None = None, limit: int = 100):
    return get_store().list_trade_fills(symbol=symbol, side=side, limit=limit)


@app.get("/api/trade-roundtrips")
def trade_roundtrips(symbol: str | None = None, limit: int = 100):
    return get_store().list_trade_roundtrips(symbol=symbol, limit=limit)


@app.get("/api/behavior-reports")
def behavior_reports(symbol: str | None = None, limit: int = 50):
    return get_store().list_behavior_reports(symbol=symbol, limit=limit)


@app.post("/api/behavior-reports/run")
def run_behavior_report(request: BehaviorReportRunRequest | None = None):
    try:
        return TradeJournalService(get_store()).run_behavior_report(request or BehaviorReportRunRequest(), actor=RunCardActor.API)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/behavior-reports/{report_id}")
def behavior_report(report_id: str):
    item = get_store().get_behavior_report(report_id)
    if not item:
        raise HTTPException(status_code=404, detail="behavior report not found")
    return item


@app.post("/api/shadow-strategies/extract")
def extract_shadow_strategy(request: ShadowStrategyExtractRequest):
    try:
        return ShadowAccountService(get_store()).extract_strategy(request, actor=RunCardActor.API)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/shadow-strategies")
def shadow_strategies(status: ShadowStrategyStatus | None = None, limit: int = 50):
    return get_store().list_shadow_strategies(status=status, limit=limit)


@app.get("/api/shadow-strategies/{strategy_id}")
def shadow_strategy(strategy_id: str):
    item = get_store().get_shadow_strategy(strategy_id)
    if not item:
        raise HTTPException(status_code=404, detail="shadow strategy not found")
    return item


@app.post("/api/shadow-strategies/{strategy_id}/confirm")
def confirm_shadow_strategy(strategy_id: str, request: ShadowStrategyConfirmRequest | None = None):
    try:
        return ShadowAccountService(get_store()).confirm_strategy(
            strategy_id,
            request or ShadowStrategyConfirmRequest(),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/shadow-reports/run")
def run_shadow_report(request: ShadowReportRunRequest):
    try:
        return ShadowAccountService(get_store()).run_report(request, actor=RunCardActor.API)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/shadow-reports")
def shadow_reports(strategy_id: str | None = None, limit: int = 50):
    return get_store().list_shadow_reports(strategy_id=strategy_id, limit=limit)


@app.get("/api/shadow-reports/{report_id}")
def shadow_report(report_id: str):
    item = get_store().get_shadow_report(report_id)
    if not item:
        raise HTTPException(status_code=404, detail="shadow report not found")
    return item


@app.get("/api/shadow-events")
def shadow_events(report_id: str | None = None, symbol: str | None = None, limit: int = 100):
    return get_store().list_shadow_events(shadow_report_id=report_id, symbol=symbol, limit=limit)


@app.get("/api/autonomy/status")
def autonomy_status_api():
    return autonomy_status(get_settings(), get_store())


@app.post("/api/autonomy/run")
def run_autonomy_cycle(request: AutonomyRunRequest | None = None):
    request = request or AutonomyRunRequest()
    return SafeAutonomyRunner(get_settings(), get_store(), get_service()).run_cycle(
        mode="api-once",
        create_proposals=request.create_proposals,
        include_slow_sources=request.include_slow_sources,
    )


@app.post("/api/events/export")
def export_events(request: EventReplayRequest | None = None):
    request = request or EventReplayRequest()
    return export_event_replay(
        get_store(),
        request.path,
        actor=RunCardActor.API,
        trigger_source=RunCardTriggerSource.REPLAY,
    )


@app.post("/api/events/replay")
def replay_events(request: EventReplayRequest | None = None):
    request = request or EventReplayRequest()
    return replay_event_file(
        get_settings(),
        get_store(),
        request.path,
        create_proposals=request.create_proposals,
        run_drafts=request.run_drafts,
    )


@app.get("/api/proposals")
def proposals(status: ProposalStatus | None = None, limit: int = 100):
    return get_store().list_proposals(status=status, limit=limit)


@app.post("/api/proposal-drafts")
def proposal_drafts(request: DraftRequest | None = None):
    request = request or DraftRequest()
    return ProposalDraftEngine(get_settings(), get_store(), get_service()).draft_from_watchlist(
        symbols=request.symbols,
        lookback_hours=request.lookback_hours,
        max_drafts=request.max_drafts,
        create_proposals=request.create_proposals,
    )


@app.get("/api/proposals/{proposal_id}")
def proposal(proposal_id: str):
    item = get_store().get_proposal(proposal_id)
    if not item:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail="proposal not found")
    return item


@app.post("/api/proposals")
def create_proposal(request: ProposalCreate):
    return get_service().create_proposal(request)


@app.post("/api/proposals/{proposal_id}/approve")
def approve_proposal(proposal_id: str):
    return get_service().approve_proposal(proposal_id)


@app.post("/api/proposals/{proposal_id}/reject")
def reject_proposal(proposal_id: str, request: RejectRequest | None = None):
    reason = request.reason if request else "Rejected by user"
    return get_service().reject_proposal(proposal_id, reason=reason)


@app.get("/api/executions")
def executions(proposal_id: str | None = None):
    return get_store().list_executions(proposal_id=proposal_id)


@app.get("/api/audit")
def audit(limit: int = 100):
    return get_store().list_audit_events(limit=limit)


@app.get("/api/futu/status")
def futu_status():
    return get_futu_status(get_settings())


@app.post("/api/futu/refresh")
def futu_refresh(refresh_cache: bool = False):
    try:
        return refresh_futu_readonly(get_settings(), get_store(), refresh_cache=refresh_cache).as_dict()
    except FutuIntegrationError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


def main() -> None:
    settings = get_settings()
    uvicorn.run("invest_agent.api:app", host=settings.host, port=settings.port, reload=False)


DASHBOARD_HTML = """
<!doctype html>
<html lang="zh-Hant">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>投資代理控制台</title>
  <style>
    :root {
      color-scheme: light;
      --ink: #17211f;
      --muted: #65706c;
      --line: #d9ded8;
      --paper: #fbfcf7;
      --panel: #ffffff;
      --mint: #0f8a6b;
      --blue: #2455a6;
      --amber: #9a6400;
      --coral: #b8443b;
      --slate: #273238;
      --shadow: 0 12px 28px rgba(23, 33, 31, 0.08);
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      color: var(--ink);
      background:
        linear-gradient(90deg, rgba(23, 33, 31, 0.05) 1px, transparent 1px),
        linear-gradient(180deg, rgba(23, 33, 31, 0.04) 1px, transparent 1px),
        var(--paper);
      background-size: 32px 32px;
      font-family: "Avenir Next", "Gill Sans", "PingFang HK", "Microsoft JhengHei", sans-serif;
      letter-spacing: 0;
    }
    header {
      border-bottom: 1px solid var(--line);
      background: rgba(251, 252, 247, 0.94);
      backdrop-filter: blur(12px);
      position: sticky;
      top: 0;
      z-index: 10;
    }
    .bar {
      max-width: 1220px;
      margin: 0 auto;
      padding: 18px 24px;
      display: grid;
      grid-template-columns: 1fr auto;
      gap: 18px;
      align-items: center;
    }
    .brand {
      display: grid;
      gap: 6px;
    }
    h1 {
      margin: 0;
      font-family: Georgia, "Times New Roman", "PingFang HK", serif;
      font-size: 30px;
      line-height: 1;
      font-weight: 700;
    }
    .subtitle {
      color: var(--muted);
      font-size: 13px;
    }
    .bar-actions {
      display: flex;
      gap: 10px;
      align-items: center;
      justify-content: end;
      flex-wrap: wrap;
    }
    .mode {
      border: 1px solid var(--line);
      background: var(--panel);
      box-shadow: var(--shadow);
      padding: 9px 12px;
      border-radius: 6px;
      color: var(--muted);
      font-size: 13px;
      white-space: nowrap;
    }
    main {
      max-width: 1220px;
      margin: 0 auto;
      padding: 26px 24px 42px;
      display: grid;
      gap: 18px;
    }
    .topline {
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 12px;
    }
    .metric, .panel {
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      box-shadow: var(--shadow);
    }
    .metric {
      padding: 16px;
      min-height: 94px;
      display: grid;
      gap: 8px;
    }
    .label {
      color: var(--muted);
      font-size: 12px;
      letter-spacing: 0;
    }
    .value {
      font-family: Georgia, "Times New Roman", "PingFang HK", serif;
      font-size: 30px;
      line-height: 1;
    }
    .grid {
      display: grid;
      grid-template-columns: 1.2fr 0.8fr;
      gap: 18px;
      align-items: start;
    }
    .triple-grid {
      display: grid;
      grid-template-columns: 1fr 1fr 0.82fr;
      gap: 18px;
      align-items: start;
    }
    .panel h2 {
      margin: 0;
      padding: 15px 16px;
      font-size: 15px;
      border-bottom: 1px solid var(--line);
    }
    .panel-title-row {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      padding: 13px 16px;
      border-bottom: 1px solid var(--line);
    }
    .panel-title-row h2 {
      padding: 0;
      border-bottom: 0;
    }
    .advisor-shell {
      display: grid;
      grid-template-columns: minmax(0, 0.95fr) minmax(0, 1.35fr);
      gap: 0;
    }
    .advisor-summary {
      padding: 16px;
      border-right: 1px solid var(--line);
      display: grid;
      align-content: start;
      gap: 12px;
    }
    .advisor-headline {
      font-family: Georgia, "Times New Roman", "PingFang HK", serif;
      font-size: 23px;
      line-height: 1.22;
    }
    .advisor-list {
      display: grid;
      gap: 0;
    }
    .advisor-item {
      padding: 14px 16px;
      border-bottom: 1px solid var(--line);
      display: grid;
      gap: 7px;
    }
    .advisor-item:last-child { border-bottom: 0; }
    .advisor-meta {
      display: flex;
      gap: 8px;
      flex-wrap: wrap;
      align-items: center;
    }
    .advisor-actions {
      display: flex;
      gap: 8px;
      align-items: center;
      flex-wrap: wrap;
    }
    .source-strip {
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 0;
    }
    .source-cell {
      min-height: 88px;
      padding: 14px 16px;
      border-right: 1px solid var(--line);
      display: grid;
      align-content: start;
      gap: 7px;
    }
    .source-cell:last-child { border-right: 0; }
    table {
      width: 100%;
      border-collapse: collapse;
      table-layout: fixed;
    }
    th, td {
      padding: 11px 14px;
      border-bottom: 1px solid var(--line);
      text-align: left;
      font-size: 14px;
      vertical-align: top;
      overflow-wrap: anywhere;
    }
    th {
      color: var(--muted);
      font-size: 12px;
      letter-spacing: 0;
      background: #f5f7f1;
    }
    tr:last-child td { border-bottom: 0; }
    .pill, .source-badge {
      display: inline-flex;
      align-items: center;
      min-height: 24px;
      padding: 2px 8px;
      border-radius: 999px;
      border: 1px solid var(--line);
      color: var(--muted);
      font-size: 12px;
      font-weight: 700;
      white-space: nowrap;
    }
    .source-badge {
      width: fit-content;
      font-weight: 800;
    }
    .source-demo { color: var(--amber); border-color: #dfc68a; background: #fff7df; }
    .source-futu-opend { color: var(--blue); border-color: #9ab3df; background: #eef4ff; }
    .source-gdelt { color: #7047a8; border-color: #c2a8df; background: #f6f0ff; }
    .source-google-news { color: #3f6b20; border-color: #a8c990; background: #f1faed; }
    .source-finnhub { color: #0f7a8a; border-color: #91cfda; background: #edfafd; }
    .source-sec-edgar { color: #74431b; border-color: #d7b48a; background: #fff5e8; }
    .source-sec-companyfacts { color: #265b47; border-color: #9cc9b8; background: #effaf5; }
    .source-company-ir { color: #7a2457; border-color: #d6a2c0; background: #fff0f8; }
    .source-local { color: var(--slate); border-color: #b6c0bd; background: #f3f6f5; }
    .PENDING { color: var(--amber); border-color: #dfc68a; background: #fff7df; }
    .APPROVED, .EXECUTED { color: var(--mint); border-color: #9ad6c5; background: #eaf8f3; }
    .REJECTED, .RISK_REJECTED, .EXPIRED { color: var(--coral); border-color: #e6aaa5; background: #fff0ee; }
    .ACTIVE { color: var(--blue); border-color: #9ab3df; background: #eef4ff; }
    .COMPLETED { color: var(--mint); border-color: #9ad6c5; background: #eaf8f3; }
    .INSUFFICIENT { color: var(--amber); border-color: #dfc68a; background: #fff7df; }
    .active { color: var(--mint); border-color: #9ad6c5; background: #eaf8f3; }
    .watch { color: var(--amber); border-color: #dfc68a; background: #fff7df; }
    .info { color: var(--blue); border-color: #9ab3df; background: #eef4ff; }
    .action { color: var(--amber); border-color: #dfc68a; background: #fff7df; }
    .blocked { color: var(--coral); border-color: #e6aaa5; background: #fff0ee; }
    .invalidated, .archived { color: var(--coral); border-color: #e6aaa5; background: #fff0ee; }
    .upcoming { color: var(--blue); border-color: #9ab3df; background: #eef4ff; }
    .completed { color: var(--mint); border-color: #9ad6c5; background: #eaf8f3; }
    .cancelled, .missed { color: var(--coral); border-color: #e6aaa5; background: #fff0ee; }
    .high { color: var(--coral); border-color: #e6aaa5; background: #fff0ee; }
    .medium { color: var(--amber); border-color: #dfc68a; background: #fff7df; }
    .low { color: var(--mint); border-color: #9ad6c5; background: #eaf8f3; }
    .actions {
      display: flex;
      gap: 8px;
      flex-wrap: wrap;
    }
    button {
      border: 1px solid var(--line);
      background: var(--panel);
      color: var(--ink);
      border-radius: 6px;
      min-height: 34px;
      padding: 7px 10px;
      font: inherit;
      cursor: pointer;
    }
    button.primary { background: var(--mint); border-color: var(--mint); color: white; }
    button.secondary { color: var(--blue); }
    button.danger { color: var(--coral); }
    button:disabled { cursor: default; opacity: 0.55; }
    form {
      display: grid;
      gap: 12px;
      padding: 16px;
    }
    .form-grid {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 10px;
    }
    .field {
      display: grid;
      gap: 6px;
    }
    .field label {
      color: var(--muted);
      font-size: 12px;
    }
    input, select, textarea {
      width: 100%;
      min-height: 38px;
      border: 1px solid var(--line);
      border-radius: 6px;
      background: #fff;
      padding: 8px 10px;
      font: inherit;
      color: var(--ink);
    }
    textarea { min-height: 82px; resize: vertical; }
    .stack-list {
      display: grid;
      gap: 0;
    }
    .stack-item {
      padding: 14px 16px;
      border-bottom: 1px solid var(--line);
      display: grid;
      gap: 7px;
    }
    .stack-item:last-child { border-bottom: 0; }
    .item-title { font-weight: 700; }
    .muted { color: var(--muted); font-size: 13px; }
    .toast {
      min-height: 24px;
      color: var(--blue);
      font-size: 13px;
      padding: 0 16px 14px;
    }
    .empty {
      padding: 14px 16px;
      color: var(--muted);
      font-size: 13px;
    }
    @media (max-width: 980px) {
      .triple-grid { grid-template-columns: 1fr; }
      .advisor-shell { grid-template-columns: 1fr; }
      .advisor-summary { border-right: 0; border-bottom: 1px solid var(--line); }
      .source-strip { grid-template-columns: repeat(2, minmax(0, 1fr)); }
      .source-cell:nth-child(2) { border-right: 0; }
      .source-cell:nth-child(-n+2) { border-bottom: 1px solid var(--line); }
    }
    @media (max-width: 820px) {
      .bar, .grid, .topline, .form-grid, .source-strip { grid-template-columns: 1fr; }
      .source-cell { border-right: 0; border-bottom: 1px solid var(--line); }
      .source-cell:last-child { border-bottom: 0; }
      h1 { font-size: 26px; }
      .value { font-size: 25px; }
      main { padding: 18px 14px 32px; }
      th, td { padding: 10px; }
    }
  </style>
</head>
<body>
  <header>
    <div class="bar">
      <div class="brand">
        <h1>投資代理控制台</h1>
        <div class="subtitle">Hermes Agent / Codex LLM / 富途 OpenD 只讀資料流</div>
      </div>
      <div class="bar-actions">
        <button class="secondary" id="news-refresh" type="button">刷新市場新聞</button>
        <button class="secondary" id="primary-refresh" type="button">刷新 SEC/IR</button>
        <button class="secondary" id="fundamentals-refresh" type="button">刷新 SEC Fundamentals</button>
        <button class="secondary" id="autonomy-run" type="button">執行自治循環</button>
        <button class="secondary" id="draft-proposals" type="button">草擬並送風控</button>
        <button class="secondary" id="futu-refresh" type="button">刷新富途 OpenD</button>
        <div class="mode" id="mode">載入中</div>
      </div>
    </div>
  </header>
  <main>
    <section class="topline">
      <div class="metric"><div class="label">總資產</div><div class="value" id="total">$0</div></div>
      <div class="metric"><div class="label">現金</div><div class="value" id="cash">$0</div></div>
      <div class="metric"><div class="label">持倉數</div><div class="value" id="positions">0</div></div>
      <div class="metric"><div class="label">待審批</div><div class="value" id="pending">0</div></div>
    </section>
    <section class="panel">
      <div class="panel-title-row">
        <h2>AI Advisor Brief</h2>
        <div class="advisor-actions">
          <span class="muted">Agent 自動整理研究、事件、行為與 proposal 風險</span>
          <button class="primary" id="advisor-run" type="button">讓 Agent 自動分析</button>
        </div>
      </div>
      <div class="advisor-shell" id="advisor-brief">
        <div class="advisor-summary"><div class="muted">正在整理 advisor brief...</div></div>
        <div class="advisor-list"></div>
      </div>
      <div class="toast" id="advisor-toast"></div>
    </section>
    <section class="panel">
      <h2>資料來源與刷新狀態</h2>
      <div class="source-strip" id="source-strip"></div>
    </section>
    <section class="panel">
      <h2>安全自治狀態</h2>
      <div class="source-strip" id="autonomy-strip"></div>
    </section>
    <section class="panel">
      <h2>研究目標與證據帳本</h2>
      <table>
        <thead><tr><th>狀態</th><th>研究目標</th><th>證據 Gate</th><th>Claims / Criteria</th></tr></thead>
        <tbody id="research-goals"></tbody>
      </table>
    </section>
    <section class="grid">
      <div class="panel">
        <h2>投資論點</h2>
        <table>
          <thead><tr><th>狀態</th><th>標的</th><th>論點</th><th>支柱 / 風險</th></tr></thead>
          <tbody id="theses"></tbody>
        </table>
      </div>
      <div class="panel">
        <h2>新增投資論點</h2>
        <form id="thesis-form">
          <div class="form-grid">
            <div class="field"><label for="thesis_symbol">標的</label><input id="thesis_symbol" name="symbol" value="AAPL" required /></div>
            <div class="field"><label for="thesis_side">方向</label><select id="thesis_side" name="side"><option value="long">Long</option><option value="short">Short</option><option value="neutral_watch">觀察</option></select></div>
            <div class="field"><label for="thesis_conviction">信念強度</label><select id="thesis_conviction" name="conviction"><option value="medium">中</option><option value="high">高</option><option value="low">低</option></select></div>
            <div class="field"><label for="thesis_target_price">目標價</label><input id="thesis_target_price" name="target_price" type="number" min="0.01" step="0.01" /></div>
          </div>
          <div class="field"><label for="thesis_statement">核心論點</label><textarea id="thesis_statement" name="thesis_statement" required>長期 thesis 待填；每次 proposal 前都要用 evidence ledger 更新。</textarea></div>
          <div class="field"><label for="thesis_stop_loss">失效 / 停損觸發</label><textarea id="thesis_stop_loss" name="stop_loss_trigger">若核心營運指標與 thesis 相反，先停止加倉並重做研究。</textarea></div>
          <div class="field"><label for="thesis_pillars">支柱，每行一個</label><textarea id="thesis_pillars" name="pillars">收入與現金流趨勢支持 thesis
Primary-source evidence 沒有反向訊號</textarea></div>
          <div class="field"><label for="thesis_risks">風險，每行一個</label><textarea id="thesis_risks" name="risks">財報或 SEC filing 顯示 growth thesis 被削弱
估值或倉位風險超過 portfolio policy</textarea></div>
          <div class="field"><label for="thesis_invalidation">失效條件，每行對應一個風險</label><textarea id="thesis_invalidation" name="invalidation_conditions">收入、淨收入或 operating cash flow 多期惡化
proposal 需要靠 manual override 才能成立</textarea></div>
          <button class="primary" type="submit">建立論點</button>
        </form>
      </div>
    </section>
    <section class="grid">
      <div class="panel">
        <h2>催化事件</h2>
        <table>
          <thead><tr><th>狀態</th><th>事件</th><th>時間 / 影響</th><th>來源 / Review</th></tr></thead>
          <tbody id="catalysts"></tbody>
        </table>
      </div>
      <div class="panel">
        <h2>新增催化事件</h2>
        <form id="catalyst-form">
          <div class="form-grid">
            <div class="field"><label for="catalyst_symbol">標的</label><input id="catalyst_symbol" name="symbol" value="AAPL" /></div>
            <div class="field"><label for="catalyst_event_type">事件類型</label><select id="catalyst_event_type" name="event_type"><option value="earnings">Earnings</option><option value="investor_day">Investor Day</option><option value="product">產品</option><option value="regulatory">監管</option><option value="macro">宏觀</option><option value="conference">會議</option><option value="other">其他</option></select></div>
            <div class="field"><label for="catalyst_event_date">事件時間</label><input id="catalyst_event_date" name="event_date" type="datetime-local" required /></div>
            <div class="field"><label for="catalyst_impact">預期影響</label><select id="catalyst_impact" name="expected_impact"><option value="high">高</option><option value="medium">中</option><option value="low">低</option></select></div>
          </div>
          <div class="field"><label for="catalyst_title">事件標題</label><textarea id="catalyst_title" name="title" required>AAPL earnings / high-impact event 待確認</textarea></div>
          <div class="field"><label for="catalyst_description">備註</label><textarea id="catalyst_description" name="description">Dashboard 手動新增，視為 human_verified；proposal 前仍會受 catalyst invariant 約束。</textarea></div>
          <button class="primary" type="submit">建立事件</button>
        </form>
      </div>
    </section>
    <section class="grid">
      <div class="panel">
        <h2>財報檢討</h2>
        <table>
          <thead><tr><th>標的 / 期間</th><th>YoY 指標</th><th>Thesis Delta</th><th>證據</th></tr></thead>
          <tbody id="earnings-reviews"></tbody>
        </table>
      </div>
      <div class="panel">
        <h2>執行財報檢討</h2>
        <form id="earnings-review-form">
          <div class="form-grid">
            <div class="field"><label for="earnings_symbol">標的</label><input id="earnings_symbol" name="symbol" value="AAPL" required /></div>
            <div class="field"><label for="earnings_catalyst_id">Catalyst ID</label><input id="earnings_catalyst_id" name="catalyst_id" placeholder="可留空" /></div>
            <div class="field"><label for="earnings_thesis_id">Thesis ID</label><input id="earnings_thesis_id" name="thesis_id" placeholder="可留空" /></div>
            <div class="field"><label for="earnings_refresh">刷新 SEC</label><select id="earnings_refresh" name="refresh_fundamentals"><option value="false">使用本機快照</option><option value="true">先刷新</option></select></div>
          </div>
          <button class="primary" type="submit">建立財報檢討</button>
        </form>
      </div>
    </section>
    <section class="panel">
      <h2>研究執行紀錄</h2>
      <table>
        <thead><tr><th>狀態</th><th>Run</th><th>連結</th><th>Hash / Artifact</th></tr></thead>
        <tbody id="run-cards"></tbody>
      </table>
    </section>
    <section class="grid">
      <div class="panel">
        <h2>交易行為</h2>
        <table>
          <thead><tr><th>期間</th><th>績效輪廓</th><th>行為診斷</th><th>Run Card</th></tr></thead>
          <tbody id="behavior-reports"></tbody>
        </table>
      </div>
      <div class="panel">
        <h2>匯入交易日誌</h2>
        <form id="trade-import-form">
          <div class="field"><label for="trade_import_path">CSV 路徑</label><input id="trade_import_path" name="path" placeholder="/Users/apple/Downloads/futu_trades.csv" required /></div>
          <div class="field"><label for="trade_import_source">來源格式</label><select id="trade_import_source" name="source"><option value="futu_csv">Futu CSV</option><option value="generic_csv">Generic CSV</option></select></div>
          <button class="primary" type="submit">匯入交易紀錄</button>
        </form>
        <form id="behavior-report-form">
          <div class="form-grid">
            <div class="field"><label for="behavior_period_start">開始日期</label><input id="behavior_period_start" name="period_start" type="date" /></div>
            <div class="field"><label for="behavior_period_end">結束日期</label><input id="behavior_period_end" name="period_end" type="date" /></div>
            <div class="field"><label for="behavior_symbols">標的，可逗號分隔</label><input id="behavior_symbols" name="symbols" placeholder="AAPL,MSFT" /></div>
          </div>
          <button class="primary" type="submit">建立行為報告</button>
        </form>
        <table>
          <thead><tr><th>匯入</th><th>最近 Roundtrip</th></tr></thead>
          <tbody id="trade-journal-summary"></tbody>
        </table>
      </div>
    </section>
    <section class="grid">
      <div class="panel">
        <h2>影子帳戶</h2>
        <table>
          <thead><tr><th>狀態</th><th>策略 / 規則</th><th>來源</th><th>操作</th></tr></thead>
          <tbody id="shadow-strategies"></tbody>
        </table>
      </div>
      <div class="panel">
        <h2>反事實報告</h2>
        <form id="shadow-extract-form">
          <div class="form-grid">
            <div class="field"><label for="shadow_behavior_report_id">Behavior Report ID</label><input id="shadow_behavior_report_id" name="behavior_report_id" placeholder="beh_..." required /></div>
            <div class="field"><label for="shadow_strategy_name">策略名稱</label><input id="shadow_strategy_name" name="name" placeholder="可留空" /></div>
          </div>
          <button class="primary" type="submit">抽取影子規則</button>
        </form>
        <form id="shadow-report-form">
          <div class="form-grid">
            <div class="field"><label for="shadow_strategy_id">Strategy ID</label><input id="shadow_strategy_id" name="strategy_id" placeholder="shadow_..." required /></div>
            <div class="field"><label for="shadow_report_behavior_id">Behavior Report ID</label><input id="shadow_report_behavior_id" name="behavior_report_id" placeholder="可留空" /></div>
          </div>
          <button class="primary" type="submit">建立反事實報告</button>
        </form>
        <table>
          <thead><tr><th>報告</th><th>事件</th></tr></thead>
          <tbody id="shadow-reports"></tbody>
        </table>
      </div>
    </section>
    <section class="panel">
      <h2>SEC 基本面快照</h2>
      <table>
        <thead><tr><th>標的</th><th>收入</th><th>淨收入</th><th>現金流 / 來源</th></tr></thead>
        <tbody id="fundamentals"></tbody>
      </table>
    </section>
    <section class="grid">
      <div class="panel">
        <h2>交易提案</h2>
        <table>
          <thead><tr><th>狀態</th><th>交易意圖</th><th>風控結果</th><th>操作</th></tr></thead>
          <tbody id="proposals"></tbody>
        </table>
      </div>
      <div class="panel">
        <h2>新增提案</h2>
        <form id="proposal-form">
          <div class="form-grid">
            <div class="field"><label for="symbol">標的</label><input id="symbol" name="symbol" value="GOOGL" required /></div>
            <div class="field"><label for="side">方向</label><select id="side" name="side"><option value="BUY">買入</option><option value="SELL">賣出</option></select></div>
            <div class="field"><label for="qty">數量</label><input id="qty" name="qty" type="number" min="1" value="5" required /></div>
            <div class="field"><label for="limit_price">限價</label><input id="limit_price" name="limit_price" type="number" min="0.01" step="0.01" value="175.70" required /></div>
            <div class="field"><label for="confidence">信心分數</label><input id="confidence" name="confidence" type="number" min="0" max="1" step="0.01" value="0.62" required /></div>
            <div class="field"><label for="ttl_minutes">有效分鐘</label><input id="ttl_minutes" name="ttl_minutes" type="number" min="1" max="1440" value="15" required /></div>
          </div>
          <div class="field"><label for="trigger">觸發條件</label><textarea id="trigger" name="trigger" required>Watchlist 回調，且組合現金足夠</textarea></div>
          <div class="field"><label for="thesis">投資論點</label><textarea id="thesis" name="thesis" required>小額紙上交易，用來驗證審批、風控與 audit 流程。</textarea></div>
          <div class="field"><label for="manual_override_reason">手動覆寫理由</label><textarea id="manual_override_reason" name="manual_override_reason" required>Dashboard 手動建立 paper-only proposal；我確認此提案未通過自動 evidence gate，需人工審閱。</textarea></div>
          <button class="primary" type="submit">建立提案</button>
        </form>
        <div class="toast" id="toast"></div>
      </div>
    </section>
    <section class="triple-grid">
      <div class="panel">
        <h2>持倉</h2>
        <table>
          <thead><tr><th>標的</th><th>數量</th><th>最新價</th><th>市值 / 來源</th></tr></thead>
          <tbody id="position-rows"></tbody>
        </table>
      </div>
      <div class="panel">
        <h2>市場摘要</h2>
        <div class="stack-list" id="news"></div>
      </div>
      <div class="panel">
        <h2>操作紀錄</h2>
        <div class="stack-list" id="audit"></div>
      </div>
    </section>
  </main>
  <script>
    const money = value => new Intl.NumberFormat("zh-HK", { style: "currency", currency: "USD", maximumFractionDigits: 0 }).format(value || 0);
    const smallMoney = value => new Intl.NumberFormat("zh-HK", { style: "currency", currency: "USD", maximumFractionDigits: 2 }).format(value || 0);
    const htmlEscapeMap = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#039;" };
    const escapeHtml = value => String(value ?? "").replace(/[&<>"']/g, char => htmlEscapeMap[char]);
    const formatDate = value => {
      if (!value) return "未有紀錄";
      const date = new Date(value);
      if (Number.isNaN(date.getTime())) return "時間格式未知";
      return new Intl.DateTimeFormat("zh-HK", {
        month: "2-digit",
        day: "2-digit",
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit",
        hour12: false
      }).format(date);
    };
    const latestTime = items => {
      const times = items
        .map(item => Date.parse(item.updated_at || item.published_at || item.created_at))
        .filter(time => Number.isFinite(time));
      return times.length ? new Date(Math.max(...times)).toISOString() : null;
    };
    const statusLabels = {
      PENDING: "待審批",
      APPROVED: "已批准",
      REJECTED: "已拒絕",
      EXPIRED: "已過期",
      RISK_REJECTED: "風控拒絕",
      EXECUTED: "已執行"
    };
    const sideLabels = { BUY: "買入", SELL: "賣出" };
    const goalStatusLabels = {
      ACTIVE: "進行中",
      COMPLETED: "證據足夠",
      INSUFFICIENT: "證據不足",
      REJECTED: "已拒絕"
    };
    const criterionStatusLabels = {
      PENDING: "待補",
      SATISFIED: "已滿足",
      INSUFFICIENT: "不足",
      WAIVED: "略過"
    };
    const thesisStatusLabels = {
      active: "有效",
      watch: "觀察",
      invalidated: "已失效",
      archived: "已封存"
    };
    const thesisSideLabels = {
      long: "Long",
      short: "Short",
      neutral_watch: "觀察"
    };
    const convictionLabels = {
      high: "高",
      medium: "中",
      low: "低"
    };
    const catalystStatusLabels = {
      upcoming: "未發生",
      completed: "已完成",
      cancelled: "已取消",
      missed: "未追蹤"
    };
    const catalystTypeLabels = {
      earnings: "Earnings",
      investor_day: "Investor Day",
      analyst_day: "Analyst Day",
      product: "產品",
      regulatory: "監管",
      conference: "會議",
      macro: "宏觀",
      industry_data: "行業數據",
      shareholder_meeting: "股東會",
      other: "其他"
    };
    const impactLabels = { high: "高影響", medium: "中影響", low: "低影響" };
    const thesisDeltaLabels = {
      strengthens: "強化",
      weakens: "削弱",
      neutral: "中性",
      invalidates: "推翻",
      unknown: "未知"
    };
    const actionBiasLabels = {
      no_change: "不變",
      watch_only: "觀察",
      increase: "加碼候選",
      trim: "減碼候選",
      exit: "退出候選",
      block_new_proposal: "封鎖新提案"
    };
    const cashflowQualityLabels = {
      healthy: "健康",
      mixed: "混合",
      weak: "偏弱",
      unknown: "未知"
    };
    const runCardTypeLabels = {
      earnings_review: "財報檢討",
      catalyst_review: "催化事件 Review",
      event_replay: "事件重播",
      trade_journal_import: "交易日誌匯入",
      behavior_report: "交易行為報告",
      shadow_strategy_extract: "影子規則抽取",
      shadow_report: "影子帳戶報告",
      safe_autonomy_cycle: "自治循環",
      proposal_draft: "提案草稿",
      future_backtest_import: "Backtest 匯入",
      future_behavior_report: "交易行為報告"
    };
    const runCardStatusLabels = {
      running: "執行中",
      completed: "完成",
      failed: "失敗",
      cancelled: "取消"
    };
    const behaviorSeverityLabels = {
      low: "低",
      medium: "中",
      high: "高",
      unknown: "未知"
    };
    const behaviorDiagnosticLabels = {
      disposition_effect: "處分效應",
      overtrading: "過度交易",
      chasing_momentum: "追高",
      anchoring: "錨定"
    };
    const shadowStrategyStatusLabels = {
      draft: "草稿",
      active: "已確認",
      archived: "封存"
    };
    const shadowRuleLabels = {
      entry: "進場",
      exit: "出場",
      sizing: "倉位",
      cooldown: "冷卻",
      catalyst: "事件",
      thesis: "論點",
      stop_loss: "止損",
      take_profit: "停利"
    };
    const shadowEventLabels = {
      rule_followed: "規則符合",
      rule_violation: "規則偏離",
      early_exit: "太早退出",
      late_exit: "太晚退出",
      missed_entry: "錯失進場",
      oversized_trade: "倉位偏大",
      ignored_catalyst: "忽略催化事件",
      thesis_mismatch: "論點不符",
      post_event_review_missing: "缺少事件後 Review",
      contradicted_earnings_review: "與財報檢討相反"
    };
    const advisorSeverityLabels = {
      info: "資訊",
      watch: "觀察",
      action: "需要處理",
      blocked: "暫停行動"
    };
    const advisorCategoryLabels = {
      system: "系統",
      proposal: "提案",
      catalyst: "催化事件",
      earnings: "財報",
      behavior: "交易行為",
      shadow: "影子帳戶",
      thesis: "投資論點",
      research: "研究證據"
    };
    const verificationLabels = {
      unverified: "未驗證",
      source_verified: "來源驗證",
      human_verified: "人工確認",
      rejected: "已拒絕"
    };
    const sourceLabels = {
      demo: "Demo",
      "futu-opend": "富途 OpenD",
      gdelt: "GDELT",
      "google-news": "Google News",
      finnhub: "Finnhub",
      "sec-edgar": "SEC EDGAR",
      "sec-companyfacts": "SEC Company Facts",
      "company-ir": "公司 IR",
      "exchange-calendar": "交易所日曆",
      "macro-calendar": "宏觀日曆",
      manual: "手動",
      news: "新聞",
      other: "其他",
      local: "本機"
    };
    const eventLabels = {
      demo_seeded: "Demo 資料建立",
      portfolio_upserted: "投資組合已更新",
      futu_readonly_refreshed: "富途只讀刷新",
      proposal_created: "提案已建立",
      proposal_updated: "提案已更新",
      proposal_approved: "提案已批准",
      proposal_rejected: "提案已拒絕",
      proposal_expired: "提案已過期",
      paper_execution_recorded: "紙上交易紀錄",
      market_news_refreshed: "市場新聞已刷新",
      proposal_drafts_generated: "提案草稿已產生",
      sec_filings_refreshed: "SEC filings 已刷新",
      sec_companyfacts_refreshed: "SEC 基本面已刷新",
      fundamentals_upserted: "基本面快照已更新",
      trade_journal_import_created: "交易日誌匯入已建立",
      trade_fills_imported: "交易成交已匯入",
      trade_roundtrips_rebuilt: "交易 roundtrip 已重建",
      behavior_report_created: "交易行為報告已建立",
      shadow_strategy_created: "影子策略已建立",
      shadow_strategy_updated: "影子策略已更新",
      shadow_strategy_confirmed: "影子策略已確認",
      shadow_report_created: "影子報告已建立",
      autonomy_cycle_started: "自治循環已開始",
      autonomy_cycle_completed: "自治循環已完成",
      ir_feeds_refreshed: "公司 IR 已刷新",
      event_replay_exported: "事件重播已匯出",
      events_replayed: "事件已重播",
      research_goal_created: "研究目標已建立",
      research_evidence_added: "研究證據已加入",
      research_goal_completed: "研究 Gate 已通過",
      research_goal_insufficient: "研究 Gate 證據不足",
      research_goal_evaluated: "研究目標已評估",
      thesis_created: "投資論點已建立",
      thesis_updated: "投資論點已更新",
      thesis_update_added: "投資論點更新已加入",
      catalyst_created: "催化事件已建立",
      catalyst_updated: "催化事件已更新",
      catalyst_completed: "催化事件已完成",
      catalyst_review_created: "催化事件 Review 已建立",
      catalyst_review_applied: "催化事件 Review 已套用",
      catalyst_post_event_goal_created: "事件後研究目標已建立",
      earnings_review_created: "財報檢討已建立",
      earnings_review_goal_updated: "財報研究目標已更新",
      run_card_started: "Run Card 已開始",
      run_card_updated: "Run Card 已更新",
      run_card_completed: "Run Card 已完成",
      run_card_failed: "Run Card 已失敗",
      run_card_artifacts_written: "Run Card artifact 已寫入",
      proposal_research_invariant_rejected: "提案違反研究 Gate 不變式"
    };
    const sourceClass = source => `source-${String(source || "local").toLowerCase().replace(/[^a-z0-9]+/g, "-")}`;
    const sourceBadge = source => `<span class="source-badge ${sourceClass(source)}">${escapeHtml(sourceLabels[source] || source || "本機")}</span>`;
    const pill = (status, label) => `<span class="pill ${escapeHtml(status)}">${escapeHtml(label)}</span>`;
    const api = async (path, options = {}) => {
      const response = await fetch(path, { headers: { "Content-Type": "application/json" }, ...options });
      if (response.ok) return response.json();
      let message = await response.text();
      try {
        const parsed = JSON.parse(message);
        message = typeof parsed.detail === "string" ? parsed.detail : JSON.stringify(parsed.detail || parsed);
      } catch (_) {}
      throw new Error(message);
    };
    const apiOptional = async (path, fallback) => {
      try {
        return await api(path);
      } catch (error) {
        return fallback(error);
      }
    };
    const setToast = text => {
      document.querySelector("#toast").textContent = text;
      const advisorToast = document.querySelector("#advisor-toast");
      if (advisorToast) advisorToast.textContent = text;
    };

    function renderAdvisorBrief(brief) {
      const shell = document.querySelector("#advisor-brief");
      if (!brief) {
        shell.innerHTML = `<div class="advisor-summary"><div class="muted">Advisor brief 尚未建立。</div></div><div class="advisor-list"></div>`;
        return;
      }
      const summary = (brief.summary || []).map(item => `<div>${escapeHtml(item)}</div>`).join("");
      const actions = (brief.automated_actions || []).map(item => `<div>${escapeHtml(item)}</div>`).join("");
      const advice = (brief.advice || []).map(item => {
        const ids = (item.related_ids || []).slice(0, 5).map(id => `<span class="muted">${escapeHtml(id)}</span>`).join(" ");
        return `<div class="advisor-item">
          <div class="advisor-meta">${pill(item.severity, advisorSeverityLabels[item.severity] || item.severity)} ${pill(item.category, advisorCategoryLabels[item.category] || item.category)}</div>
          <div class="item-title">${escapeHtml(item.title)}</div>
          <div>${escapeHtml(item.rationale)}</div>
          <div class="muted">下一步：${escapeHtml(item.next_action)}</div>
          ${ids ? `<div>${ids}</div>` : ""}
        </div>`;
      }).join("") || `<div class="advisor-item"><div class="muted">暫時沒有建議項目。</div></div>`;
      shell.innerHTML = `
        <div class="advisor-summary">
          <div>${pill(brief.risk_level, advisorSeverityLabels[brief.risk_level] || brief.risk_level)} ${brief.paper_only ? pill("APPROVED", "paper-only") : pill("PENDING", "live requested")}</div>
          <div class="advisor-headline">${escapeHtml(brief.headline)}</div>
          <div class="muted">${summary || "暫時沒有摘要資料"}</div>
          ${actions ? `<div><div class="label">Agent 已自動完成</div><div class="muted">${actions}</div></div>` : `<div class="muted">按「讓 Agent 自動分析」會建立可重播的輕量行為分析，不會批准或下單。</div>`}
          <div class="muted">更新：${formatDate(brief.generated_at)}</div>
        </div>
        <div class="advisor-list">${advice}</div>
      `;
    }

    function renderSourceStrip(health, portfolio, quotes, futuStatus) {
      const quoteSources = quotes.reduce((acc, quote) => {
        const source = quote.source || "local";
        acc[source] = (acc[source] || 0) + 1;
        return acc;
      }, {});
      const quoteBadges = Object.entries(quoteSources)
        .map(([source, count]) => `${sourceBadge(source)} <span class="muted">${count} 筆</span>`)
        .join(" ");
      document.querySelector("#source-strip").innerHTML = `
        <div class="source-cell">
          <div class="label">投資組合來源</div>
          <div>${sourceBadge(portfolio.source || "local")}</div>
          <div class="muted">更新：${formatDate(portfolio.updated_at)}</div>
        </div>
        <div class="source-cell">
          <div class="label">行情來源</div>
          <div>${quoteBadges || sourceBadge("local")}</div>
          <div class="muted">最新：${formatDate(latestTime(quotes))}</div>
        </div>
        <div class="source-cell">
          <div class="label">富途 OpenD</div>
          <div>${futuStatus.connected ? pill("APPROVED", "已連線") : pill("EXPIRED", "未連線")}</div>
          <div class="muted">${escapeHtml(health.futu_host)}:${escapeHtml(health.futu_monitor_port)} · ${escapeHtml(futuStatus.message || "未檢查")}</div>
        </div>
        <div class="source-cell">
          <div class="label">執行模式</div>
          <div>${health.paper_only ? pill("APPROVED", "紙上交易") : pill("PENDING", "要求實盤")}</div>
          <div class="muted">審批後仍只寫入本機紀錄</div>
        </div>
      `;
    }

    function renderAutonomy(status) {
      const lastRun = status.last_run;
      const stepText = lastRun?.steps?.length
        ? `${lastRun.steps.filter(step => step.status === "ok").length}/${lastRun.steps.length} 步成功`
        : "未有紀錄";
      const created = lastRun?.created_count || 0;
      document.querySelector("#autonomy-strip").innerHTML = `
        <div class="source-cell">
          <div class="label">循環頻率</div>
          <div>${pill("PENDING", `${Math.round((status.cycle_seconds || 0) / 60)} 分鐘`)}</div>
          <div class="muted">由 launchd / CLI 常駐觸發</div>
        </div>
        <div class="source-cell">
          <div class="label">提案模式</div>
          <div>${status.create_proposals ? pill("APPROVED", "自動建立待審批") : pill("PENDING", "只產生草稿")}</div>
          <div class="muted">冷卻 ${escapeHtml(status.proposal_cooldown_minutes)} 分鐘，仍需人工批准</div>
        </div>
        <div class="source-cell">
          <div class="label">最近循環</div>
          <div>${stepText}</div>
          <div class="muted">${lastRun ? formatDate(lastRun.finished_at) : "尚未執行"} · 建立 ${created} 個 proposal</div>
        </div>
        <div class="source-cell">
          <div class="label">安全邊界</div>
          <div>${status.paper_only ? pill("APPROVED", "paper-only") : pill("PENDING", "live requested")}</div>
          <div class="muted">不 unlock Futu，不下實盤單</div>
        </div>
      `;
    }

    function renderPositions(portfolio, quotes) {
      const quoteBySymbol = new Map(quotes.map(quote => [quote.symbol, quote]));
      const rows = portfolio.positions.map(pos => {
        const quote = quoteBySymbol.get(pos.symbol);
        const source = quote?.source || portfolio.source || "local";
        const updated = quote?.updated_at || portfolio.updated_at;
        return `<tr>
          <td><strong>${escapeHtml(pos.symbol)}</strong></td>
          <td>${escapeHtml(pos.qty)}</td>
          <td>${smallMoney(pos.last_price)}</td>
          <td>${money(pos.market_value)}<br>${sourceBadge(source)} <span class="muted">${formatDate(updated)}</span></td>
        </tr>`;
      }).join("");
      document.querySelector("#position-rows").innerHTML = rows || `<tr><td colspan="4" class="muted">目前沒有持倉資料</td></tr>`;
    }

    const metricValue = metric => {
      if (!metric || metric.value === null || metric.value === undefined) return "未有資料";
      if ((metric.unit || "").toLowerCase().includes("share")) return Number(metric.value).toFixed(2);
      if ((metric.unit || "").toUpperCase() === "USD") {
        const absolute = Math.abs(Number(metric.value));
        if (absolute >= 1_000_000_000) return `$${(Number(metric.value) / 1_000_000_000).toFixed(1)}B`;
        if (absolute >= 1_000_000) return `$${(Number(metric.value) / 1_000_000).toFixed(1)}M`;
      }
      return new Intl.NumberFormat("zh-HK", { maximumFractionDigits: 2 }).format(metric.value);
    };
    const metricCell = metric => {
      if (!metric) return `<span class="muted">未有資料</span>`;
      const period = [metric.fiscal_year, metric.fiscal_period].filter(Boolean).join(" ") || metric.end_date || "未有期間";
      const yoy = metric.yoy_change_pct === null || metric.yoy_change_pct === undefined
        ? ""
        : ` · YoY ${metric.yoy_change_pct > 0 ? "+" : ""}${Number(metric.yoy_change_pct).toFixed(1)}%`;
      return `<strong>${metricValue(metric)}</strong><br><span class="muted">${escapeHtml(period)}${escapeHtml(yoy)} · ${escapeHtml(metric.form || "SEC")}</span>`;
    };
    function renderFundamentals(snapshots) {
      document.querySelector("#fundamentals").innerHTML = snapshots.map(snapshot => `
        <tr>
          <td><strong>${escapeHtml(snapshot.symbol)}</strong><br><span class="muted">${escapeHtml(snapshot.entity_name || snapshot.cik)}</span></td>
          <td>${metricCell(snapshot.metrics?.revenue)}</td>
          <td>${metricCell(snapshot.metrics?.net_income)}</td>
          <td>${metricCell(snapshot.metrics?.operating_cash_flow)}<br>${sourceBadge(snapshot.source || "sec-companyfacts")} <span class="muted">${formatDate(snapshot.updated_at)}</span></td>
        </tr>
      `).join("") || `<tr><td colspan="4" class="muted">尚未刷新 SEC Company Facts 基本面</td></tr>`;
    }

    function renderResearchGoals(goals) {
      document.querySelector("#research-goals").innerHTML = goals.map(goal => {
        const claims = (goal.claims || []).slice(0, 2).map(claim =>
          `<div>${escapeHtml(claim.text)} <span class="muted">(${escapeHtml(claim.status)})</span></div>`
        ).join("");
        const criteria = (goal.criteria || []).slice(0, 3).map(criterion =>
          `<div>${escapeHtml(criterionStatusLabels[criterion.status] || criterion.status)} · ${escapeHtml(criterion.text)}</div>`
        ).join("");
        return `<tr>
          <td>${pill(goal.status, goalStatusLabels[goal.status] || goal.status)}</td>
          <td><strong>${escapeHtml(goal.symbol || "組合")}</strong><br><span class="muted">${escapeHtml(goal.objective)}</span><br><span class="muted">${formatDate(goal.created_at)}</span></td>
          <td><strong>${escapeHtml(goal.evidence_count || 0)} 筆證據</strong><br><span class="muted">${escapeHtml(goal.summary || "等待證據寫入")}</span></td>
          <td>${claims || '<span class="muted">未有 claim</span>'}${criteria ? `<div class="muted">${criteria}</div>` : ""}</td>
        </tr>`;
      }).join("") || `<tr><td colspan="4" class="muted">尚未建立研究目標；新聞草稿會自動建立 evidence ledger。</td></tr>`;
    }

    function renderTheses(theses) {
      document.querySelector("#theses").innerHTML = theses.map(thesis => {
        const pillars = (thesis.pillars || []).slice(0, 3).map(pillar =>
          `<div>${escapeHtml(pillar.text)} <span class="muted">(${escapeHtml(pillar.status)})</span></div>`
        ).join("");
        const risks = (thesis.risks || []).slice(0, 2).map(risk =>
          `<div class="muted">風險：${escapeHtml(risk.text)} · ${escapeHtml(risk.invalidation_condition)}</div>`
        ).join("");
        const latest = (thesis.updates || [])[0];
        const latestText = latest
          ? `<br><span class="muted">最近更新：${escapeHtml(latest.impact)} · ${escapeHtml(latest.summary)}</span>`
          : "";
        return `<tr>
          <td>${pill(thesis.status, thesisStatusLabels[thesis.status] || thesis.status)}<br><span class="muted">信念 ${escapeHtml(convictionLabels[thesis.conviction] || thesis.conviction)}</span></td>
          <td><strong>${escapeHtml(thesis.symbol)}</strong><br><span class="muted">${escapeHtml(thesisSideLabels[thesis.side] || thesis.side)}${thesis.target_price ? ` · 目標 ${smallMoney(thesis.target_price)}` : ""}</span></td>
          <td>${escapeHtml(thesis.thesis_statement)}${latestText}<br><span class="muted">失效：${escapeHtml(thesis.stop_loss_trigger || "未設定")}</span></td>
          <td>${pillars || '<span class="muted">未有 pillar</span>'}${risks}</td>
        </tr>`;
      }).join("") || `<tr><td colspan="4" class="muted">尚未建立投資論點；可先為 watchlist 建立 thesis，再讓 draft proposal 自動引用。</td></tr>`;
    }

    function renderCatalysts(catalysts) {
      document.querySelector("#catalysts").innerHTML = catalysts.map(catalyst => {
        const source = `${sourceBadge(catalyst.source_type || "manual")} <span class="muted">${escapeHtml(verificationLabels[catalyst.verification_status] || catalyst.verification_status)}</span>`;
        const review = catalyst.linked_research_goal_id
          ? `Research Goal ${escapeHtml(catalyst.linked_research_goal_id)}`
          : (catalyst.status === "completed" ? "等待 post-event review" : "未發生");
        return `<tr>
          <td>${pill(catalyst.status, catalystStatusLabels[catalyst.status] || catalyst.status)}</td>
          <td><strong>${escapeHtml(catalyst.symbol || "組合")}</strong><br>${escapeHtml(catalyst.title)}<br><span class="muted">${escapeHtml(catalystTypeLabels[catalyst.event_type] || catalyst.event_type)}</span></td>
          <td>${formatDate(catalyst.event_date)}<br>${pill(catalyst.expected_impact, impactLabels[catalyst.expected_impact] || catalyst.expected_impact)} <span class="muted">${escapeHtml(catalyst.event_time_hint || "unknown")}</span></td>
          <td>${source}<br><span class="muted">${escapeHtml(review)}</span></td>
        </tr>`;
      }).join("") || `<tr><td colspan="4" class="muted">未來 14 天沒有催化事件；可先手動新增 earnings / macro / investor day。</td></tr>`;
    }

    const pctText = value => value === null || value === undefined ? "n/a" : `${Number(value) > 0 ? "+" : ""}${Number(value).toFixed(1)}%`;
    function renderEarningsReviews(reviews) {
      document.querySelector("#earnings-reviews").innerHTML = reviews.map(review => {
        const metrics = [
          `收入 ${pctText(review.revenue_yoy)}`,
          `淨利 ${pctText(review.net_income_yoy)}`,
          `OCF ${pctText(review.operating_cash_flow_yoy)}`,
          `EPS ${pctText(review.diluted_eps_yoy)}`
        ].join("<br>");
        return `<tr>
          <td><strong>${escapeHtml(review.symbol)}</strong><br><span class="muted">${escapeHtml(review.period || "unknown")} · ${formatDate(review.created_at)}</span></td>
          <td>${metrics}<br><span class="muted">Cashflow ${escapeHtml(cashflowQualityLabels[review.cashflow_quality] || review.cashflow_quality)}</span></td>
          <td>${pill(review.thesis_delta, thesisDeltaLabels[review.thesis_delta] || review.thesis_delta)}<br><span class="muted">${escapeHtml(actionBiasLabels[review.action_bias] || review.action_bias)} · score ${escapeHtml(review.score)}</span></td>
          <td>${sourceBadge("sec-companyfacts")}<br><span class="muted">${escapeHtml((review.evidence_hash || "").slice(0, 12))}${review.catalyst_id ? ` · Catalyst ${escapeHtml(review.catalyst_id)}` : ""}</span></td>
        </tr>`;
      }).join("") || `<tr><td colspan="4" class="muted">尚未建立財報檢討；可先刷新 SEC Fundamentals，再執行 earnings review。</td></tr>`;
    }

    function renderRunCards(runCards) {
      document.querySelector("#run-cards").innerHTML = runCards.map(card => {
        const links = [
          card.research_goal_id ? `Goal ${escapeHtml(card.research_goal_id)}` : "",
          card.earnings_review_id ? `Earnings ${escapeHtml(card.earnings_review_id)}` : "",
          card.catalyst_review_id ? `Catalyst Review ${escapeHtml(card.catalyst_review_id)}` : "",
          card.catalyst_id ? `Catalyst ${escapeHtml(card.catalyst_id)}` : ""
        ].filter(Boolean).join("<br>") || '<span class="muted">未連結</span>';
        const artifactKinds = (card.artifacts || []).map(item => escapeHtml(item.kind)).join(", ") || "未寫入";
        const warningText = (card.warnings || []).length ? `<br><span class="muted">Warnings ${escapeHtml(card.warnings.length)}</span>` : "";
        return `<tr>
          <td>${pill(card.status, runCardStatusLabels[card.status] || card.status)}</td>
          <td><strong>${escapeHtml(card.symbol || "組合")}</strong><br>${escapeHtml(runCardTypeLabels[card.run_type] || card.run_type)}<br><span class="muted">${formatDate(card.started_at)} · ${escapeHtml(card.actor)}</span></td>
          <td>${links}${warningText}</td>
          <td><span class="muted">input ${escapeHtml((card.input_hash || "").slice(0, 10))}</span><br><span class="muted">output ${escapeHtml((card.output_hash || "").slice(0, 10))}</span><br><span class="muted">${artifactKinds}</span></td>
        </tr>`;
      }).join("") || `<tr><td colspan="4" class="muted">尚未有 run card；財報檢討和 event replay 會自動建立。</td></tr>`;
    }

    function renderBehaviorReports(reports) {
      document.querySelector("#behavior-reports").innerHTML = reports.map(report => {
        const diagnostics = Object.entries(report.diagnostics || {}).map(([key, diagnostic]) =>
          `${pill(diagnostic.severity, `${behaviorDiagnosticLabels[key] || key} ${behaviorSeverityLabels[diagnostic.severity] || diagnostic.severity}`)}`
        ).join(" ");
        const period = `${report.period_start ? formatDate(report.period_start) : "全部"} → ${report.period_end ? formatDate(report.period_end) : "現在"}`;
        return `<tr>
          <td><strong>${escapeHtml((report.symbols || []).join(", ") || "全部標的")}</strong><br><span class="muted">${period}</span></td>
          <td>交易 ${escapeHtml(report.total_trades)} · Roundtrip ${escapeHtml(report.total_roundtrips)}<br><span class="muted">勝率 ${Math.round((report.win_rate || 0) * 100)}% · 盈虧比 ${Number(report.profit_loss_ratio || 0).toFixed(2)} · 回撤 ${smallMoney(report.max_drawdown || 0)}</span></td>
          <td>${diagnostics || '<span class="muted">未有診斷</span>'}</td>
          <td><span class="muted">${escapeHtml(report.run_card_id || "n/a")}</span><br><span class="muted">PnL ${smallMoney(report.total_realized_pnl || 0)}</span></td>
        </tr>`;
      }).join("") || `<tr><td colspan="4" class="muted">尚未建立交易行為報告；先匯入 Futu / generic CSV，再建立 behavior report。</td></tr>`;
    }

    function renderTradeJournalSummary(imports, roundtrips) {
      const latestImport = imports[0];
      const latestRoundtrip = roundtrips[0];
      document.querySelector("#trade-journal-summary").innerHTML = `
        <tr>
          <td>${latestImport ? `<strong>${escapeHtml(latestImport.filename)}</strong><br><span class="muted">${escapeHtml(latestImport.source)} · ${escapeHtml(latestImport.row_count)} rows · ${formatDate(latestImport.imported_at)}</span>` : '<span class="muted">未匯入</span>'}</td>
          <td>${latestRoundtrip ? `<strong>${escapeHtml(latestRoundtrip.symbol)}</strong> ${escapeHtml(latestRoundtrip.qty)}<br><span class="muted">PnL ${smallMoney(latestRoundtrip.realized_pnl)} · ${Number(latestRoundtrip.holding_days || 0).toFixed(1)} 天</span>` : '<span class="muted">未有 closed roundtrip</span>'}</td>
        </tr>`;
    }

    function renderShadowStrategies(strategies) {
      document.querySelector("#shadow-strategies").innerHTML = strategies.map(strategy => {
        const rules = (strategy.rules || []).slice(0, 4).map(rule =>
          `${pill(rule.rule_type, shadowRuleLabels[rule.rule_type] || rule.rule_type)} <span class="muted">${escapeHtml(rule.support_count)} 筆</span>`
        ).join(" ");
        const action = strategy.status === "draft"
          ? `<button class="secondary" data-confirm-shadow="${escapeHtml(strategy.id)}">確認</button>`
          : `<span class="muted">read-only</span>`;
        return `<tr>
          <td>${pill(strategy.status, shadowStrategyStatusLabels[strategy.status] || strategy.status)}<br><span class="muted">${strategy.human_confirmed ? "human confirmed" : "等待人工確認"}</span></td>
          <td><strong>${escapeHtml(strategy.name)}</strong><br>${rules || '<span class="muted">未有規則</span>'}</td>
          <td><span class="muted">${escapeHtml(strategy.source_behavior_report_id)}</span><br><span class="muted">${formatDate(strategy.created_at)}</span></td>
          <td>${action}</td>
        </tr>`;
      }).join("") || `<tr><td colspan="4" class="muted">尚未抽取影子策略；先建立 behavior report，再抽取 draft rules。</td></tr>`;
    }

    function renderShadowReports(reports, events) {
      const eventsByReport = events.reduce((acc, event) => {
        (acc[event.shadow_report_id] ||= []).push(event);
        return acc;
      }, {});
      document.querySelector("#shadow-reports").innerHTML = reports.map(report => {
        const linkedEvents = eventsByReport[report.id] || [];
        const eventSummary = linkedEvents.slice(0, 4).map(event =>
          `${pill(event.event_type, shadowEventLabels[event.event_type] || event.event_type)} <span class="muted">${escapeHtml(event.symbol)}</span>`
        ).join(" ") || '<span class="muted">未有事件</span>';
        return `<tr>
          <td><strong>${escapeHtml(report.id)}</strong><br><span class="muted">策略 ${escapeHtml(report.strategy_id)} · 交易 ${escapeHtml(report.total_evaluated_trades)}</span><br><span class="muted">實際 PnL ${smallMoney(report.actual_pnl || 0)} · CF ${report.counterfactual_pnl === null || report.counterfactual_pnl === undefined ? "n/a" : smallMoney(report.counterfactual_pnl)}</span></td>
          <td>${eventSummary}<br><span class="muted">偏離 ${escapeHtml(report.rule_violation_count)} · 早退 ${escapeHtml(report.early_exit_count)} · 晚退 ${escapeHtml(report.late_exit_count)}</span></td>
        </tr>`;
      }).join("") || `<tr><td colspan="2" class="muted">尚未建立反事實報告；確認 shadow strategy 後再執行。</td></tr>`;
    }

    function renderProposals(proposals) {
      document.querySelector("#proposals").innerHTML = proposals.map(p => {
        const risk = p.risk_check.passed ? "通過" : (p.risk_check.reasons || []).map(escapeHtml).join("; ");
        const warnings = (p.risk_check.warnings || []).length ? `<br><span class="muted">提示：${p.risk_check.warnings.map(escapeHtml).join("; ")}</span>` : "";
        const actions = p.status === "PENDING"
          ? `<div class="actions"><button class="primary" data-approve="${escapeHtml(p.id)}">批准</button><button class="danger" data-reject="${escapeHtml(p.id)}">拒絕</button></div>`
          : `<span class="muted">無可用操作</span>`;
        return `<tr>
          <td>${pill(p.status, statusLabels[p.status] || p.status)}</td>
          <td><strong>${escapeHtml(p.symbol)} ${escapeHtml(sideLabels[p.side] || p.side)} ${escapeHtml(p.qty)}</strong><br><span class="muted">${smallMoney(p.limit_price)} · 信心 ${Math.round(p.confidence * 100)}%</span></td>
          <td>${risk || "未有風控訊息"}${warnings}<br><span class="muted">${escapeHtml(p.trigger)}</span></td>
          <td>${actions}</td>
        </tr>`;
      }).join("") || `<tr><td colspan="4" class="muted">目前沒有交易提案</td></tr>`;
    }

    function renderNews(news) {
      document.querySelector("#news").innerHTML = news.map(item => `
        <div class="stack-item">
          <div class="item-title">${item.symbol ? `${escapeHtml(item.symbol)} · ` : ""}${escapeHtml(item.title)}</div>
          <div>${sourceBadge(item.source || "local")} <span class="muted">${formatDate(item.published_at)}</span></div>
          <div class="muted">${escapeHtml(item.summary || "")}</div>
        </div>
      `).join("") || `<div class="empty">目前沒有市場摘要</div>`;
    }

    function renderAudit(auditEvents) {
      document.querySelector("#audit").innerHTML = auditEvents.map(event => `
        <div class="stack-item">
          <div class="item-title">${escapeHtml(eventLabels[event.event_type] || event.event_type)}</div>
          <div class="muted">${escapeHtml(event.entity_type)} · ${escapeHtml(event.entity_id)}</div>
          <div class="muted">${formatDate(event.created_at)}</div>
        </div>
      `).join("") || `<div class="empty">目前沒有操作紀錄</div>`;
    }

    async function loadAll() {
      const [advisorBrief, health, portfolio, quotes, proposals, news, auditEvents, futuStatus, fundamentals, autonomy, researchGoals, theses, catalysts, earningsReviews, runCards, behaviorReports, tradeImports, tradeRoundtrips, shadowStrategies, shadowReports, shadowEvents] = await Promise.all([
        api("/api/advisor/brief"),
        api("/health"),
        api("/api/portfolio"),
        api("/api/quotes"),
        api("/api/proposals"),
        api("/api/news?limit=8"),
        api("/api/audit?limit=6"),
        apiOptional("/api/futu/status", error => ({ connected: false, message: error.message })),
        api("/api/fundamentals"),
        api("/api/autonomy/status"),
        api("/api/research-goals?limit=8"),
        api("/api/theses?limit=8"),
        api("/api/catalysts/upcoming?days=14&limit=8"),
        api("/api/earnings-reviews?limit=8"),
        api("/api/run-cards?limit=8"),
        api("/api/behavior-reports?limit=5"),
        api("/api/trade-imports?limit=5"),
        api("/api/trade-roundtrips?limit=5"),
        api("/api/shadow-strategies?limit=5"),
        api("/api/shadow-reports?limit=5"),
        api("/api/shadow-events?limit=20")
      ]);
      document.querySelector("#mode").textContent = health.paper_only ? "紙上交易模式" : "已要求實盤模式";
      const futuButton = document.querySelector("#futu-refresh");
      futuButton.disabled = !health.futu_read_enabled;
      futuButton.textContent = health.futu_read_enabled ? `刷新富途 OpenD :${health.futu_monitor_port}` : "富途讀取未啟用";
      document.querySelector("#total").textContent = money(portfolio.total_value_usd);
      document.querySelector("#cash").textContent = money(portfolio.cash_usd);
      document.querySelector("#positions").textContent = portfolio.positions.length;
      document.querySelector("#pending").textContent = proposals.filter(p => p.status === "PENDING").length;
      renderAdvisorBrief(advisorBrief);
      renderSourceStrip(health, portfolio, quotes, futuStatus);
      renderAutonomy(autonomy);
      renderResearchGoals(researchGoals);
      renderTheses(theses);
      renderCatalysts(catalysts);
      renderEarningsReviews(earningsReviews);
      renderRunCards(runCards);
      renderBehaviorReports(behaviorReports);
      renderTradeJournalSummary(tradeImports, tradeRoundtrips);
      renderShadowStrategies(shadowStrategies);
      renderShadowReports(shadowReports, shadowEvents);
      renderFundamentals(fundamentals);
      renderPositions(portfolio, quotes);
      renderProposals(proposals);
      renderNews(news);
      renderAudit(auditEvents);
    }

    document.addEventListener("click", async event => {
      const approveId = event.target.dataset.approve;
      const rejectId = event.target.dataset.reject;
      const confirmShadowId = event.target.dataset.confirmShadow;
      try {
        if (approveId) {
          await api(`/api/proposals/${approveId}/approve`, { method: "POST" });
          setToast(`已批准 ${approveId}`);
          await loadAll();
        }
        if (rejectId) {
          await api(`/api/proposals/${rejectId}/reject`, { method: "POST", body: JSON.stringify({ reason: "在中文 Dashboard 拒絕" }) });
          setToast(`已拒絕 ${rejectId}`);
          await loadAll();
        }
        if (confirmShadowId) {
          await api(`/api/shadow-strategies/${confirmShadowId}/confirm`, {
            method: "POST",
            body: JSON.stringify({ human_confirmed: true, confirmed_by: "dashboard" })
          });
          setToast(`已確認影子策略 ${confirmShadowId}`);
          await loadAll();
        }
      } catch (error) {
        setToast(error.message);
      }
    });
    document.querySelector("#advisor-run").addEventListener("click", async event => {
      event.target.disabled = true;
      setToast("Advisor 正在自動整理研究、行為與風險，不會批准或下單...");
      try {
        const brief = await api("/api/advisor/brief", {
          method: "POST",
          body: JSON.stringify({ run_light_analysis: true, max_items: 8 })
        });
        renderAdvisorBrief(brief);
        const actionNote = brief.automated_actions?.length ? `；已完成 ${brief.automated_actions.length} 個分析動作` : "";
        setToast(`Advisor brief 已更新${actionNote}`);
        await loadAll();
        renderAdvisorBrief(brief);
      } catch (error) {
        setToast(error.message);
      } finally {
        event.target.disabled = false;
      }
    });
    document.querySelector("#futu-refresh").addEventListener("click", async event => {
      event.target.disabled = true;
      setToast("正在刷新富途 OpenD 只讀快照...");
      try {
        const result = await api("/api/futu/refresh", { method: "POST" });
        setToast(`富途已刷新：${result.position_count} 個持倉，${result.quote_count} 筆行情`);
        await loadAll();
      } catch (error) {
        setToast(error.message);
      } finally {
        event.target.disabled = false;
      }
    });
    document.querySelector("#news-refresh").addEventListener("click", async event => {
      event.target.disabled = true;
      setToast("正在從 watchlist 刷新市場新聞...");
      try {
        const result = await api("/api/news/refresh", { method: "POST", body: JSON.stringify({}) });
        const errorNote = result.errors?.length ? `；${result.errors.length} 個來源有錯誤` : "";
        setToast(`市場新聞已入庫：${result.stored_count} 筆，watchlist ${result.symbols.length} 個標的${errorNote}`);
        await loadAll();
      } catch (error) {
        setToast(error.message);
      } finally {
        event.target.disabled = false;
      }
    });
    document.querySelector("#primary-refresh").addEventListener("click", async event => {
      event.target.disabled = true;
      setToast("正在刷新 SEC/IR primary-source evidence...");
      try {
        const result = await api("/api/primary-sources/refresh", { method: "POST", body: JSON.stringify({}) });
        const errorNote = result.errors?.length ? `；${result.errors.length} 個來源有錯誤` : "";
        setToast(`SEC/IR 已入庫：${result.stored_count} 筆 primary-source evidence${errorNote}`);
        await loadAll();
      } catch (error) {
        setToast(error.message);
      } finally {
        event.target.disabled = false;
      }
    });
    document.querySelector("#fundamentals-refresh").addEventListener("click", async event => {
      event.target.disabled = true;
      setToast("正在刷新 SEC Company Facts 基本面...");
      try {
        const result = await api("/api/fundamentals/refresh", { method: "POST", body: JSON.stringify({}) });
        const errorNote = result.errors?.length ? `；${result.errors.length} 個來源有錯誤` : "";
        setToast(`SEC 基本面已更新：${result.stored_count} 個標的${errorNote}`);
        await loadAll();
      } catch (error) {
        setToast(error.message);
      } finally {
        event.target.disabled = false;
      }
    });
    document.querySelector("#autonomy-run").addEventListener("click", async event => {
      event.target.disabled = true;
      setToast("正在執行安全自治循環...");
      try {
        const result = await api("/api/autonomy/run", {
          method: "POST",
          body: JSON.stringify({ include_slow_sources: true })
        });
        const errorNote = result.errors?.length ? `；${result.errors.length} 個步驟有錯誤` : "";
        setToast(`自治循環完成：${result.steps.length} 個步驟，建立 ${result.created_proposals.length} 個待審批提案${errorNote}`);
        await loadAll();
      } catch (error) {
        setToast(error.message);
      } finally {
        event.target.disabled = false;
      }
    });
    document.querySelector("#draft-proposals").addEventListener("click", async event => {
      event.target.disabled = true;
      setToast("正在根據新聞草擬提案並送入風控...");
      try {
        const result = await api("/api/proposal-drafts", {
          method: "POST",
          body: JSON.stringify({ create_proposals: true })
        });
        setToast(`已產生 ${result.drafts.length} 個草稿，送入風控 ${result.created.length} 個提案`);
        await loadAll();
      } catch (error) {
        setToast(error.message);
      } finally {
        event.target.disabled = false;
      }
    });
    document.querySelector("#proposal-form").addEventListener("submit", async event => {
      event.preventDefault();
      const form = new FormData(event.target);
      const body = {
        symbol: form.get("symbol"),
        side: form.get("side"),
        qty: Number(form.get("qty")),
        limit_price: Number(form.get("limit_price")),
        confidence: Number(form.get("confidence")),
        ttl_minutes: Number(form.get("ttl_minutes")),
        trigger: form.get("trigger"),
        thesis: form.get("thesis"),
        evidence: ["zh-Hant-dashboard"],
        counter_evidence: [],
        manual_override_reason: form.get("manual_override_reason")
      };
      try {
        const created = await api("/api/proposals", { method: "POST", body: JSON.stringify(body) });
        setToast(`已建立 ${created.id}，狀態：${statusLabels[created.status] || created.status}`);
        await loadAll();
      } catch (error) {
        setToast(error.message);
      }
    });
    const linesFrom = value => String(value || "").split("\\n").map(item => item.trim()).filter(Boolean);
    document.querySelector("#thesis-form").addEventListener("submit", async event => {
      event.preventDefault();
      const form = new FormData(event.target);
      const risks = linesFrom(form.get("risks"));
      const invalidation = linesFrom(form.get("invalidation_conditions"));
      const targetPrice = Number(form.get("target_price"));
      const body = {
        symbol: form.get("symbol"),
        side: form.get("side"),
        conviction: form.get("conviction"),
        target_price: Number.isFinite(targetPrice) && targetPrice > 0 ? targetPrice : null,
        thesis_statement: form.get("thesis_statement"),
        stop_loss_trigger: form.get("stop_loss_trigger"),
        pillars: linesFrom(form.get("pillars")).map(text => ({ text })),
        risks: risks.map((text, index) => ({
          text,
          invalidation_condition: invalidation[index] || text
        }))
      };
      try {
        const created = await api("/api/theses", { method: "POST", body: JSON.stringify(body) });
        setToast(`已建立投資論點 ${created.id}`);
        await loadAll();
      } catch (error) {
        setToast(error.message);
      }
    });
    document.querySelector("#catalyst-form").addEventListener("submit", async event => {
      event.preventDefault();
      const form = new FormData(event.target);
      const eventDate = new Date(form.get("event_date"));
      const body = {
        symbol: form.get("symbol") || null,
        event_type: form.get("event_type"),
        title: form.get("title"),
        description: form.get("description"),
        event_date: eventDate.toISOString(),
        expected_impact: form.get("expected_impact"),
        source_type: "manual",
        verification_status: "human_verified"
      };
      try {
        const created = await api("/api/catalysts", { method: "POST", body: JSON.stringify(body) });
        setToast(`已建立催化事件 ${created.id}`);
        await loadAll();
      } catch (error) {
        setToast(error.message);
      }
    });
    document.querySelector("#earnings-review-form").addEventListener("submit", async event => {
      event.preventDefault();
      const form = new FormData(event.target);
      const body = {
        symbol: form.get("symbol"),
        catalyst_id: form.get("catalyst_id") || null,
        thesis_id: form.get("thesis_id") || null,
        refresh_fundamentals: form.get("refresh_fundamentals") === "true"
      };
      try {
        const created = await api("/api/earnings-reviews/run", { method: "POST", body: JSON.stringify(body) });
        setToast(`已建立財報檢討 ${created.id}，delta：${thesisDeltaLabels[created.thesis_delta] || created.thesis_delta}`);
        await loadAll();
      } catch (error) {
        setToast(error.message);
      }
    });
    document.querySelector("#trade-import-form").addEventListener("submit", async event => {
      event.preventDefault();
      const form = new FormData(event.target);
      try {
        const created = await api("/api/trade-journal/import", {
          method: "POST",
          body: JSON.stringify({ path: form.get("path"), source: form.get("source") })
        });
        setToast(`已匯入交易日誌 ${created.id}，rows：${created.row_count}`);
        await loadAll();
      } catch (error) {
        setToast(error.message);
      }
    });
    document.querySelector("#behavior-report-form").addEventListener("submit", async event => {
      event.preventDefault();
      const form = new FormData(event.target);
      const start = form.get("period_start");
      const end = form.get("period_end");
      const symbols = String(form.get("symbols") || "").split(",").map(item => item.trim()).filter(Boolean);
      const body = {
        period_start: start ? `${start}T00:00:00Z` : null,
        period_end: end ? `${end}T23:59:59Z` : null,
        symbols: symbols.length ? symbols : null
      };
      try {
        const created = await api("/api/behavior-reports/run", { method: "POST", body: JSON.stringify(body) });
        setToast(`已建立交易行為報告 ${created.id}，roundtrips：${created.total_roundtrips}`);
        await loadAll();
      } catch (error) {
        setToast(error.message);
      }
    });
    document.querySelector("#shadow-extract-form").addEventListener("submit", async event => {
      event.preventDefault();
      const form = new FormData(event.target);
      const body = {
        behavior_report_id: form.get("behavior_report_id"),
        name: form.get("name") || null
      };
      try {
        const created = await api("/api/shadow-strategies/extract", { method: "POST", body: JSON.stringify(body) });
        setToast(`已抽取影子策略 ${created.id}，狀態：${shadowStrategyStatusLabels[created.status] || created.status}`);
        await loadAll();
      } catch (error) {
        setToast(error.message);
      }
    });
    document.querySelector("#shadow-report-form").addEventListener("submit", async event => {
      event.preventDefault();
      const form = new FormData(event.target);
      const body = {
        strategy_id: form.get("strategy_id"),
        behavior_report_id: form.get("behavior_report_id") || null
      };
      try {
        const created = await api("/api/shadow-reports/run", { method: "POST", body: JSON.stringify(body) });
        setToast(`已建立反事實報告 ${created.id}，偏離：${created.rule_violation_count}`);
        await loadAll();
      } catch (error) {
        setToast(error.message);
      }
    });
    loadAll().catch(error => setToast(error.message));
  </script>
</body>
</html>
"""


if __name__ == "__main__":
    main()
