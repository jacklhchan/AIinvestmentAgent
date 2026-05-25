# AI Investment Agent Status

Last updated: 2026-05-25

## Current State

The local MVP is implemented in `/Users/apple/Documents/AIinvestmentAgent`.

This version is intentionally paper-only. It can create trade proposals, run policy checks, accept or reject approvals, record paper executions, and expose the same control plane to Hermes through MCP. It does not unlock Futu OpenD and does not place live broker orders.

## Implemented

- FastAPI control plane on `127.0.0.1:8788`.
- SQLite-backed local store for portfolio snapshot, quotes, news, proposals, executions, and audit events.
- Demo portfolio, quotes, and news seed data.
- Watchlist resolver that merges configured symbols, held positions, and locally cached quotes.
- Market/news ingestion from GDELT, Google News RSS fallback, and optional Finnhub company news when `FINNHUB_API_KEY` is configured.
- SEC EDGAR primary-source ingestion for company filings, plus configurable company IR RSS ingestion.
- SEC companyfacts/XBRL fundamentals ingestion for revenue, net income, operating income, operating cash flow, assets, liabilities, equity, and diluted EPS.
- Event replay export/import for portfolio, quotes, news/evidence, and fundamental snapshot JSONL.
- Proposal draft engine that turns recent symbol-specific watchlist news into structured draft proposals and can optionally send them through the existing policy engine.
- Risk checks for max notional, cash availability, portfolio percentage, confidence floor, duplicate pending proposals, and approval-time price drift.
- Traditional Chinese browser dashboard for portfolio, pending proposals, create proposal, approve/reject, positions, news digest, source provenance, refresh timestamps, and recent audit events.
- Futu OpenD read-only refresh for account funds, positions, and position quote snapshots.
- Hermes stdio MCP server exposing:
  - `get_portfolio_snapshot`
  - `get_watchlist_quotes`
  - `get_watchlist_symbols`
  - `get_news_digest`
  - `refresh_market_news`
  - `refresh_primary_source_filings`
  - `refresh_sec_company_facts`
  - `get_fundamental_snapshot`
  - `export_event_replay_file`
  - `replay_event_file`
  - `draft_trade_proposals_from_watchlist`
  - `get_futu_connection_status`
  - `refresh_futu_readonly_snapshot`
  - `list_pending_proposals`
  - `create_trade_proposal`
  - `approve_trade_proposal`
  - `reject_trade_proposal`
- Hermes config snippet at `deploy/hermes/config.snippet.yaml`.
- launchd example plist at `deploy/launchd/com.local.invest-agent-api.plist`.
- Tests for proposal creation, approval, risk rejection, duplicate proposal blocking, non-pending state handling, Futu adapter mapping, dashboard localization, news parsing, watchlist resolution, SEC/IR parsing, event replay, and proposal draft creation.

## Local Hermes/Codex Setup

Hermes Agent v0.14.0 was installed under `/Users/apple/.hermes/hermes-agent`.

The global Hermes config at `/Users/apple/.hermes/config.yaml` has been updated locally to use:

- Provider: `openai-codex`
- Model: `gpt-5.2-codex`
- Reasoning effort: `high`
- MCP server: `invest_agent`

`hermes auth status openai-codex` shows logged in.

`hermes mcp list` shows `invest_agent` enabled with 17 selected tools.

## Futu Setup

The app now supports a read-only Futu OpenD refresh path. The current local OpenD screen shows:

- OpenD connected
- API port `11111`
- US stocks quote permission available
- Trade still locked

Local `.env` has `FUTU_READ_ENABLED=true` for this machine. `.env.example` keeps it disabled by default.

Read-only refresh commands:

```bash
python -m invest_agent.cli futu-refresh
curl -X POST http://127.0.0.1:8788/api/futu/refresh
```

This integration only calls account/quote read APIs and does not call `unlock_trade`, `place_order`, or `modify_order`.

## Market News + Proposal Drafting

The app now implements the next design-plan slice: a middle-loop news cadence plus structured proposal drafts.

- `POST /api/news/refresh` refreshes watchlist news from GDELT, Google News RSS fallback, and optional Finnhub.
- `POST /api/proposal-drafts` generates structured draft proposals from recent news.
- `create_proposals=false` keeps drafts as research output for Hermes/Codex review.
- `create_proposals=true` sends the drafts through the existing policy engine and creates `PENDING` or `RISK_REJECTED` proposals.
- Dashboard buttons are available for `刷新市場新聞` and `草擬並送風控`.
- CLI commands are available through `python -m invest_agent.cli news-refresh`, `draft-proposals`, and `draft-and-create`.

