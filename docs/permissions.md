# MCP Permission Matrix

This repo intentionally keeps Hermes as a research and interaction shell. The local control plane owns proposal state, approval state, paper execution records, policy checks, and audit history. All MCP tools are `execution_forbidden`: no MCP surface may unlock Futu OpenD, place broker orders, modify broker orders, or cancel live broker orders.

Permission classes:

- `read_only`: reads local state only.
- `research_write`: may write local research, data-cache, evidence, run-card, or artifact tables; must not create proposals or executions.
- `proposal_write`: may create or replay policy-checked paper proposal state through the existing control-plane path.
- `approval_write`: may change proposal approval/rejection state through the existing control-plane path; current execution output is paper-only.
- `execution_forbidden`: hard tag for every tool in this file; live broker execution remains unavailable.

| Tool | Permission | Execution Boundary |
|---|---|---|
| `add_research_evidence` | `research_write` | `execution_forbidden` |
| `add_thesis_update_from_research_goal` | `research_write` | `execution_forbidden` |
| `apply_earnings_review_to_thesis` | `research_write` | `execution_forbidden` |
| `approve_trade_proposal` | `approval_write` | `execution_forbidden` |
| `ask_advisor` | `research_write` | `execution_forbidden` |
| `confirm_advisor_profile_update` | `research_write` | `execution_forbidden` |
| `complete_catalyst_with_research_goal` | `research_write` | `execution_forbidden` |
| `create_catalyst` | `research_write` | `execution_forbidden` |
| `create_hypothesis_draft` | `research_write` | `execution_forbidden` |
| `create_idea_candidate_draft` | `research_write` | `execution_forbidden` |
| `create_research_goal` | `research_write` | `execution_forbidden` |
| `create_thesis` | `research_write` | `execution_forbidden` |
| `create_trade_proposal` | `proposal_write` | `execution_forbidden` |
| `draft_trade_proposals_from_watchlist` | `proposal_write` | `execution_forbidden` |
| `export_event_replay_file` | `research_write` | `execution_forbidden` |
| `get_advisor_brief` | `research_write` | `execution_forbidden` |
| `get_advisor_profile` | `read_only` | `execution_forbidden` |
| `get_backtest_import` | `read_only` | `execution_forbidden` |
| `get_behavior_report` | `read_only` | `execution_forbidden` |
| `get_catalyst_snapshot` | `read_only` | `execution_forbidden` |
| `get_committee_review` | `read_only` | `execution_forbidden` |
| `get_correlation_snapshot` | `read_only` | `execution_forbidden` |
| `get_data_import_summary` | `read_only` | `execution_forbidden` |
| `get_data_quality_report` | `read_only` | `execution_forbidden` |
| `get_dividend_review` | `read_only` | `execution_forbidden` |
| `get_earnings_preview` | `read_only` | `execution_forbidden` |
| `get_earnings_review` | `read_only` | `execution_forbidden` |
| `get_fundamental_snapshot` | `read_only` | `execution_forbidden` |
| `get_futu_connection_status` | `read_only` | `execution_forbidden` |
| `get_hypothesis` | `read_only` | `execution_forbidden` |
| `get_idea_candidate` | `read_only` | `execution_forbidden` |
| `get_latest_advisor_brief` | `read_only` | `execution_forbidden` |
| `get_latest_daily_brief` | `read_only` | `execution_forbidden` |
| `get_latest_paper_signals` | `read_only` | `execution_forbidden` |
| `get_market_context` | `read_only` | `execution_forbidden` |
| `get_market_regime` | `read_only` | `execution_forbidden` |
| `get_news_digest` | `read_only` | `execution_forbidden` |
| `get_options_snapshot` | `read_only` | `execution_forbidden` |
| `get_portfolio_risk_snapshot` | `read_only` | `execution_forbidden` |
| `get_portfolio_snapshot` | `read_only` | `execution_forbidden` |
| `get_quote_history_summary` | `read_only` | `execution_forbidden` |
| `get_rebalance_review` | `read_only` | `execution_forbidden` |
| `get_research_goal_snapshot` | `read_only` | `execution_forbidden` |
| `get_run_card` | `read_only` | `execution_forbidden` |
| `get_run_card_artifact` | `read_only` | `execution_forbidden` |
| `get_safe_autonomy_status` | `read_only` | `execution_forbidden` |
| `get_sector_snapshot` | `read_only` | `execution_forbidden` |
| `get_shadow_report` | `read_only` | `execution_forbidden` |
| `get_shadow_strategy` | `read_only` | `execution_forbidden` |
| `get_thesis_snapshot` | `read_only` | `execution_forbidden` |
| `get_watchlist_quotes` | `read_only` | `execution_forbidden` |
| `get_watchlist_symbols` | `read_only` | `execution_forbidden` |
| `invalidate_hypothesis` | `research_write` | `execution_forbidden` |
| `link_run_card_to_hypothesis` | `research_write` | `execution_forbidden` |
| `list_backtest_imports` | `read_only` | `execution_forbidden` |
| `list_behavior_reports` | `read_only` | `execution_forbidden` |
| `list_catalysts` | `read_only` | `execution_forbidden` |
| `list_committee_reviews` | `read_only` | `execution_forbidden` |
| `list_daily_briefs` | `read_only` | `execution_forbidden` |
| `list_data_imports` | `read_only` | `execution_forbidden` |
| `list_data_quality_reports` | `read_only` | `execution_forbidden` |
| `list_dividend_reviews` | `read_only` | `execution_forbidden` |
| `list_earnings_previews` | `read_only` | `execution_forbidden` |
| `list_earnings_reviews` | `read_only` | `execution_forbidden` |
| `list_futu_accounts` | `read_only` | `execution_forbidden` |
| `list_hypotheses` | `read_only` | `execution_forbidden` |
| `list_idea_candidates` | `read_only` | `execution_forbidden` |
| `list_options_snapshots` | `read_only` | `execution_forbidden` |
| `list_peer_groups` | `read_only` | `execution_forbidden` |
| `list_pending_proposals` | `read_only` | `execution_forbidden` |
| `list_quote_history` | `read_only` | `execution_forbidden` |
| `list_rebalance_reviews` | `read_only` | `execution_forbidden` |
| `list_research_goals` | `read_only` | `execution_forbidden` |
| `list_run_cards` | `read_only` | `execution_forbidden` |
| `list_shadow_events` | `read_only` | `execution_forbidden` |
| `list_shadow_reports` | `read_only` | `execution_forbidden` |
| `list_shadow_strategies` | `read_only` | `execution_forbidden` |
| `list_theses` | `read_only` | `execution_forbidden` |
| `list_trade_roundtrips` | `read_only` | `execution_forbidden` |
| `promote_signal_to_proposal` | `proposal_write` | `execution_forbidden` |
| `refresh_futu_readonly_snapshot` | `research_write` | `execution_forbidden` |
| `refresh_market_context_news` | `research_write` | `execution_forbidden` |
| `refresh_market_news` | `research_write` | `execution_forbidden` |
| `refresh_primary_source_filings` | `research_write` | `execution_forbidden` |
| `refresh_sec_company_facts` | `research_write` | `execution_forbidden` |
| `reject_paper_signal` | `research_write` | `execution_forbidden` |
| `reject_trade_proposal` | `approval_write` | `execution_forbidden` |
| `replay_event_file` | `proposal_write` | `execution_forbidden` |
| `run_committee_review` | `research_write` | `execution_forbidden` |
| `run_dividend_review` | `research_write` | `execution_forbidden` |
| `run_earnings_preview` | `research_write` | `execution_forbidden` |
| `run_earnings_review` | `research_write` | `execution_forbidden` |
| `run_hourly_advisor_pulse` | `research_write` | `execution_forbidden` |
| `run_paper_signal_engine` | `research_write` | `execution_forbidden` |
| `run_post_close_advisor_brief` | `research_write` | `execution_forbidden` |
| `run_pre_market_advisor_brief` | `research_write` | `execution_forbidden` |
| `run_safe_autonomy_cycle` | `proposal_write` | `execution_forbidden` |
| `suggest_advisor_profile_update` | `research_write` | `execution_forbidden` |

Next-phase research cockpit tools are intentionally limited to `read_only` or `research_write`. Promotion paths such as idea-to-research-goal and rebalance-candidate-to-research-goal create research goals only; they do not create `PENDING` proposals. Severe thesis changes from earnings review remain blocked without human confirmation.
