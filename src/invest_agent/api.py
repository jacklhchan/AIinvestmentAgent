from __future__ import annotations

import uvicorn
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from .config import get_settings
from .deps import get_service, get_store
from .models import ProposalCreate, ProposalStatus


class RejectRequest(BaseModel):
    reason: str = "Rejected by user"


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
    }


@app.get("/api/portfolio")
def portfolio():
    return get_store().get_portfolio()


@app.get("/api/quotes")
def quotes():
    return get_store().list_quotes()


@app.get("/api/news")
def news(limit: int = 20, symbol: str | None = None):
    return get_store().list_news(limit=limit, symbol=symbol)


@app.get("/api/proposals")
def proposals(status: ProposalStatus | None = None, limit: int = 100):
    return get_store().list_proposals(status=status, limit=limit)


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


def main() -> None:
    settings = get_settings()
    uvicorn.run("invest_agent.api:app", host=settings.host, port=settings.port, reload=False)


DASHBOARD_HTML = """
<!doctype html>
<html lang="zh-Hant">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>AI Investment Agent</title>
  <style>
    :root {
      color-scheme: light;
      --ink: #17211f;
      --muted: #66706d;
      --line: #d9ded8;
      --paper: #fbfcf7;
      --panel: #ffffff;
      --mint: #0f8a6b;
      --blue: #2455a6;
      --amber: #9a6400;
      --coral: #b8443b;
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
      font-family: "Avenir Next", "Gill Sans", "Trebuchet MS", sans-serif;
      letter-spacing: 0;
    }
    header {
      border-bottom: 1px solid var(--line);
      background: rgba(251, 252, 247, 0.92);
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
    h1 {
      margin: 0;
      font-family: Georgia, "Times New Roman", serif;
      font-size: 30px;
      line-height: 1;
      font-weight: 700;
    }
    .mode {
      border: 1px solid var(--line);
      background: var(--panel);
      box-shadow: var(--shadow);
      padding: 9px 12px;
      border-radius: 6px;
      color: var(--muted);
      font-size: 13px;
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
      text-transform: uppercase;
      letter-spacing: 0;
    }
    .value {
      font-family: Georgia, "Times New Roman", serif;
      font-size: 30px;
      line-height: 1;
    }
    .grid {
      display: grid;
      grid-template-columns: 1.2fr 0.8fr;
      gap: 18px;
      align-items: start;
    }
    .panel h2 {
      margin: 0;
      padding: 15px 16px;
      font-size: 15px;
      border-bottom: 1px solid var(--line);
    }
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
      text-transform: uppercase;
      letter-spacing: 0;
      background: #f5f7f1;
    }
    tr:last-child td { border-bottom: 0; }
    .pill {
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
    .PENDING { color: var(--amber); border-color: #dfc68a; background: #fff7df; }
    .APPROVED, .EXECUTED { color: var(--mint); border-color: #9ad6c5; background: #eaf8f3; }
    .REJECTED, .RISK_REJECTED, .EXPIRED { color: var(--coral); border-color: #e6aaa5; background: #fff0ee; }
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
    button.danger { color: var(--coral); }
    button:disabled { cursor: default; opacity: 0.55; }
    form {
      display: grid;
      gap: 10px;
      padding: 16px;
    }
    .form-grid {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 10px;
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
    .news-list {
      display: grid;
      gap: 0;
    }
    .news-item {
      padding: 14px 16px;
      border-bottom: 1px solid var(--line);
    }
    .news-item:last-child { border-bottom: 0; }
    .news-title { font-weight: 700; margin-bottom: 6px; }
    .muted { color: var(--muted); font-size: 13px; }
    .toast {
      min-height: 24px;
      color: var(--blue);
      font-size: 13px;
      padding: 0 16px 14px;
    }
    @media (max-width: 820px) {
      .bar, .grid, .topline, .form-grid { grid-template-columns: 1fr; }
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
      <h1>AI Investment Agent</h1>
      <div class="mode" id="mode">Loading</div>
    </div>
  </header>
  <main>
    <section class="topline">
      <div class="metric"><div class="label">Portfolio Value</div><div class="value" id="total">$0</div></div>
      <div class="metric"><div class="label">Cash</div><div class="value" id="cash">$0</div></div>
      <div class="metric"><div class="label">Positions</div><div class="value" id="positions">0</div></div>
      <div class="metric"><div class="label">Pending</div><div class="value" id="pending">0</div></div>
    </section>
    <section class="grid">
      <div class="panel">
        <h2>Proposals</h2>
        <table>
          <thead><tr><th>Status</th><th>Intent</th><th>Risk</th><th>Actions</th></tr></thead>
          <tbody id="proposals"></tbody>
        </table>
      </div>
      <div class="panel">
        <h2>Create Proposal</h2>
        <form id="proposal-form">
          <div class="form-grid">
            <input name="symbol" placeholder="Symbol" value="GOOGL" required />
            <select name="side"><option>BUY</option><option>SELL</option></select>
            <input name="qty" type="number" min="1" value="5" required />
            <input name="limit_price" type="number" min="0.01" step="0.01" value="175.70" required />
            <input name="confidence" type="number" min="0" max="1" step="0.01" value="0.62" required />
            <input name="ttl_minutes" type="number" min="1" max="1440" value="15" required />
          </div>
          <textarea name="trigger" required>Watchlist pullback with portfolio cash available</textarea>
          <textarea name="thesis" required>Small paper allocation to validate the approval and risk workflow before any broker integration.</textarea>
          <button class="primary" type="submit">Create</button>
        </form>
        <div class="toast" id="toast"></div>
      </div>
    </section>
    <section class="grid">
      <div class="panel">
        <h2>Positions</h2>
        <table>
          <thead><tr><th>Symbol</th><th>Qty</th><th>Last</th><th>Value</th></tr></thead>
          <tbody id="position-rows"></tbody>
        </table>
      </div>
      <div class="panel">
        <h2>News Digest</h2>
        <div class="news-list" id="news"></div>
      </div>
    </section>
  </main>
  <script>
    const money = value => new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 }).format(value || 0);
    const smallMoney = value => new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 2 }).format(value || 0);
    const api = async (path, options = {}) => {
      const response = await fetch(path, { headers: { "Content-Type": "application/json" }, ...options });
      if (!response.ok) throw new Error(await response.text());
      return response.json();
    };
    const setToast = text => { document.querySelector("#toast").textContent = text; };
    async function loadAll() {
      const [health, portfolio, proposals, news] = await Promise.all([
        api("/health"),
        api("/api/portfolio"),
        api("/api/proposals"),
        api("/api/news?limit=8")
      ]);
      document.querySelector("#mode").textContent = health.paper_only ? "Paper mode" : "Live mode requested";
      document.querySelector("#total").textContent = money(portfolio.total_value_usd);
      document.querySelector("#cash").textContent = money(portfolio.cash_usd);
      document.querySelector("#positions").textContent = portfolio.positions.length;
      document.querySelector("#pending").textContent = proposals.filter(p => p.status === "PENDING").length;
      document.querySelector("#position-rows").innerHTML = portfolio.positions.map(pos => `
        <tr><td>${pos.symbol}</td><td>${pos.qty}</td><td>${smallMoney(pos.last_price)}</td><td>${money(pos.market_value)}</td></tr>
      `).join("");
      document.querySelector("#proposals").innerHTML = proposals.map(p => {
        const risk = p.risk_check.passed ? "Passed" : p.risk_check.reasons.join("; ");
        const actions = p.status === "PENDING"
          ? `<div class="actions"><button class="primary" data-approve="${p.id}">Approve</button><button class="danger" data-reject="${p.id}">Reject</button></div>`
          : `<span class="muted">No action</span>`;
        return `<tr>
          <td><span class="pill ${p.status}">${p.status}</span></td>
          <td><strong>${p.symbol} ${p.side} ${p.qty}</strong><br><span class="muted">${smallMoney(p.limit_price)} · conf ${Math.round(p.confidence * 100)}%</span></td>
          <td>${risk}<br><span class="muted">${p.trigger}</span></td>
          <td>${actions}</td>
        </tr>`;
      }).join("");
      document.querySelector("#news").innerHTML = news.map(item => `
        <div class="news-item">
          <div class="news-title">${item.symbol ? item.symbol + " · " : ""}${item.title}</div>
          <div class="muted">${item.source} · ${new Date(item.published_at).toLocaleString()}</div>
        </div>
      `).join("");
    }
    document.addEventListener("click", async event => {
      const approveId = event.target.dataset.approve;
      const rejectId = event.target.dataset.reject;
      try {
        if (approveId) {
          await api(`/api/proposals/${approveId}/approve`, { method: "POST" });
          setToast(`Approved ${approveId}`);
          await loadAll();
        }
        if (rejectId) {
          await api(`/api/proposals/${rejectId}/reject`, { method: "POST", body: JSON.stringify({ reason: "Rejected in dashboard" }) });
          setToast(`Rejected ${rejectId}`);
          await loadAll();
        }
      } catch (error) {
        setToast(error.message);
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
        evidence: ["dashboard"],
        counter_evidence: []
      };
      try {
        const created = await api("/api/proposals", { method: "POST", body: JSON.stringify(body) });
        setToast(`Created ${created.id} as ${created.status}`);
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