This phase still does not unlock Futu OpenD and does not place live orders.

## Primary Sources + Event Replay

The app now ingests primary-source evidence before relying on news-derived proposal quality.

- `POST /api/primary-sources/refresh` refreshes SEC EDGAR filings and configured company IR RSS feeds.
- SEC filings are stored as `sec-edgar` / `primary-source` news items.
- Company IR RSS items are stored as `company-ir` / `primary-source` news items when `INVEST_AGENT_IR_RSS_FEEDS` is configured.
- Proposal drafts still require directional news; primary-source evidence is attached as context and does not independently create a trade direction.
- `python -m invest_agent.cli event-export` writes portfolio, quotes, and news/evidence to JSONL.
- `python -m invest_agent.cli event-replay` replays that JSONL and re-runs draft generation for signal review.
- Dashboard has a `刷新 SEC/IR` action and displays `SEC EDGAR` / `公司 IR` source badges.

## SEC Company Facts Fundamentals

The app now parses SEC `companyfacts` XBRL JSON into local fundamental snapshots.

- `POST /api/fundamentals/refresh` refreshes watchlist fundamentals.
- `GET /api/fundamentals` and `GET /api/fundamentals/{symbol}` expose cached snapshots.
- `python -m invest_agent.cli fundamentals-refresh` refreshes fundamentals from the CLI.
- Hermes MCP exposes `refresh_sec_company_facts` and `get_fundamental_snapshot`.
- Event replay now includes `fundamental_snapshot` events.
- Proposal drafts attach SEC companyfacts evidence and add counter-evidence when revenue, net income, or operating cash flow YoY contradicts the news-derived direction.
- Dashboard has a `刷新 SEC Fundamentals` action and a `SEC 基本面快照` table.

This phase still does not unlock Futu OpenD and does not place live orders.

## Dashboard UX

The dashboard is now localized in Traditional Chinese and includes:

- Source badges for `Demo`, `富途 OpenD`, and local data.
- Portfolio, quote, news, and audit refresh timestamps.
- Futu OpenD connection status for the configured host/port.
- A recent audit trail panel so proposal, approval, paper execution, and Futu refresh events are visible without leaving the browser.

## Run Commands

```bash
cd /Users/apple/Documents/AIinvestmentAgent
source .venv/bin/activate
python -m invest_agent.cli seed
python -m invest_agent.api
```

Open:

```text
http://127.0.0.1:8788
```

## Verification

Latest verification completed:

```bash
.venv/bin/python -m pytest
```

Result:

```text
27 passed
```

HTTP checks were also verified:

- `GET /health`
- `GET /api/news`
- `POST /api/news/refresh`
- `POST /api/primary-sources/refresh`
- `GET /api/fundamentals`
- `POST /api/fundamentals/refresh`
- `POST /api/events/export`
- `POST /api/events/replay`
- `POST /api/proposal-drafts`
- `GET /api/watchlist`
- `GET /api/proposals`
- `GET /api/quotes`
- `GET /api/audit`
- `GET /api/futu/status`
- `POST /api/futu/refresh`
- `python -m invest_agent.cli futu-refresh`
- `python -m invest_agent.cli news-refresh`
- `python -m invest_agent.cli primary-refresh`
- `python -m invest_agent.cli fundamentals-refresh`
- `python -m invest_agent.cli event-export`
- `python -m invest_agent.cli event-replay`
- `python -m invest_agent.cli draft-proposals`

The dashboard was visually checked in the Codex in-app browser.

Futu OpenD read-only refresh was validated against the local OpenD on port `11111`; it refreshed 7 positions and 7 quote snapshots.

SEC companyfacts live smoke was validated against the configured watchlist. It refreshed 5 company snapshots; `US.VOO` was skipped because SEC companyfacts has no company CIK for the ETF.

## Not Tracked In Git

The following are local runtime artifacts and intentionally ignored:

- `.env`
- `.venv/`
- `data/*.db`
- `artifacts/`
- `.pytest_cache/`
- `*.egg-info/`

## Next Steps

- Decide whether Telegram approval should be handled directly by Hermes Gateway or a dedicated approval bot.
- Add valuation ratios and filing-period normalization on top of SEC companyfacts.
- Keep live execution disabled until Keychain secret loading, two-OpenD separation, broker-side revalidation, order/deal reconciliation, and a small live smoke-test plan are implemented.
