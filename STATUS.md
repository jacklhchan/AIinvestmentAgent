# AI Investment Agent Status

Last updated: 2026-05-26

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
- Research Goal / Evidence Ledger layer with research-only goals, claims, criteria, evidence rows, verification status, caveats, and evidence gate summaries.
- Thesis Tracker layer with long-term symbol theses, pillars, invalidating risks, evidence-linked thesis updates, and proposal-time thesis invariants.
- Catalyst Calendar layer with upcoming/completed events, source/human verification, post-event reviews, and proposal-time catalyst invariants.
- Earnings Review layer with SEC companyfacts-based YoY scoring, cashflow quality, research evidence, catalyst reviews, and thesis-delta artifacts.
- Event replay export/import for portfolio, quotes, news/evidence, and fundamental snapshot JSONL.
- Proposal draft engine that turns recent symbol-specific watchlist news into structured draft proposals, records a research goal for each draft, and only creates policy-checked proposals when evidence gate passes.
- Safe autonomy loop that refreshes read-only data, drafts watchlist proposals, applies evidence gate and proposal cooldown, and creates only paper-mode pending proposals for human approval.
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
  - `list_research_goals`
  - `create_research_goal`
  - `add_research_evidence`
  - `get_research_goal_snapshot`
  - `create_thesis`
  - `list_theses`
  - `get_thesis_snapshot`
  - `add_thesis_update_from_research_goal`
  - `list_catalysts`
  - `create_catalyst`
  - `get_catalyst_snapshot`
  - `complete_catalyst_with_research_goal`
  - `run_earnings_review`
  - `list_earnings_reviews`
  - `get_earnings_review`
  - `apply_earnings_review_to_thesis`
  - `get_safe_autonomy_status`
  - `run_safe_autonomy_cycle`
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
- launchd example plists at `deploy/launchd/com.local.invest-agent-api.plist` and `deploy/launchd/com.local.invest-agent-scheduler.plist`.
- Tests for proposal creation, approval, risk rejection, duplicate proposal blocking, non-pending state handling, Futu adapter mapping, dashboard localization, news parsing, watchlist resolution, SEC/IR parsing, event replay, proposal draft creation, research evidence gates, thesis tracker behavior, catalyst calendar invariants, and earnings review behavior.

## Local Hermes/Codex Setup

Hermes Agent v0.14.0 was installed under `/Users/apple/.hermes/hermes-agent`.

The global Hermes config at `/Users/apple/.hermes/config.yaml` has been updated locally to use:

- Provider: `openai-codex`
- Model: `gpt-5.2-codex`
- Reasoning effort: `high`
- MCP server: `invest_agent`

`hermes auth status openai-codex` shows logged in.

`hermes mcp list` shows `invest_agent` enabled with 35 selected tools after adding the 4 earnings review tools.

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

## Research Goal / Evidence Ledger

The app has started the next research-quality phase inspired by Anthropic-style thesis discipline and Vibe-style research goal ledgers, implemented locally without copying external code.

- SQLite now has `research_goals` and `research_evidence` tables.
- `ResearchGoalService` creates research-only goals and rejects objectives that ask for broker execution, trade unlock, direct order placement, or approval.
- Each proposal draft now creates a research goal with a directional claim, acceptance criteria, and evidence rows.
- Evidence rows track source type, source URI, data date, retrieved time, freshness, verification status, source-verified provenance, confidence, caveat, and contradicting claim IDs.
- The evidence gate requires both recent directional market/news evidence and source-verified primary-source or SEC companyfacts evidence before `create_proposals=true` can create a `PENDING` proposal.
- The gate is now enforced at `InvestmentService.create_proposal`, so REST, MCP, dashboard, CLI, autonomy, and draft creation all share the same invariant.
- Every `PENDING` proposal must have either a passed `research_goal_id` or an explicit `manual_override_reason`.
- MCP-created evidence rows are always unverified; remote agent text cannot mark itself source-verified.
- Verified evidence must match the research goal symbol, must be fresh under `INVEST_AGENT_RESEARCH_GATE_MAX_VERIFIED_AGE_DAYS`, and contradictory evidence blocks the gate as mixed.
- Created proposals store `research_goal_id` / `manual_override_reason` plus `evidence_hash` for later audit.
- If the gate fails, the draft remains research output and the skip reason is recorded; no pending proposal is created.
- Safe autonomy now checks this same gate before cooldown / proposal creation.
- REST endpoints:
  - `GET /api/research-goals`
  - `POST /api/research-goals`
  - `GET /api/research-goals/{goal_id}`
  - `POST /api/research-goals/{goal_id}/evidence`
