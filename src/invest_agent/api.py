from __future__ import annotations

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from .autonomy import SafeAutonomyRunner, autonomy_status
from .config import get_settings
from .deps import get_service, get_store
from .event_replay import DEFAULT_REPLAY_PATH, export_event_replay, replay_event_file
from .futu_adapter import FutuIntegrationError, get_futu_status, refresh_futu_readonly
from .ir_feeds import IrFeedIngestor
from .market_news import MarketNewsIngestor, external_ticker, resolve_watchlist_symbols
from .models import ProposalCreate, ProposalStatus, ResearchEvidenceCreate, ResearchGoalCreate, ResearchGoalStatus
from .primary_sources import refresh_primary_sources
from .proposal_drafts import ProposalDraftEngine
from .research_goals import ResearchGoalService
from .sec_companyfacts import SecCompanyFactsIngestor
from .sec_edgar import SecEdgarIngestor


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
    return export_event_replay(get_store(), request.path)


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
    const sourceLabels = {
      demo: "Demo",
      "futu-opend": "富途 OpenD",
      gdelt: "GDELT",
      "google-news": "Google News",
      finnhub: "Finnhub",
      "sec-edgar": "SEC EDGAR",
      "sec-companyfacts": "SEC Company Facts",
      "company-ir": "公司 IR",
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
    const setToast = text => { document.querySelector("#toast").textContent = text; };

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
      const [health, portfolio, quotes, proposals, news, auditEvents, futuStatus, fundamentals, autonomy, researchGoals] = await Promise.all([
        api("/health"),
        api("/api/portfolio"),
        api("/api/quotes"),
        api("/api/proposals"),
        api("/api/news?limit=8"),
        api("/api/audit?limit=6"),
        apiOptional("/api/futu/status", error => ({ connected: false, message: error.message })),
        api("/api/fundamentals"),
        api("/api/autonomy/status"),
        api("/api/research-goals?limit=8")
      ]);
      document.querySelector("#mode").textContent = health.paper_only ? "紙上交易模式" : "已要求實盤模式";
      const futuButton = document.querySelector("#futu-refresh");
      futuButton.disabled = !health.futu_read_enabled;
      futuButton.textContent = health.futu_read_enabled ? `刷新富途 OpenD :${health.futu_monitor_port}` : "富途讀取未啟用";
      document.querySelector("#total").textContent = money(portfolio.total_value_usd);
      document.querySelector("#cash").textContent = money(portfolio.cash_usd);
      document.querySelector("#positions").textContent = portfolio.positions.length;
      document.querySelector("#pending").textContent = proposals.filter(p => p.status === "PENDING").length;
      renderSourceStrip(health, portfolio, quotes, futuStatus);
      renderAutonomy(autonomy);
      renderResearchGoals(researchGoals);
      renderFundamentals(fundamentals);
      renderPositions(portfolio, quotes);
      renderProposals(proposals);
      renderNews(news);
      renderAudit(auditEvents);
    }

    document.addEventListener("click", async event => {
      const approveId = event.target.dataset.approve;
      const rejectId = event.target.dataset.reject;
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
      } catch (error) {
        setToast(error.message);
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
    loadAll().catch(error => setToast(error.message));
  </script>
</body>
</html>
"""


if __name__ == "__main__":
    main()
