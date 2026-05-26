# AI Investment Agent Status

Last updated: 2026-05-26

## Current State

The local MVP is implemented in `/Users/apple/Documents/AIinvestmentAgent`.

This version is intentionally paper-only. It can create trade proposals, run policy checks, accept or reject approvals, record paper executions, and expose the same control plane to Hermes through MCP. It does not unlock Futu OpenD and does not place live broker orders.

## Implemented

- FastAPI control plane on `127.0.0.1:8788`.
- AI Advisor Brief first-screen workflow that automatically summarizes portfolio, proposal, thesis, catalyst, earnings, behavior, shadow, and research-goal state into research-only advice.
- Market Context Lens with broad-market symbols for index, volatility, rates, gold, and oil context; it informs advice but does not create proposal candidates.
- Market Regime / Risk Budget Lens that deterministically turns broad-market quote/news context into risk appetite, growth/rates/volatility/inflation pressure, and proposal-bias background.
- Hypothesis Registry / Research Autopilot spine with hypothesis lifecycle, run-card/research/thesis/catalyst links, and MCP-created drafts kept unconfirmed.
- Portfolio Studio / Risk X-ray with allocation drift, concentration warnings, rebalance reviews, and candidates that can only promote to research goals.
- Earnings Preview layer for pre-event setup, key metrics, scenarios, what-to-watch lists, and optional implied-move context before post-event earnings review.
- Quote History layer with daily price bars and shadow-account diagnostic PnL coverage only when reliable bars exist.
- External Backtest Importer for JSON/Markdown run-card artifacts without executing external code or passing proposal gates.
- Data Bridge for safe local CSV imports, including symbol classification schema, with REST/CLI write paths and MCP read-only summaries.
- Daily Brief / Research Delivery artifacts for morning, close, and weekly blocked/action/watch/info summaries.
- Sector / Peer / Correlation Lens, Options Implied Move Lens, Dividend / Shareholder Yield Lens, Idea Inbox, Committee Review, Skill Validator, and Data Quality reports.
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
- Research Run Card layer with versioned rule metadata, input/output/dataset hashes, evidence links, and JSON/Markdown artifacts for earnings reviews, catalyst reviews, and event replay exports.
- Trade Journal / Behavior Report layer with Futu/generic CSV import, file-hash idempotency, FIFO roundtrip pairing, behavior diagnostics, and behavior-report run cards.
- Shadow Account / Counterfactual Report layer with deterministic draft rule extraction, human-confirmed strategy activation, journal-internal counterfactual events, and shadow-report run cards.
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
  - `get_advisor_brief`
  - `get_market_context`
  - `get_market_regime`
  - `refresh_market_context_news`
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
  - `list_run_cards`
  - `get_run_card`
  - `get_run_card_artifact`
  - `list_behavior_reports`
  - `get_behavior_report`
  - `list_trade_roundtrips`
  - `list_shadow_strategies`
  - `get_shadow_strategy`
  - `list_shadow_reports`
  - `get_shadow_report`
  - `list_shadow_events`
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
- Tests for proposal creation, approval, risk rejection, duplicate proposal blocking, non-pending state handling, Futu adapter mapping, dashboard localization, news parsing, watchlist resolution, market context/regime guardrails, SEC/IR parsing, event replay, proposal draft creation, research evidence gates, thesis tracker behavior, catalyst calendar invariants, earnings review/preview behavior, research run card artifacts, trade journal behavior analytics, quote-history-backed shadow diagnostics, hypothesis/portfolio/backtest/data-bridge/daily-brief/sector/options/dividend/idea/committee/skill-validator/data-quality layers, and AI Advisor Brief behavior.

## AI Advisor Brief

The dashboard now has an advisor-first entry point so daily use no longer requires selecting internal IDs or manually chaining thesis/catalyst/earnings/journal/shadow panels.

