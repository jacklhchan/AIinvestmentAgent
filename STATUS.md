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
- Browser dashboard for portfolio, pending proposals, create proposal, approve/reject, positions, and news digest.
- Hermes stdio MCP server exposing:
  - `get_portfolio_snapshot`
  - `get_watchlist_quotes`
  - `get_news_digest`
  - `list_pending_proposals`
  - `create_trade_proposal`
  - `approve_trade_proposal`
  - `reject_trade_proposal`
- Hermes config snippet at `deploy/hermes/config.snippet.yaml`.
- launchd example plist at `deploy/launchd/com.local.invest-agent-api.plist`.
- Tests for proposal creation, approval, risk rejection, duplicate proposal blocking, and non-pending state handling.

## Local Hermes/Codex Setup

Hermes Agent v0.14.0 was installed under `/Users/apple/.hermes/hermes-agent`.

The global Hermes config at `/Users/apple/.hermes/config.yaml` has been updated locally to use:

- Provider: `openai-codex`
- Model: `gpt-5.2-codex`
- Reasoning effort: `high`
- MCP server: `invest_agent`

`hermes mcp list` shows `invest_agent` enabled with 7 selected tools.

Codex OAuth is still pending. Hermes currently reports `openai-codex: logged out`. Complete it with:

```bash
/Users/apple/.local/bin/hermes auth add openai-codex
```

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
4 passed
```

HTTP checks were also verified:

- `GET /health`
- `GET /api/news`
- `GET /api/proposals`

The dashboard was visually checked in the Codex in-app browser.

## Not Tracked In Git

The following are local runtime artifacts and intentionally ignored:

- `.env`
- `.venv/`
- `data/*.db`
- `artifacts/`
- `.pytest_cache/`
- `*.egg-info/`

## Next Steps

- Complete Hermes OpenAI Codex OAuth.
- Decide whether Telegram approval should be handled directly by Hermes Gateway or a dedicated approval bot.
- Add real market/news ingestion behind the current store abstraction.
- Add optional Futu read-only monitor adapter.
- Keep live execution disabled until Keychain secret loading, two-OpenD separation, broker-side revalidation, order/deal reconciliation, and a small live smoke-test plan are implemented.
