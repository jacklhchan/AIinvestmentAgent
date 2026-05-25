# AI Investment Agent Status

Last updated: 2026-05-25

## Current State

The local MVP is implemented in `/Users/apple/Documents/AIinvestmentAgent`.

This version is intentionally paper-only. It can create trade proposals, run policy checks, accept or reject approvals, record paper executions, and expose the same control plane to Hermes through MCP. It does not unlock Futu OpenD and does not place live broker orders.

## Implemented

- FastAPI control plane on `127.0.0.1:8788`.
- SQLite-backed local store for portfolio snapshot, quotes, news, proposals, executions, and audit events.
- Demo portfolio, quotes, and news seed data.
- Risk checks for max notional, cash availability, portfolio percentage, confidence floor, duplicate pending proposals, and approval-time price drift.
- Traditional Chinese browser dashboard for portfolio, pending proposals, create proposal, approve/reject, positions, news digest, source provenance, refresh timestamps, and recent audit events.
- Futu OpenD read-only refresh for account funds, positions, and position quote snapshots.
- Hermes stdio MCP server exposing:
  - `get_portfolio_snapshot`
  - `get_watchlist_quotes`
  - `get_news_digest`
  - `get_futu_connection_status`
  - `refresh_futu_readonly_snapshot`
  - `list_pending_proposals`
  - `create_trade_proposal`
  - `approve_trade_proposal`
  - `reject_trade_proposal`
- Hermes config snippet at `deploy/hermes/config.snippet.yaml`.
- launchd example plist at `deploy/launchd/com.local.invest-agent-api.plist`.
- Tests for proposal creation, approval, risk rejection, duplicate proposal blocking, non-pending state handling, Futu adapter mapping, and dashboard localization.

## Local Hermes/Codex Setup

Hermes Agent v0.14.0 was installed under `/Users/apple/.hermes/hermes-agent`.

The global Hermes config at `/Users/apple/.hermes/config.yaml` has been updated locally to use:

- Provider: `openai-codex`
- Model: `gpt-5.2-codex`
- Reasoning effort: `high`
- MCP server: `invest_agent`

`hermes auth status openai-codex` shows logged in.

`hermes mcp list` shows `invest_agent` enabled with 9 selected tools.

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
8 passed
```

HTTP checks were also verified:

- `GET /health`
- `GET /api/news`
- `GET /api/proposals`
- `GET /api/quotes`
- `GET /api/audit`
- `GET /api/futu/status`
- `POST /api/futu/refresh`
- `python -m invest_agent.cli futu-refresh`

The dashboard was visually checked in the Codex in-app browser.

Futu OpenD read-only refresh was validated against the local OpenD on port `11111`; it refreshed 7 positions and 7 quote snapshots.

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
- Add real market/news ingestion behind the current store abstraction.
- Keep live execution disabled until Keychain secret loading, two-OpenD separation, broker-side revalidation, order/deal reconciliation, and a small live smoke-test plan are implemented.