- Hermes MCP research tools:
  - `list_research_goals`
  - `create_research_goal`
  - `add_research_evidence`
  - `get_research_goal_snapshot`
- Dashboard has a `研究目標與證據帳本` panel showing goal status, gate summary, evidence count, claims, and criteria.

This phase still does not unlock Futu OpenD and does not place live orders.

## Thesis Tracker

The app now adds the Anthropic-style thesis discipline as a first-class local data model, without giving Hermes or any external workflow approval or execution authority.

- SQLite now has `theses`, `thesis_pillars`, `thesis_risks`, and `thesis_updates` tables.
- A thesis stores symbol, side, thesis statement, status, conviction, target price, stop-loss / invalidation trigger, pillars, risks, and evidence-linked updates.
- Thesis provenance now stores `created_via`, `created_by`, `human_confirmed`, `confirmed_at`, and `confirmed_by`.
- MCP-created thesis rows default to `watch` / unconfirmed and are kept as research context until a human confirms them.
- Thesis updates can link to a research goal; the update stores an evidence hash that includes the goal evidence and thesis ID.
- `InvestmentService.create_proposal` now preserves `thesis_id` and blocks pending proposals that point to an unconfirmed, invalidated / archived, neutral-watch thesis, triggered invalidation risk, or broken pillar.
- Proposal drafts automatically attach only human-confirmed active theses for the symbol, add a thesis-tracker evidence line, and reduce confidence / add counter-evidence when tracked risks or pillars are already impaired.
- REST endpoints:
  - `GET /api/theses`
  - `POST /api/theses`
  - `GET /api/theses/{thesis_id}`
  - `POST /api/theses/{thesis_id}/updates`
- Hermes MCP thesis tools:
  - `create_thesis`
  - `list_theses`
  - `get_thesis_snapshot`
  - `add_thesis_update_from_research_goal`
- CLI:
  - `python -m invest_agent.cli list-theses`
- Dashboard has a `投資論點` panel and `新增投資論點` form.

This phase still does not unlock Futu OpenD and does not place live orders.

## Catalyst Calendar

The app now adds a proposal-time event risk layer for earnings, investor days, product launches, regulatory decisions, conferences, macro events, and other high-impact events.

- SQLite now has `catalysts` and `catalyst_reviews` tables.
- A catalyst stores symbol, event type, title, description, event date, time hint, timezone, expected impact, source URI/type, verification status, source-verified flag, linked thesis/research goal, actual outcome summary, thesis delta, and provenance.
- MCP-created catalysts are unverified by default and never count as source-verified.
- Source-verified catalysts require an official source type such as SEC EDGAR, company IR, exchange calendar, or macro calendar.
- Dashboard-created catalysts are human-verified and remain local audit objects.
- `InvestmentService.create_proposal` now checks catalyst risk:
  - High-impact upcoming catalysts within 48 hours block new pending proposals unless a manual override is provided.
  - Medium-impact upcoming catalysts within 24 hours add policy warnings and a confidence haircut.
  - Recently completed high/medium-impact catalysts without post-event review block new pending proposals unless manually overridden.
- Portfolio-wide macro catalysts use `symbol = null` and `event_type = macro`; those high/medium-impact events now apply to every symbol proposal check.
- Catalyst completion can create a post-event research goal candidate.
- Catalyst review can write thesis delta and update a linked thesis.
- REST endpoints:
  - `GET /api/catalysts/upcoming`
  - `GET /api/catalysts`
  - `POST /api/catalysts`
  - `GET /api/catalysts/{catalyst_id}`
  - `POST /api/catalysts/{catalyst_id}/complete`
  - `POST /api/catalysts/{catalyst_id}/review`