- `GET /api/advisor/brief` returns a no-side-effect research brief.
- `POST /api/advisor/brief` can run light analysis, currently by creating the latest behavior report when trade fills exist.
- Hermes MCP exposes `get_advisor_brief` so the conversational agent can answer from the same advisor-first summary instead of asking the user to select internal IDs.
- The brief ranks advice as `blocked`, `action`, `watch`, or `info`.
- Inputs include broad-market context, pending proposals, catalyst windows, completed catalysts missing review, earnings review thesis deltas, behavior diagnostics, latest shadow events, thesis coverage, and insufficient research goals.
- The workflow is research-only. It does not create trade proposals, approve proposals, unlock Futu OpenD, or place live broker orders.

## Market Context Lens

The app now separates broad-market context from trade proposal watchlists.

- Default symbols: `SPY,QQQ,IWM,DIA,VIXY,TLT,GLD,USO`.
- `GET /api/market-context` returns quote/news coverage and risk notes for market context symbols.
- `POST /api/market-context/refresh` refreshes broad-market news without creating proposals.
- `GET /api/market-regime` returns the current deterministic market regime without side effects.
- `POST /api/market-regime/refresh` persists a `market_regime_v1` run card and snapshot.
- Safe autonomy refreshes market-context news alongside watchlist news.
- Dashboard has a `市場全景` panel and `刷新市場全景` action.
- Dashboard has a `市場狀態 / 風險預算` panel with risk appetite, proposal bias, growth/rates pressure, and vol/inflation pressure.
- Dashboard includes panels for 研究假設, 組合風險 / 再平衡檢討, 財報預覽, Quote History / Shadow PnL, 外部回測匯入, 資料匯入, 每日簡報, 同業與相關性, 期權風險, 股息檢討, 想法收件箱, 投資委員會備忘, 技能 / 指令檢查, and 資料品質.
- Dashboard market summary now shows 24 latest news items instead of 8.
- Futu read-only refresh attempts quote snapshots for market-context symbols in addition to held positions.
- Hermes MCP exposes `get_market_context`, `get_market_regime`, and `refresh_market_context_news`.
- These symbols inform Advisor Brief but are not fed into proposal drafting unless explicitly added to `INVEST_AGENT_WATCHLIST`.
- Market-context quote snapshots are explicitly excluded from proposal draft watchlist resolution unless the symbol is held or explicitly configured in `INVEST_AGENT_WATCHLIST`.

## Local Hermes/Codex Setup

Hermes Agent v0.14.0 was installed under `/Users/apple/.hermes/hermes-agent`.

The global Hermes config at `/Users/apple/.hermes/config.yaml` has been updated locally to use:

- Provider: `openai-codex`
- Model: `gpt-5.2-codex`
- Reasoning effort: `high`
- MCP server: `invest_agent`

`hermes auth status openai-codex` shows logged in.

`/Users/apple/.hermes/hermes-agent/venv/bin/hermes mcp list` should now show `invest_agent` with 85 local MCP tools after adding the next-phase research cockpit tools. Re-run the Hermes list command after syncing config to verify the live selection.

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
- Earnings review scoring stores versioned rule metadata (`earnings_review_v1`), deterministic thresholds, SEC companyfacts snapshot lineage, and linked evidence/run-card hashes.
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

## Research Run Cards

The app now adds a local Trust Layer-style artifact spine for important research actions.

- SQLite now has a `research_run_cards` table.
- A run card stores run type, status, symbol, actor, trigger source, git commit, rule version, input/output/dataset/evidence hashes, linked research/thesis/catalyst/earnings/proposal IDs, metrics, warnings, assumptions, outputs, errors, and artifact metadata.
- `RunCardService` writes deterministic JSON and human-readable Markdown artifacts under `artifacts/run_cards/...`.
- Earnings reviews now always create a run card. The linked source-verified `sec-companyfacts` evidence row and `earnings_review` row both store `run_card_id`.
- Catalyst reviews created directly also create a run card. Catalyst reviews created by earnings review reuse the earnings review run card.
- Event replay export now creates an `event_replay` run card and records the JSONL export artifact hash.
- Hermes MCP exposes only read-only run card tools; it cannot create arbitrary run cards.
- REST endpoints:
  - `GET /api/run-cards`
  - `GET /api/run-cards/{run_card_id}`
  - `GET /api/run-cards/{run_card_id}/artifact?kind=json`
  - `GET /api/run-cards/{run_card_id}/artifact?kind=markdown`
