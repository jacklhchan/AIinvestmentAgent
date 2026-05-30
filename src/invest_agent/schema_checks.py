from __future__ import annotations

from typing import Any

from .store import Store


EXPECTED_SCHEMA: dict[str, set[str]] = {
    "accounting_snapshots": {"id", "as_of", "payload"},
    "accounting_tax_lots": {"id", "account_id", "symbol", "status", "opened_at", "payload"},
    "accounting_transactions": {"id", "account_id", "symbol", "transaction_type", "occurred_at", "row_hash", "payload"},
    "advisor_briefs": {"id", "brief_type", "market_session_date", "created_at", "payload"},
    "advisor_profile_updates": {"id", "status", "created_at", "payload"},
    "advisor_profiles": {"id", "version", "updated_at", "payload"},
    "advisor_pulses": {"id", "pulse_type", "severity", "created_at", "payload"},
    "advisor_questions": {
        "id",
        "user_question",
        "symbol",
        "original_symbol",
        "resolved_symbol",
        "symbol_resolution_status",
        "answer_summary",
        "recommendation_type",
        "created_at",
        "payload",
    },
    "advisor_recommendations": {
        "id",
        "source_type",
        "source_id",
        "symbol",
        "recommendation_type",
        "created_at",
        "payload",
    },
    "audit_events": {"id", "event_type", "entity_type", "entity_id", "created_at", "payload"},
    "behavior_reports": {"id", "period_start", "period_end", "created_at", "payload"},
    "catalyst_reviews": {"id", "catalyst_id", "research_goal_id", "thesis_delta", "created_at", "payload"},
    "catalysts": {"id", "symbol", "event_type", "status", "event_date", "expected_impact", "payload"},
    "committee_reviews": {"id", "created_at", "payload"},
    "correlation_snapshots": {"id", "created_at", "payload"},
    "daily_briefs": {"id", "date", "brief_type", "created_at", "payload"},
    "data_imports": {"id", "file_hash", "schema_name", "imported_at", "payload"},
    "data_quality_reports": {"id", "target_type", "created_at", "payload"},
    "data_schemas": {"id", "name", "version", "payload"},
    "dividend_reviews": {"id", "symbol", "created_at", "payload"},
    "earnings_previews": {"id", "symbol", "catalyst_id", "created_at", "payload"},
    "earnings_reviews": {"id", "symbol", "catalyst_id", "research_goal_id", "thesis_delta", "created_at", "payload"},
    "executions": {"id", "proposal_id", "status", "created_at", "payload"},
    "external_backtest_imports": {"id", "run_card_hash", "validation_status", "created_at", "payload"},
    "fundamentals": {"symbol", "payload", "updated_at"},
    "hypothesis_links": {"id", "hypothesis_id", "linked_type", "linked_id", "created_at", "payload"},
    "idea_candidates": {"id", "symbol", "status", "created_at", "payload"},
    "idea_screens": {"id", "created_at", "payload"},
    "investor_policy_statements": {"id", "version", "updated_at", "payload"},
    "investor_framework_profiles": {"framework_key", "enabled", "weight", "updated_at", "payload"},
    "investor_committee_runs": {"id", "signal_id", "symbol", "final_stance", "created_at", "payload"},
    "investor_committee_votes": {"id", "run_id", "signal_id", "framework_key", "stance", "created_at", "payload"},
    "paper_advice_runs": {"id", "signal_run_id", "readiness_score", "created_at", "payload"},
    "paper_advice_items": {"id", "run_id", "signal_id", "committee_run_id", "symbol", "final_status", "created_at", "payload"},
    "market_regime_snapshots": {"id", "created_at", "risk_appetite", "proposal_bias", "payload"},
    "news": {"id", "symbol", "payload", "published_at"},
    "options_snapshots": {"id", "symbol", "expiry", "created_at", "payload"},
    "opportunity_cards": {"id", "run_id", "rank", "recommendation_type", "created_at", "payload"},
    "opportunity_radar_runs": {"id", "run_type", "created_at", "payload"},
    "peer_groups": {"id", "name", "sector", "created_at", "payload"},
    "portfolio": {"id", "payload"},
    "portfolio_risk_snapshots": {"id", "as_of", "payload"},
    "portfolio_targets": {"id", "asset_class", "payload"},
    "price_bars": {
        "id",
        "import_id",
        "symbol",
        "ts",
        "source_provider",
        "source_feed",
        "adjusted",
        "retrieved_at",
        "quality_score",
        "license_note",
        "row_hash",
        "payload",
    },
    "provider_usage_ledger": {
        "provider",
        "endpoint",
        "symbol",
        "quota_window",
        "request_count",
        "reset_at",
        "updated_at",
        "payload",
    },
    "proposals": {"id", "status", "symbol", "side", "created_at", "expires_at", "payload"},
    "quote_history_imports": {"id", "symbol", "input_hash", "dataset_hash", "imported_at", "payload"},
    "quotes": {"symbol", "payload", "updated_at"},
    "rebalance_candidates": {"id", "review_id", "symbol", "status", "payload"},
    "rebalance_reviews": {"id", "as_of", "payload"},
    "research_evidence": {"id", "goal_id", "symbol", "source_type", "retrieved_at", "payload"},
    "research_goals": {"id", "symbol", "status", "created_at", "payload"},
    "research_hypotheses": {"id", "status", "updated_at", "payload"},
    "research_run_cards": {"id", "run_type", "status", "symbol", "started_at", "completed_at", "payload"},
    "sector_snapshots": {"id", "sector", "created_at", "payload"},
    "shadow_events": {"id", "shadow_report_id", "symbol", "event_type", "created_at", "payload"},
    "shadow_reports": {"id", "strategy_id", "behavior_report_id", "created_at", "payload"},
    "shadow_rules": {"id", "strategy_id", "rule_type", "created_at", "payload"},
    "shadow_strategies": {"id", "source_behavior_report_id", "status", "created_at", "updated_at", "payload"},
    "signal_runs": {"id", "source", "horizon", "created_at", "payload"},
    "signal_outcome_rows": {
        "signal_id",
        "side",
        "blocked_action",
        "window",
        "window_type",
        "entry_bar_ts",
        "target_bar_ts",
        "raw_return_pct",
        "directional_return_pct",
        "raw_excess_return_pct",
        "directional_excess_return_pct",
        "hit_direction",
        "evaluated_at",
        "max_drawdown_pct",
        "max_favorable_excursion_pct",
        "max_adverse_upside_pct",
        "max_favorable_downside_pct",
        "score",
        "readiness_score",
        "blocking_reasons",
        "payload",
    },
    "signals": {"id", "run_id", "symbol", "side", "status", "score", "created_at", "expires_at", "payload"},
    "symbol_classifications": {"symbol", "asset_class", "payload"},
    "theses": {"id", "symbol", "side", "status", "updated_at", "payload"},
    "thesis_pillars": {"id", "thesis_id", "status", "payload"},
    "thesis_risks": {"id", "thesis_id", "status", "payload"},
    "thesis_updates": {"id", "thesis_id", "research_goal_id", "impact", "created_at", "payload"},
    "trade_fills": {"id", "import_id", "symbol", "side", "traded_at", "raw_row_hash", "payload"},
    "trade_imports": {"id", "source", "file_hash", "imported_at", "payload"},
    "trade_roundtrips": {"id", "import_id", "symbol", "opened_at", "closed_at", "payload"},
}