- Hermes MCP catalyst tools:
  - `list_catalysts`
  - `create_catalyst`
  - `get_catalyst_snapshot`
  - `complete_catalyst_with_research_goal`
- CLI:
  - `python -m invest_agent.cli list-catalysts --days 14`
  - `python -m invest_agent.cli catalyst-preview --days 7`
- Dashboard has a `催化事件` panel and `新增催化事件` form.

This phase still does not unlock Futu OpenD and does not place live orders.

## Earnings Review

The app now adds a deterministic post-earnings review layer built on local SEC companyfacts snapshots.

- SQLite now has an `earnings_reviews` table.
- An earnings review stores symbol, period, catalyst/research/thesis links, revenue/net income/operating income/operating cash flow/diluted EPS YoY, cashflow quality, thesis delta, action bias, evidence hash, score, warnings, and source summary.
- `EarningsReviewService.run_review` reads the latest local SEC companyfacts snapshot, creates or reuses a research goal, writes source-verified `sec-companyfacts` evidence, computes a deterministic thesis delta, and stores the review artifact.
- If the review is linked to a completed earnings catalyst, it creates a `catalyst_review`, which satisfies the post-event review requirement and unblocks future proposals that otherwise passed research/policy checks.
- MCP-run earnings reviews are research-only artifacts. Severe deltas such as `invalidates`, `exit`, `trim`, or `block_new_proposal` require human confirmation before applying to a thesis.
- REST endpoints:
  - `GET /api/earnings-reviews`
  - `POST /api/earnings-reviews/run`
  - `GET /api/earnings-reviews/{review_id}`
  - `POST /api/earnings-reviews/{review_id}/apply-to-thesis`
- Hermes MCP earnings review tools:
  - `run_earnings_review`
  - `list_earnings_reviews`
  - `get_earnings_review`
  - `apply_earnings_review_to_thesis`
- CLI:
  - `python -m invest_agent.cli earnings-review --symbol AAPL`
  - `python -m invest_agent.cli list-earnings-reviews --symbol AAPL`
- Dashboard has a `財報檢討` panel and `執行財報檢討` form.

This phase still does not unlock Futu OpenD and does not place live orders.

## Safe Autonomy Loop

The app now has a safe autonomous scheduler.

- `python -m invest_agent.cli autonomy-loop` runs the continuous local loop.
- `python -m invest_agent.cli autonomy-once` runs one full cycle for smoke testing.
- `python -m invest_agent.cli autonomy-status` reports the latest completed cycle from audit events.
- `GET /api/autonomy/status` and `POST /api/autonomy/run` expose the same controls to the dashboard.
- Hermes MCP exposes `get_safe_autonomy_status` and `run_safe_autonomy_cycle`.
- The loop can refresh read-only Futu data, market news, SEC/IR filings, and SEC companyfacts.
- Proposal creation has a configurable cooldown, defaulting to 240 minutes per symbol/side, to avoid repeated pending proposals.
- Created proposals remain `PENDING` / paper-only until a human approves them.

This phase still does not unlock Futu OpenD and does not place live orders.

Local launchd status:

- `com.local.invest-agent-api` is installed under `/Users/apple/Library/LaunchAgents` and running.
- `com.local.invest-agent-scheduler` is installed under `/Users/apple/Library/LaunchAgents` and running.
- Scheduler cycle interval is currently 900 seconds.
- Latest launchd loop cycle completed successfully and created 0 new proposals because cooldown / existing proposal state applied.

## Dashboard UX

The dashboard is now localized in Traditional Chinese and includes:

