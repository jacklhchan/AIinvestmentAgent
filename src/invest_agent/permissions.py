from __future__ import annotations

from typing import Literal


McpPermission = Literal["read_only", "research_write", "proposal_write", "approval_write"]

READ_ONLY_TOOLS = frozenset(
    {
        "get_backtest_import",
        "get_behavior_report",
        "get_catalyst_snapshot",
        "get_committee_review",
        "get_correlation_snapshot",
        "get_data_import_summary",
        "get_data_quality_report",
        "get_dividend_review",
        "get_earnings_preview",
        "get_earnings_review",
        "get_fundamental_snapshot",
        "get_futu_connection_status",
        "get_advice_readiness",
        "get_advisor_profile",
        "get_hypothesis",
        "get_idea_candidate",
        "get_latest_daily_brief",
        "get_latest_advisor_brief",
        "get_latest_paper_signals",
        "get_market_context",
        "get_market_regime",
        "get_options_snapshot",
        "get_portfolio_risk_snapshot",
        "get_portfolio_snapshot",
        "get_quote_history_summary",
        "get_rebalance_review",
        "get_research_goal_snapshot",
        "get_run_card",
        "get_run_card_artifact",
        "get_safe_autonomy_status",
        "get_sector_snapshot",
        "get_signal_outcome_summary",
        "get_latest_investor_committee",
        "get_shadow_report",
        "get_shadow_strategy",
        "get_thesis_snapshot",
        "get_watchlist_quotes",
        "get_watchlist_symbols",
        "get_news_digest",
        "list_backtest_imports",
        "list_behavior_reports",
        "list_catalysts",
        "list_committee_reviews",
        "list_daily_briefs",
        "list_data_imports",
        "list_data_quality_reports",
        "list_dividend_reviews",
        "list_earnings_previews",
        "list_earnings_reviews",
        "list_futu_accounts",
        "list_hypotheses",
        "list_idea_candidates",
        "list_options_snapshots",
        "list_peer_groups",
        "list_pending_proposals",
        "list_quote_history",
        "list_rebalance_reviews",
        "list_research_goals",
        "list_run_cards",
        "list_shadow_events",
        "list_shadow_reports",
        "list_shadow_strategies",
        "list_theses",
        "list_trade_roundtrips",
    }
)

RESEARCH_WRITE_TOOLS = frozenset(
    {
        "add_research_evidence",
        "add_thesis_update_from_research_goal",
        "apply_earnings_review_to_thesis",
        "ask_advisor",
        "confirm_advisor_profile_update",
        "complete_catalyst_with_research_goal",
        "create_catalyst",
        "create_hypothesis_draft",
        "create_idea_candidate_draft",
        "create_research_goal",
        "create_thesis",
        "evaluate_signal_outcomes",
        "export_event_replay_file",
        "get_advisor_brief",
        "invalidate_hypothesis",
        "link_run_card_to_hypothesis",
        "refresh_futu_readonly_snapshot",
        "refresh_market_context_news",
        "refresh_market_news",
        "refresh_primary_source_filings",
        "refresh_sec_company_facts",
        "reject_paper_signal",
        "run_committee_review",
        "run_dividend_review",
        "run_earnings_preview",
        "run_earnings_review",
        "run_hourly_advisor_pulse",
        "run_investor_framework_committee",
        "run_paper_signal_engine",
        "run_pre_market_advisor_brief",
        "run_post_close_advisor_brief",
        "suggest_advisor_profile_update",
    }
)

PROPOSAL_WRITE_TOOLS = frozenset(
    {
        "create_trade_proposal",
        "draft_trade_proposals_from_watchlist",
        "promote_signal_to_proposal",
        "replay_event_file",
        "run_safe_autonomy_cycle",
    }
)

APPROVAL_WRITE_TOOLS = frozenset({"approve_trade_proposal", "reject_trade_proposal"})

MCP_TOOL_PERMISSIONS: dict[str, McpPermission] = {
    **{tool: "read_only" for tool in READ_ONLY_TOOLS},
    **{tool: "research_write" for tool in RESEARCH_WRITE_TOOLS},
    **{tool: "proposal_write" for tool in PROPOSAL_WRITE_TOOLS},
    **{tool: "approval_write" for tool in APPROVAL_WRITE_TOOLS},
}

NEXT_PHASE_MCP_TOOLS = frozenset(
    {
        "apply_earnings_review_to_thesis",
        "create_hypothesis_draft",
        "create_idea_candidate_draft",
        "get_backtest_import",
        "get_committee_review",
        "get_advice_readiness",
        "get_correlation_snapshot",
        "get_data_import_summary",
        "get_data_quality_report",
        "get_dividend_review",
        "get_earnings_preview",
        "get_hypothesis",
        "get_idea_candidate",
        "get_latest_daily_brief",
        "get_signal_outcome_summary",
        "get_latest_investor_committee",
        "get_options_snapshot",
        "get_portfolio_risk_snapshot",
        "get_quote_history_summary",
        "get_rebalance_review",
        "get_sector_snapshot",
        "invalidate_hypothesis",
        "link_run_card_to_hypothesis",
        "get_latest_investor_committee",
        "list_backtest_imports",
        "list_committee_reviews",
        "list_daily_briefs",
        "list_data_imports",
        "list_data_quality_reports",
        "list_dividend_reviews",
        "list_earnings_previews",
        "list_hypotheses",
        "list_idea_candidates",
        "list_options_snapshots",
        "list_peer_groups",
        "list_quote_history",
        "list_rebalance_reviews",
        "list_run_cards",
        "evaluate_signal_outcomes",
        "run_investor_framework_committee",
        "run_committee_review",
        "run_dividend_review",
        "run_earnings_preview",
        "run_investor_framework_committee",
    }
)

FORBIDDEN_LIVE_EXECUTION_TOOL_NAMES = frozenset(
    {
        "cancel_order",
        "modify_order",
        "place_live_order",
        "place_order",
        "submit_order",
        "unlock_trade",
    }
)


def permission_for_tool(tool_name: str) -> McpPermission:
    return MCP_TOOL_PERMISSIONS[tool_name]


def can_write_proposals(tool_name: str) -> bool:
    return MCP_TOOL_PERMISSIONS.get(tool_name) in {"proposal_write", "approval_write"}