- Hermes MCP run card tools:
  - `list_run_cards`
  - `get_run_card`
  - `get_run_card_artifact`
- CLI:
  - `python -m invest_agent.cli list-run-cards --run-type earnings_review --symbol AAPL`
  - `python -m invest_agent.cli show-run-card --run-card-id run_...`
  - `python -m invest_agent.cli show-run-card --run-card-id run_... --kind markdown`
- Dashboard has a `研究執行紀錄` panel showing recent run cards, status, linked IDs, evidence hash, input/output hash, warnings, and artifact kinds.

This phase still does not unlock Futu OpenD and does not place live orders.

## Trade Journal / Behavior Report

The app now adds a research-only trade behavior analytics layer inspired by Vibe-style journal analysis, implemented locally without giving Hermes file-import or execution authority.

- SQLite now has `trade_imports`, `trade_fills`, `trade_roundtrips`, and `behavior_reports` tables.
- Futu CSV and generic CSV imports normalize fills into symbol, side, qty, price, fees, currency, market, traded time, broker IDs, raw row hash, and raw JSON.
- Import is idempotent by CSV `file_hash`; importing the same file again returns the existing import and does not duplicate fills.
- `TradeJournalService.run_behavior_report` rebuilds FIFO closed roundtrips and computes total trades, total roundtrips, win rate, profit/loss ratio, average holding days, trade frequency per week, total realized PnL, max drawdown, top symbols, hourly distribution, and market distribution.
- Deterministic diagnostics v1 covers:
  - disposition effect: loser holding days vs winner holding days
  - overtrading: busy-day PnL vs quiet-day PnL
  - chasing momentum: buys after the trader's own same-symbol trade prices already ran up
  - anchoring: repeated trades clustered in a narrow same-symbol price band
- Trade journal imports create `trade_journal_import` run cards. Behavior reports create `behavior_report` run cards with normalized fill dataset hashes, roundtrip metrics, diagnostics, warnings, and report IDs.
- Behavior analytics is research-only. It does not create proposals, approve proposals, unlock Futu, or place live broker orders.
- REST endpoints:
  - `GET /api/trade-imports`
  - `POST /api/trade-journal/import`
  - `GET /api/trade-fills`
  - `GET /api/trade-roundtrips`
  - `GET /api/behavior-reports`
  - `POST /api/behavior-reports/run`
  - `GET /api/behavior-reports/{report_id}`
- Hermes MCP behavior tools are read-only:
  - `list_behavior_reports`
  - `get_behavior_report`
  - `list_trade_roundtrips`
- CLI:
  - `python -m invest_agent.cli import-trade-journal --source futu_csv --path ~/Downloads/futu_trades.csv`
  - `python -m invest_agent.cli behavior-report --period-start 2026-01-01 --period-end 2026-05-26`
  - `python -m invest_agent.cli list-behavior-reports --limit 5`
  - `python -m invest_agent.cli show-behavior-report --report-id beh_...`
  - `python -m invest_agent.cli list-trade-roundtrips --symbol AAPL`
- Dashboard has `交易行為` and `匯入交易日誌` panels showing report metrics, diagnostics, latest import, latest roundtrip, and run card IDs.

This phase still does not unlock Futu OpenD and does not place live orders.

## Shadow Account / Counterfactual Report

The app now adds a research-only shadow account layer on top of imported fills, FIFO roundtrips, and behavior reports. It studies whether historical trades followed the user's own observed discipline; it does not create proposals, approve proposals, unlock Futu, or place broker orders.