- Source badges for `Demo`, `富途 OpenD`, and local data.
- Portfolio, quote, news, and audit refresh timestamps.
- Futu OpenD connection status for the configured host/port.
- Safe autonomy status and a manual `執行自治循環` action.
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
.venv/bin/python -m compileall -q src
/Users/apple/.hermes/hermes-agent/venv/bin/hermes mcp list
.venv/bin/python -m invest_agent.cli draft-proposals
curl -s -X POST http://127.0.0.1:8788/api/proposals ...
```

Result:

```text
59 passed
```

HTTP checks were also verified:

- `GET /health`
- `GET /api/news`
- `POST /api/news/refresh`
- `POST /api/primary-sources/refresh`
- `GET /api/fundamentals`
- `POST /api/fundamentals/refresh`
- `GET /api/research-goals`
- `POST /api/research-goals`
- `GET /api/research-goals/{goal_id}`
- `POST /api/research-goals/{goal_id}/evidence`
- `GET /api/theses`
- `POST /api/theses`
- `GET /api/theses/{thesis_id}`
- `POST /api/theses/{thesis_id}/updates`
- `GET /api/catalysts/upcoming`
- `GET /api/catalysts`
- `POST /api/catalysts`
- `GET /api/catalysts/{catalyst_id}`
- `POST /api/catalysts/{catalyst_id}/complete`
- `POST /api/catalysts/{catalyst_id}/review`
- `GET /api/earnings-reviews`
- `POST /api/earnings-reviews/run`
- `GET /api/earnings-reviews/{review_id}`
- `POST /api/earnings-reviews/{review_id}/apply-to-thesis`
- `GET /api/autonomy/status`
- `POST /api/autonomy/run`
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
- `python -m invest_agent.cli autonomy-once`
- `python -m invest_agent.cli autonomy-status`
- `python -m invest_agent.cli event-export`
- `python -m invest_agent.cli event-replay`
- `python -m invest_agent.cli draft-proposals`
- invariant tests for direct proposal creation, MCP-unverified evidence, symbol mismatch, stale primary-source evidence, contradictory evidence, proposal `evidence_hash`, active thesis draft attachment, invalidated/unconfirmed thesis proposal blocking, MCP-unverified catalysts, high-impact catalyst blocking, portfolio-wide macro catalyst blocking, medium-impact catalyst warnings, catalyst review thesis delta, and earnings review thesis delta

The dashboard was visually checked in the Codex in-app browser.

Latest dashboard screenshot after adding the research panel:

```text
artifacts/dashboard-research-invariant.png
```

Latest dashboard screenshot after adding Thesis Tracker:

```text
artifacts/dashboard-thesis-tracker.png
```

Latest dashboard screenshot after adding Earnings Review:

```text
artifacts/dashboard-earnings-review.png
```

Futu OpenD read-only refresh was validated against the local OpenD on port `11111`; it refreshed 7 positions and 7 quote snapshots.

SEC companyfacts live smoke was validated against the configured watchlist. It refreshed 5 company snapshots; `US.VOO` was skipped because SEC companyfacts has no company CIK for the ETF.

Safe autonomy smoke was validated locally. It runs without live trading, records audit events, and creates only paper-mode pending proposals when evidence gate and cooldown allow.

Research/evidence smoke was validated locally. `draft-proposals` created research goals for evidence-gated AAPL/MSFT drafts and did not create proposals because the command was run in draft-only mode.

Legacy local pending proposals created before this invariant were marked `RISK_REJECTED` with an audit event, because they lacked both `research_goal_id` and `manual_override_reason`.

Live API smoke confirmed a direct proposal without `research_goal_id` or `manual_override_reason` becomes `RISK_REJECTED`, and the current local store has 0 pending invariant violations.

## Not Tracked In Git

The following are local runtime artifacts and intentionally ignored:

- `.env`
- `.venv/`
- `data/*.db`
- `artifacts/`
- `.pytest_cache/`
- `*.egg-info/`

## Next Steps

- Keep proposal invariant locked: no `PENDING` proposal without `research_goal_id` or explicit `manual_override_reason`.
- Keep verified provenance locked: MCP/user-submitted text cannot become source-verified evidence.
- Add Run Card / Trust Layer artifact importer for catalyst reviews, earnings reviews, event replay, and later Vibe sidecar results.
- Add Trade Journal / Behavior Report: Futu CSV import, FIFO roundtrip, win rate, PnL ratio, drawdown, and overtrading checks.
- Add valuation ratios and filing-period normalization on top of SEC companyfacts.
- Keep live execution disabled until Keychain secret loading, two-OpenD separation, atomic approval, idempotency keys, broker-side revalidation, order/deal reconciliation, and a small live smoke-test plan are implemented.