PRESERVED_TABLES = (
    "proposals",
    "executions",
    "research_goals",
    "research_run_cards",
    "signal_runs",
    "signals",
    "signal_outcome_rows",
    "investor_committee_runs",
    "investor_committee_votes",
    "paper_advice_runs",
    "paper_advice_items",
)


def run_schema_check(store: Store) -> dict[str, Any]:
    before_counts = _row_counts(store, PRESERVED_TABLES)
    store.init()
    store.init()
    table_columns = _table_columns(store)
    actual_tables = set(table_columns)
    missing_tables = sorted(set(EXPECTED_SCHEMA) - actual_tables)
    missing_columns = {
        table: sorted(expected - table_columns.get(table, set()))
        for table, expected in sorted(EXPECTED_SCHEMA.items())
        if table in actual_tables and expected - table_columns.get(table, set())
    }
    after_counts = _row_counts(store, PRESERVED_TABLES)
    preserved = before_counts == after_counts
    return {
        "ok": not missing_tables and not missing_columns and preserved,
        "db_path": str(store.db_path),
        "table_count": len(actual_tables),
        "expected_table_count": len(EXPECTED_SCHEMA),
        "missing_tables": missing_tables,
        "missing_columns": missing_columns,
        "preserved_counts": {"before": before_counts, "after": after_counts, "unchanged": preserved},
    }


def _table_columns(store: Store) -> dict[str, set[str]]:
    with store.connect() as conn:
        tables = [
            row["name"]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'").fetchall()
        ]
        return {
            table: {column["name"] for column in conn.execute(f"PRAGMA table_info({table})").fetchall()}
            for table in tables
        }


def _row_counts(store: Store, tables: tuple[str, ...]) -> dict[str, int]:
    counts: dict[str, int] = {}
    with store.connect() as conn:
        existing = {
            row["name"]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'").fetchall()
        }
        for table in tables:
            counts[table] = int(conn.execute(f"SELECT COUNT(*) AS count FROM {table}").fetchone()["count"]) if table in existing else 0
    return counts