- SQLite now has `shadow_strategies`, `shadow_rules`, `shadow_reports`, `shadow_events`, `quote_history_imports`, and `price_bars` tables.
- `ShadowAccountService.extract_strategy` reads a behavior report plus local fills/roundtrips and creates deterministic draft rules such as median holding days, median winner/loser PnL %, median entry notional, same-symbol cooldown, thesis requirement, and high-impact catalyst guardrail.
- Extracted strategies default to `draft`, `human_confirmed=false`; they must be confirmed through CLI/REST/dashboard before a shadow report can run.
- Shadow report v1 can remain journal-internal, or use cached daily price bars when `use_quote_history=true` to estimate diagnostic counterfactual PnL for early/late exits.
- Missing quote history is explicit: `counterfactual_pnl` and `delta_pnl` remain `null` when a matching daily close is unavailable.
- Quote-history-backed diagnostics use daily close only. They do not model dividends, splits, FX, taxes, borrow, liquidity, or executable intraday prices.
- Shadow strategy extraction creates `shadow_strategy_extract` run cards; shadow reports create `shadow_report` run cards with strategy inputs, roundtrip dataset hash, event counts, warnings, and outputs.
- REST endpoints:
  - `POST /api/shadow-strategies/extract`
  - `GET /api/shadow-strategies`
  - `GET /api/shadow-strategies/{strategy_id}`
  - `POST /api/shadow-strategies/{strategy_id}/confirm`
  - `POST /api/shadow-reports/run`
  - `GET /api/shadow-reports`
  - `GET /api/shadow-reports/{report_id}`
  - `GET /api/shadow-events`
  - `POST /api/quote-history/refresh`
  - `GET /api/quote-history`
  - `GET /api/quote-history/{symbol}`
- Hermes MCP shadow tools are read-only:
  - `list_shadow_strategies`
  - `get_shadow_strategy`
  - `list_shadow_reports`
  - `get_shadow_report`
  - `list_quote_history`
  - `get_quote_history_summary`
  - `list_shadow_events`
- CLI:
  - `python -m invest_agent.cli extract-shadow-strategy --behavior-report-id beh_...`
  - `python -m invest_agent.cli confirm-shadow-strategy --strategy-id shadow_...`
  - `python -m invest_agent.cli run-shadow-report --strategy-id shadow_...`
  - `python -m invest_agent.cli list-shadow-strategies --limit 5`
  - `python -m invest_agent.cli list-shadow-reports --limit 5`
  - `python -m invest_agent.cli show-shadow-report --report-id shrep_...`
- Dashboard has `影子帳戶` and `反事實報告` panels showing draft/active strategies, extracted rules, shadow reports, rule-violation events, and run card linkage.

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
- Trade behavior panels for behavior diagnostics, latest trade import, latest FIFO roundtrip, and behavior report run card IDs.
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

Latest verification completed after the research cockpit stabilization pass:

```bash
.venv/bin/python -m pytest
.venv/bin/python -m compileall src/invest_agent
.venv/bin/python -m invest_agent.cli schema-check
git diff --check
curl -sS http://127.0.0.1:8788/health
rg -n "unlock_trade\(|place_order\(|modify_order\(" src tests
```

Result:

```text
122 passed
compileall passed
schema-check ok: all expected tables and columns present; preserved counts unchanged
git diff --check passed
/health paper_only: true
live-order call grep passed
next-phase no-proposal-side-effect tests passed
Playwright dashboard smoke passed after research cockpit merge
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
- `GET /api/run-cards`
- `GET /api/run-cards/{run_card_id}`
- `GET /api/run-cards/{run_card_id}/artifact?kind=markdown`
- `GET /api/trade-imports`
- `POST /api/trade-journal/import`
- `GET /api/trade-fills`
- `GET /api/trade-roundtrips`
- `GET /api/behavior-reports`
- `POST /api/behavior-reports/run`
- `GET /api/behavior-reports/{report_id}`
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
- `python -m invest_agent.cli import-trade-journal`
- `python -m invest_agent.cli behavior-report`
- `python -m invest_agent.cli list-behavior-reports`
- `python -m invest_agent.cli list-trade-roundtrips`
- `python -m invest_agent.cli extract-shadow-strategy`
- `python -m invest_agent.cli confirm-shadow-strategy`
- `python -m invest_agent.cli run-shadow-report`
- `python -m invest_agent.cli list-shadow-strategies`
- `python -m invest_agent.cli list-shadow-reports`
- `python -m invest_agent.cli draft-proposals`
- invariant tests for direct proposal creation, MCP-unverified evidence, symbol mismatch, stale primary-source evidence, contradictory evidence, proposal `evidence_hash`, active thesis draft attachment, invalidated/unconfirmed thesis proposal blocking, MCP-unverified catalysts, high-impact catalyst blocking, portfolio-wide macro catalyst blocking, medium-impact catalyst warnings, catalyst review thesis delta, earnings review thesis delta, run card artifact linkage/hash behavior, CSV import idempotency, FIFO roundtrip pairing, behavior diagnostics, read-only behavior MCP surface, draft shadow strategy gating, shadow rule violations, read-only shadow MCP surface, MCP permission matrix coverage, schema integrity, no proposal/execution side effects for next-phase layers, run-card coverage, and severe-action MCP confirmation guards

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

Latest dashboard screenshot after adding Research Run Cards:

```text
artifacts/dashboard-run-cards.png
```

Latest dashboard screenshot after adding Trade Journal / Behavior Report:

```text
artifacts/dashboard-behavior-report.png
```

Latest dashboard screenshot after adding Shadow Account / Counterfactual Report:

```text
artifacts/dashboard-shadow-account.png
```

Futu OpenD read-only refresh was validated against the local OpenD on port `11111`; it refreshed 7 positions and 7 quote snapshots.

SEC companyfacts live smoke was validated against the configured watchlist. It refreshed 5 company snapshots; `US.VOO` was skipped because SEC companyfacts has no company CIK for the ETF.

Safe autonomy smoke was validated locally. It runs without live trading, records audit events, and creates only paper-mode pending proposals when evidence gate and cooldown allow.

Research/evidence smoke was validated locally. `draft-proposals` created research goals for evidence-gated AAPL/MSFT drafts and did not create proposals because the command was run in draft-only mode.

Trade journal smoke was validated locally with a sample CSV import, FIFO behavior report generation, behavior report API reads, and behavior report run card reads. The sample import artifact remains under ignored `artifacts/`.

Shadow account smoke was validated locally with draft strategy extraction, human confirmation, shadow report generation, shadow event reads, and shadow run card reads. The sample import artifact remains under ignored `artifacts/`.

Legacy local pending proposals created before this invariant were marked `RISK_REJECTED` with an audit event, because they lacked both `research_goal_id` and `manual_override_reason`.

Live API smoke confirmed a direct proposal without `research_goal_id` or `manual_override_reason` becomes `RISK_REJECTED`, and the current local store has 0 pending invariant violations.

## Not Tracked In Git

The following are local runtime artifacts and intentionally ignored:

- `.env`
- `.venv/`
- `data/*.db`
- `artifacts/`
- `.pytest_cache/`
- `.playwright-cli/`
- `*.egg-info/`

## Next Steps

- Keep proposal invariant locked: no `PENDING` proposal without `research_goal_id` or explicit `manual_override_reason`.
- Keep verified provenance locked: MCP/user-submitted text cannot become source-verified evidence.
- Extend Run Card / Trust Layer artifacts to safe autonomy cycles, proposal draft batches, and later Vibe sidecar imports.
- Extend Shadow Account with optional quote-history-backed counterfactual PnL, while keeping it research-only.
- Add valuation ratios and filing-period normalization on top of SEC companyfacts.
- Keep live execution disabled until Keychain secret loading, two-OpenD separation, atomic approval, idempotency keys, broker-side revalidation, order/deal reconciliation, and a small live smoke-test plan are implemented.
