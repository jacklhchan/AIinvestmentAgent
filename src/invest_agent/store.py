from __future__ import annotations

import json
import sqlite3
from datetime import timezone
from pathlib import Path
from typing import Any

from .models import (
    AccountingSnapshot,
    AccountingTaxLot,
    AccountingTransaction,
    AccountingTransactionType,
    AuditEvent,
    AdvisorFullBrief,
    AdvisorProfile,
    AdvisorProfileUpdate,
    AdvisorProfileUpdateStatus,
    AdvisorPulse,
    AdvisorPulseSeverity,
    AdvisorQuestion,
    AdvisorRecommendation,
    AdvisorSeverity,
    BacktestImportRequest,
    BehaviorReport,
    Catalyst,
    CatalystReview,
    CatalystStatus,
    CommitteeReview,
    CorrelationSnapshot,
    DailyBrief,
    DataImport,
    DataQualityReport,
    DataQualityTargetType,
    DataSchema,
    DividendReview,
    EarningsReview,
    EarningsPreview,
    ExecutionRecord,
    ExternalBacktestImport,
    ExternalBacktestValidationStatus,
    FundamentalSnapshot,
    HypothesisLink,
    HypothesisLinkType,
    HypothesisStatus,
    IdeaCandidate,
    IdeaCandidateStatus,
    IdeaScreen,
    InvestorPolicyStatement,
    InvestorCommitteeRun,
    InvestorCommitteeVote,
    InvestorFrameworkProfile,
    MarketRegimeSnapshot,
    NewsItem,
    OptionsSnapshot,
    OpportunityCard,
    OpportunityRadarRun,
    OpportunityRecommendationType,
    PeerGroup,
    PaperAdviceItem,
    PaperAdviceRun,
    PortfolioSnapshot,
    PortfolioRiskSnapshot,
    PortfolioTarget,
    PriceBar,
    Proposal,
    ProposalStatus,
    QuoteHistoryImport,
    QuoteHistorySource,
    Quote,
    RebalanceCandidate,
    RebalanceCandidateStatus,
    RebalanceReview,
    ResearchEvidence,
    ResearchGoal,
    ResearchGoalStatus,
    ResearchHypothesis,
    ResearchRunCard,
    RunCardStatus,
    RunCardType,
    SectorSnapshot,
    ShadowEvent,
    ShadowReport,
    ShadowRule,
    ShadowStrategy,
    ShadowStrategyStatus,
    Signal,
    SignalOutcomeRow,
    SignalRun,
    SignalSide,
    SignalStatus,
    SymbolClassification,
    TaxLotStatus,
    Thesis,
    ThesisPillar,
    ThesisRisk,
    ThesisStatus,
    ThesisUpdate,
    TradeFill,
    TradeFillSide,
    TradeImport,
    TradeJournalSource,
    TradeRoundTrip,
    utc_now,
)


class Store:
    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.init()

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def init(self) -> None:
        schema_backup_path = self._backup_before_schema_change_if_needed(
            missing_any_of={
                "signal_runs",
                "signals",
                "signal_outcome_rows",
                "investor_framework_profiles",
                "investor_committee_runs",
                "investor_committee_votes",
                "paper_advice_runs",
                "paper_advice_items",
            },
            label="paper-advice-v1",
        )
        with self.connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS portfolio (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    payload TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS quotes (
                    symbol TEXT PRIMARY KEY,
                    payload TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS news (
                    id TEXT PRIMARY KEY,
                    symbol TEXT,
                    payload TEXT NOT NULL,
                    published_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS fundamentals (
                    symbol TEXT PRIMARY KEY,
                    payload TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS proposals (
                    id TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    side TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    payload TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS executions (
                    id TEXT PRIMARY KEY,
                    proposal_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    FOREIGN KEY (proposal_id) REFERENCES proposals(id)
                );

                CREATE TABLE IF NOT EXISTS audit_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_type TEXT NOT NULL,
                    entity_type TEXT NOT NULL,
                    entity_id TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    payload TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS research_goals (
                    id TEXT PRIMARY KEY,
                    symbol TEXT,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    payload TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS research_evidence (
                    id TEXT PRIMARY KEY,
                    goal_id TEXT NOT NULL,
                    symbol TEXT,
                    source_type TEXT NOT NULL,
                    retrieved_at TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    FOREIGN KEY (goal_id) REFERENCES research_goals(id)
                );

                CREATE TABLE IF NOT EXISTS theses (
                    id TEXT PRIMARY KEY,
                    symbol TEXT NOT NULL,
                    side TEXT NOT NULL,
                    status TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    payload TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS thesis_pillars (
                    id TEXT PRIMARY KEY,
                    thesis_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    FOREIGN KEY (thesis_id) REFERENCES theses(id)
                );

                CREATE TABLE IF NOT EXISTS thesis_risks (
                    id TEXT PRIMARY KEY,
                    thesis_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    FOREIGN KEY (thesis_id) REFERENCES theses(id)
                );

                CREATE TABLE IF NOT EXISTS thesis_updates (
                    id TEXT PRIMARY KEY,
                    thesis_id TEXT NOT NULL,
                    research_goal_id TEXT,
                    impact TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    FOREIGN KEY (thesis_id) REFERENCES theses(id),
                    FOREIGN KEY (research_goal_id) REFERENCES research_goals(id)
                );

                CREATE TABLE IF NOT EXISTS catalysts (
                    id TEXT PRIMARY KEY,
                    symbol TEXT,
                    event_type TEXT NOT NULL,
                    status TEXT NOT NULL,
                    event_date TEXT NOT NULL,
                    expected_impact TEXT NOT NULL,
                    payload TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS catalyst_reviews (
                    id TEXT PRIMARY KEY,
                    catalyst_id TEXT NOT NULL,
                    research_goal_id TEXT,
                    thesis_delta TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    FOREIGN KEY (catalyst_id) REFERENCES catalysts(id),
                    FOREIGN KEY (research_goal_id) REFERENCES research_goals(id)
                );

                CREATE TABLE IF NOT EXISTS earnings_reviews (
                    id TEXT PRIMARY KEY,
                    symbol TEXT NOT NULL,
                    catalyst_id TEXT,
                    research_goal_id TEXT,
                    thesis_delta TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    FOREIGN KEY (catalyst_id) REFERENCES catalysts(id),
                    FOREIGN KEY (research_goal_id) REFERENCES research_goals(id)
                );

                CREATE TABLE IF NOT EXISTS research_run_cards (
                    id TEXT PRIMARY KEY,
                    run_type TEXT NOT NULL,
                    status TEXT NOT NULL,
                    symbol TEXT,
                    started_at TEXT NOT NULL,
                    completed_at TEXT,
                    payload TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS market_regime_snapshots (
                    id TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL,
                    risk_appetite TEXT NOT NULL,
                    proposal_bias TEXT NOT NULL,
                    payload TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS research_hypotheses (
                    id TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    payload TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS hypothesis_links (
                    id TEXT PRIMARY KEY,
                    hypothesis_id TEXT NOT NULL,
                    linked_type TEXT NOT NULL,
                    linked_id TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    FOREIGN KEY (hypothesis_id) REFERENCES research_hypotheses(id)
                );

                CREATE TABLE IF NOT EXISTS portfolio_targets (
                    id TEXT PRIMARY KEY,
                    asset_class TEXT NOT NULL,
                    payload TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS accounting_transactions (
                    id TEXT PRIMARY KEY,
                    account_id TEXT NOT NULL,
                    symbol TEXT,
                    transaction_type TEXT NOT NULL,
                    occurred_at TEXT NOT NULL,
                    row_hash TEXT NOT NULL UNIQUE,
                    payload TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS accounting_tax_lots (
                    id TEXT PRIMARY KEY,
                    account_id TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    status TEXT NOT NULL,
                    opened_at TEXT NOT NULL,
                    payload TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS accounting_snapshots (
                    id TEXT PRIMARY KEY,
                    as_of TEXT NOT NULL,
                    payload TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS investor_policy_statements (
                    id TEXT PRIMARY KEY,
                    version INTEGER NOT NULL,
                    updated_at TEXT NOT NULL,
                    payload TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS symbol_classifications (
                    symbol TEXT PRIMARY KEY,
                    asset_class TEXT NOT NULL,
                    payload TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS portfolio_risk_snapshots (
                    id TEXT PRIMARY KEY,
                    as_of TEXT NOT NULL,
                    payload TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS rebalance_reviews (
                    id TEXT PRIMARY KEY,
                    as_of TEXT NOT NULL,
                    payload TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS rebalance_candidates (
                    id TEXT PRIMARY KEY,
                    review_id TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    status TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    FOREIGN KEY (review_id) REFERENCES rebalance_reviews(id)
                );

                CREATE TABLE IF NOT EXISTS earnings_previews (
                    id TEXT PRIMARY KEY,
                    symbol TEXT NOT NULL,
                    catalyst_id TEXT,
                    created_at TEXT NOT NULL,
                    payload TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS quote_history_imports (
                    id TEXT PRIMARY KEY,
                    symbol TEXT NOT NULL,
                    input_hash TEXT NOT NULL,
                    dataset_hash TEXT NOT NULL,
                    imported_at TEXT NOT NULL,
                    payload TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS price_bars (
                    id TEXT PRIMARY KEY,
                    import_id TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    ts TEXT NOT NULL,
                    row_hash TEXT NOT NULL UNIQUE,
                    payload TEXT NOT NULL,
                    FOREIGN KEY (import_id) REFERENCES quote_history_imports(id)
                );

                CREATE TABLE IF NOT EXISTS external_backtest_imports (
                    id TEXT PRIMARY KEY,
                    run_card_hash TEXT NOT NULL,
                    validation_status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    payload TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS data_schemas (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    version TEXT NOT NULL,
                    payload TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS data_imports (
                    id TEXT PRIMARY KEY,
                    file_hash TEXT NOT NULL,
                    schema_name TEXT NOT NULL,
                    imported_at TEXT NOT NULL,
                    payload TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS daily_briefs (
                    id TEXT PRIMARY KEY,
                    date TEXT NOT NULL,
                    brief_type TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    payload TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS peer_groups (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    sector TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    payload TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS correlation_snapshots (
                    id TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL,
                    payload TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS sector_snapshots (
                    id TEXT PRIMARY KEY,
                    sector TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    payload TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS options_snapshots (
                    id TEXT PRIMARY KEY,
                    symbol TEXT NOT NULL,
                    expiry TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    payload TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS dividend_reviews (
                    id TEXT PRIMARY KEY,
                    symbol TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    payload TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS idea_screens (
                    id TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL,
                    payload TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS idea_candidates (
                    id TEXT PRIMARY KEY,
                    symbol TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    payload TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS committee_reviews (
                    id TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL,
                    payload TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS data_quality_reports (
                    id TEXT PRIMARY KEY,
                    target_type TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    payload TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS trade_imports (
                    id TEXT PRIMARY KEY,
                    source TEXT NOT NULL,
                    file_hash TEXT NOT NULL UNIQUE,
                    imported_at TEXT NOT NULL,
                    payload TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS trade_fills (
                    id TEXT PRIMARY KEY,
                    import_id TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    side TEXT NOT NULL,
                    traded_at TEXT NOT NULL,
                    raw_row_hash TEXT NOT NULL UNIQUE,
                    payload TEXT NOT NULL,
                    FOREIGN KEY (import_id) REFERENCES trade_imports(id)
                );

                CREATE TABLE IF NOT EXISTS trade_roundtrips (
                    id TEXT PRIMARY KEY,
                    import_id TEXT,
                    symbol TEXT NOT NULL,
                    opened_at TEXT NOT NULL,
                    closed_at TEXT NOT NULL,
                    payload TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS behavior_reports (
                    id TEXT PRIMARY KEY,
                    period_start TEXT,
                    period_end TEXT,
                    created_at TEXT NOT NULL,
                    payload TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS shadow_strategies (
                    id TEXT PRIMARY KEY,
                    source_behavior_report_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    FOREIGN KEY (source_behavior_report_id) REFERENCES behavior_reports(id)
                );

                CREATE TABLE IF NOT EXISTS shadow_rules (
                    id TEXT PRIMARY KEY,
                    strategy_id TEXT NOT NULL,
                    rule_type TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    FOREIGN KEY (strategy_id) REFERENCES shadow_strategies(id)
                );

                CREATE TABLE IF NOT EXISTS shadow_reports (
                    id TEXT PRIMARY KEY,
                    strategy_id TEXT NOT NULL,
                    behavior_report_id TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    FOREIGN KEY (strategy_id) REFERENCES shadow_strategies(id),
                    FOREIGN KEY (behavior_report_id) REFERENCES behavior_reports(id)
                );

                CREATE TABLE IF NOT EXISTS shadow_events (
                    id TEXT PRIMARY KEY,
                    shadow_report_id TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    FOREIGN KEY (shadow_report_id) REFERENCES shadow_reports(id)
                );

                CREATE TABLE IF NOT EXISTS advisor_questions (
                    id TEXT PRIMARY KEY,
                    user_question TEXT NOT NULL,
                    symbol TEXT,
                    original_symbol TEXT,
                    resolved_symbol TEXT,
                    symbol_resolution_status TEXT,
                    answer_summary TEXT NOT NULL,
                    recommendation_type TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    payload TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS advisor_pulses (
                    id TEXT PRIMARY KEY,
                    pulse_type TEXT NOT NULL,
                    severity TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    payload TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS advisor_briefs (
                    id TEXT PRIMARY KEY,
                    brief_type TEXT NOT NULL,
                    market_session_date TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    payload TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS advisor_recommendations (
                    id TEXT PRIMARY KEY,
                    source_type TEXT NOT NULL,
                    source_id TEXT NOT NULL,
                    symbol TEXT,
                    recommendation_type TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    payload TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS advisor_profiles (
                    id TEXT PRIMARY KEY,
                    version INTEGER NOT NULL,
                    updated_at TEXT NOT NULL,
                    payload TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS advisor_profile_updates (
                    id TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    payload TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS opportunity_radar_runs (
                    id TEXT PRIMARY KEY,
                    run_type TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    payload TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS opportunity_cards (
                    id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL,
                    rank INTEGER NOT NULL,
                    recommendation_type TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    FOREIGN KEY (run_id) REFERENCES opportunity_radar_runs(id)
                );

                CREATE TABLE IF NOT EXISTS signal_runs (
                    id TEXT PRIMARY KEY,
                    source TEXT NOT NULL,
                    horizon TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    payload TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS signals (
                    id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    side TEXT NOT NULL,
                    status TEXT NOT NULL,
                    score INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    FOREIGN KEY (run_id) REFERENCES signal_runs(id)
                );

                CREATE TABLE IF NOT EXISTS signal_outcome_rows (
                    signal_id TEXT NOT NULL,
                    side TEXT NOT NULL,
                    blocked_action TEXT,
                    window TEXT NOT NULL,
                    window_type TEXT NOT NULL,
                    entry_bar_ts TEXT NOT NULL,
                    target_bar_ts TEXT NOT NULL,
                    raw_return_pct REAL NOT NULL,
                    directional_return_pct REAL NOT NULL,
                    raw_excess_return_pct REAL,
                    directional_excess_return_pct REAL,
                    hit_direction INTEGER NOT NULL,
                    evaluated_at TEXT NOT NULL,
                    max_drawdown_pct REAL,
                    max_favorable_excursion_pct REAL,
                    max_adverse_upside_pct REAL,
                    max_favorable_downside_pct REAL,
                    score INTEGER,
                    readiness_score REAL,
                    blocking_reasons TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    PRIMARY KEY (signal_id, window, window_type),
                    FOREIGN KEY (signal_id) REFERENCES signals(id)
                );

                CREATE TABLE IF NOT EXISTS investor_framework_profiles (
                    framework_key TEXT PRIMARY KEY,
                    enabled INTEGER NOT NULL,
                    weight REAL NOT NULL,
                    updated_at TEXT NOT NULL,
                    payload TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS investor_committee_runs (
                    id TEXT PRIMARY KEY,
                    signal_id TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    final_stance TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    FOREIGN KEY (signal_id) REFERENCES signals(id)
                );

                CREATE TABLE IF NOT EXISTS investor_committee_votes (
                    id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL,
                    signal_id TEXT NOT NULL,
                    framework_key TEXT NOT NULL,
                    stance TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    FOREIGN KEY (run_id) REFERENCES investor_committee_runs(id),
                    FOREIGN KEY (signal_id) REFERENCES signals(id)
                );

                CREATE TABLE IF NOT EXISTS paper_advice_runs (
                    id TEXT PRIMARY KEY,
                    signal_run_id TEXT,
                    readiness_score REAL,
                    created_at TEXT NOT NULL,
                    payload TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS paper_advice_items (
                    id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL,
                    signal_id TEXT,
                    committee_run_id TEXT,
                    symbol TEXT,
                    final_status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    FOREIGN KEY (run_id) REFERENCES paper_advice_runs(id),
                    FOREIGN KEY (signal_id) REFERENCES signals(id),
                    FOREIGN KEY (committee_run_id) REFERENCES investor_committee_runs(id)
                );
                """
            )
            self._ensure_column(conn, "shadow_rules", "created_at", "TEXT")
            self._ensure_column(conn, "advisor_questions", "original_symbol", "TEXT")
            self._ensure_column(conn, "advisor_questions", "resolved_symbol", "TEXT")
            self._ensure_column(conn, "advisor_questions", "symbol_resolution_status", "TEXT")
            if schema_backup_path:
                event = AuditEvent(
                    event_type="sqlite_backup_created",
                    entity_type="database",
                    entity_id=str(self.db_path),
                    payload={"backup_path": str(schema_backup_path), "label": "paper-advice-v1"},
                )
                conn.execute(
                    """
                    INSERT INTO audit_events(event_type, entity_type, entity_id, created_at, payload)
                    VALUES(?, ?, ?, ?, ?)
                    """,
                    (
                        event.event_type,
                        event.entity_type,
                        event.entity_id,
                        event.created_at.isoformat(),
                        json.dumps(event.payload, default=str),
                    ),
                )

    @staticmethod
    def _dump(model: Any) -> str:
        return model.model_dump_json()

    def _backup_before_schema_change_if_needed(self, *, missing_any_of: set[str], label: str) -> Path | None:
        if not self.db_path.exists() or self.db_path.stat().st_size == 0:
            return None
        try:
            with sqlite3.connect(self.db_path) as conn:
                tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
                if not (missing_any_of - tables):
                    return None
                timestamp = utc_now().astimezone(timezone.utc).strftime("%Y%m%d_%H%M%S")
                safe_label = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "-" for ch in label).strip("-") or "schema"
                backup_dir = self.db_path.parent / "backups"
                backup_dir.mkdir(parents=True, exist_ok=True)
                backup_path = backup_dir / f"{self.db_path.stem}-{timestamp}-{safe_label}{self.db_path.suffix or '.db'}"
                with sqlite3.connect(backup_path) as target:
                    conn.backup(target)
                return backup_path
        except sqlite3.DatabaseError as exc:
            raise RuntimeError(f"failed to create SQLite backup before schema change: {exc}") from exc

    @staticmethod
    def _ensure_column(conn: sqlite3.Connection, table: str, column: str, definition: str) -> None:
        columns = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
        if column not in columns:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

    def _insert_payload(
        self,
        table: str,
        columns: list[str],
        values: list[Any],
        model: Any,
        *,
        audit_event: str,
        entity_type: str,
        entity_id: str,
        audit_payload: dict[str, Any] | None = None,
        or_ignore: bool = False,
    ) -> None:
        names = [*columns, "payload"]
        placeholders = ", ".join("?" for _ in names)
        verb = "INSERT OR IGNORE" if or_ignore else "INSERT"
        with self.connect() as conn:
            conn.execute(
                f"{verb} INTO {table}({', '.join(names)}) VALUES({placeholders})",
                (*values, self._dump(model)),
            )
        self.audit(audit_event, entity_type, entity_id, audit_payload or {})

    def _update_payload(
        self,
        table: str,
        key_column: str,
        key_value: Any,
        columns: list[str],
        values: list[Any],
        model: Any,
    ) -> None:
        assignments = ", ".join([*(f"{column} = ?" for column in columns), "payload = ?"])
        with self.connect() as conn:
            conn.execute(
                f"UPDATE {table} SET {assignments} WHERE {key_column} = ?",
                (*values, self._dump(model), key_value),
            )

    def _get_payload(self, table: str, model_type: type[Any], key_column: str, key_value: Any) -> Any | None:
        with self.connect() as conn:
            row = conn.execute(f"SELECT payload FROM {table} WHERE {key_column} = ?", (key_value,)).fetchone()
        return model_type.model_validate_json(row["payload"]) if row else None

    def _list_payloads(
        self,
        table: str,
        model_type: type[Any],
        *,
        where: str = "",
        args: tuple[Any, ...] = (),
        order_by: str = "id DESC",
        limit: int = 50,
    ) -> list[Any]:
        prefix = f"WHERE {where}" if where else ""
        query = f"SELECT payload FROM {table} {prefix} ORDER BY {order_by} LIMIT ?"
        with self.connect() as conn:
            rows = conn.execute(query, (*args, limit)).fetchall()
        return [model_type.model_validate_json(row["payload"]) for row in rows]

    def upsert_portfolio(self, snapshot: PortfolioSnapshot) -> None:
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO portfolio(id, payload) VALUES(1, ?) "
                "ON CONFLICT(id) DO UPDATE SET payload=excluded.payload",
                (self._dump(snapshot),),
            )
        self.audit("portfolio_upserted", "portfolio", "1", {"source": snapshot.source})

    def get_portfolio(self) -> PortfolioSnapshot:
        with self.connect() as conn:
            row = conn.execute("SELECT payload FROM portfolio WHERE id = 1").fetchone()
        if not row:
            return PortfolioSnapshot()
        return PortfolioSnapshot.model_validate_json(row["payload"])

    def upsert_quote(self, quote: Quote) -> None:
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO quotes(symbol, payload, updated_at) VALUES(?, ?, ?) "
                "ON CONFLICT(symbol) DO UPDATE SET payload=excluded.payload, updated_at=excluded.updated_at",
                (quote.symbol, self._dump(quote), quote.updated_at.isoformat()),
            )

    def list_quotes(self) -> list[Quote]:
        with self.connect() as conn:
            rows = conn.execute("SELECT payload FROM quotes ORDER BY symbol").fetchall()
        return [Quote.model_validate_json(row["payload"]) for row in rows]

    def get_quote(self, symbol: str) -> Quote | None:
        with self.connect() as conn:
            row = conn.execute("SELECT payload FROM quotes WHERE symbol = ?", (symbol.upper(),)).fetchone()
        return Quote.model_validate_json(row["payload"]) if row else None

    def upsert_news(self, item: NewsItem) -> None:
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO news(id, symbol, payload, published_at) VALUES(?, ?, ?, ?) "
                "ON CONFLICT(id) DO UPDATE SET payload=excluded.payload, published_at=excluded.published_at",
                (item.id, item.symbol, self._dump(item), item.published_at.isoformat()),
            )

    def list_news(self, limit: int = 20, symbol: str | None = None) -> list[NewsItem]:
        if symbol:
            query = "SELECT payload FROM news WHERE symbol = ? OR symbol IS NULL ORDER BY published_at DESC LIMIT ?"
            args: tuple[Any, ...] = (symbol.upper(), limit)
        else:
            query = "SELECT payload FROM news ORDER BY published_at DESC LIMIT ?"
            args = (limit,)
        with self.connect() as conn:
            rows = conn.execute(query, args).fetchall()
        return [NewsItem.model_validate_json(row["payload"]) for row in rows]

    def upsert_fundamentals(self, snapshot: FundamentalSnapshot) -> None:
        symbol = snapshot.symbol.upper()
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO fundamentals(symbol, payload, updated_at) VALUES(?, ?, ?) "
                "ON CONFLICT(symbol) DO UPDATE SET payload=excluded.payload, updated_at=excluded.updated_at",
                (symbol, self._dump(snapshot), snapshot.updated_at.isoformat()),
            )
        self.audit(
            "fundamentals_upserted",
            "fundamentals",
            symbol,
            {"source": snapshot.source, "metric_count": len(snapshot.metrics)},
        )

    def get_fundamentals(self, symbol: str) -> FundamentalSnapshot | None:
        with self.connect() as conn:
            row = conn.execute("SELECT payload FROM fundamentals WHERE symbol = ?", (symbol.upper(),)).fetchone()
        return FundamentalSnapshot.model_validate_json(row["payload"]) if row else None

    def list_fundamentals(self) -> list[FundamentalSnapshot]:
        with self.connect() as conn:
            rows = conn.execute("SELECT payload FROM fundamentals ORDER BY symbol").fetchall()
        return [FundamentalSnapshot.model_validate_json(row["payload"]) for row in rows]

    def create_research_goal(self, goal: ResearchGoal) -> ResearchGoal:
        goal.evidence = []
        goal.evidence_count = 0
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO research_goals(id, symbol, status, created_at, payload)
                VALUES(?, ?, ?, ?, ?)
                """,
                (
                    goal.id,
                    goal.symbol,
                    goal.status.value,
                    goal.created_at.isoformat(),
                    self._dump(goal),
                ),
            )
        self.audit(
            "research_goal_created",
            "research_goal",
            goal.id,
            {"symbol": goal.symbol, "status": goal.status.value, "risk_tier": goal.risk_tier},
        )
        return self.get_research_goal(goal.id) or goal

    def update_research_goal(self, goal: ResearchGoal, event_type: str = "research_goal_updated") -> ResearchGoal:
        stored_goal = goal.model_copy(update={"evidence": [], "evidence_count": 0})
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE research_goals
                SET symbol = ?, status = ?, payload = ?
                WHERE id = ?
                """,
                (stored_goal.symbol, stored_goal.status.value, self._dump(stored_goal), stored_goal.id),
            )
        self.audit(event_type, "research_goal", goal.id, {"symbol": goal.symbol, "status": goal.status.value})
        return self.get_research_goal(goal.id) or goal

    def get_research_goal(self, goal_id: str) -> ResearchGoal | None:
        with self.connect() as conn:
            row = conn.execute("SELECT payload FROM research_goals WHERE id = ?", (goal_id,)).fetchone()
        if not row:
            return None
        goal = ResearchGoal.model_validate_json(row["payload"])
        goal.evidence = self.list_research_evidence(goal_id)
        goal.evidence_count = len(goal.evidence)
        return goal

    def list_research_goals(
        self,
        status: ResearchGoalStatus | None = None,
        *,
        symbol: str | None = None,
        limit: int = 50,
    ) -> list[ResearchGoal]:
        clauses: list[str] = []
        args: list[Any] = []
        if status:
            clauses.append("status = ?")
            args.append(status.value)
        if symbol:
            clauses.append("symbol = ?")
            args.append(symbol.upper())
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        query = f"SELECT payload FROM research_goals {where} ORDER BY created_at DESC LIMIT ?"
        args.append(limit)
        with self.connect() as conn:
            rows = conn.execute(query, tuple(args)).fetchall()
        goals = [ResearchGoal.model_validate_json(row["payload"]) for row in rows]
        evidence_counts = self._research_evidence_counts([goal.id for goal in goals])
        for goal in goals:
            goal.evidence_count = evidence_counts.get(goal.id, 0)
        return goals

    def add_research_evidence(self, evidence: ResearchEvidence) -> ResearchEvidence:
        if not self.get_research_goal(evidence.goal_id):
            raise ValueError(f"research goal not found: {evidence.goal_id}")
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO research_evidence(id, goal_id, symbol, source_type, retrieved_at, payload)
                VALUES(?, ?, ?, ?, ?, ?)
                """,
                (
                    evidence.id,
                    evidence.goal_id,
                    evidence.symbol,
                    evidence.source_type,
                    evidence.retrieved_at.isoformat(),
                    self._dump(evidence),
                ),
            )
        self.audit(
            "research_evidence_added",
            "research_goal",
            evidence.goal_id,
            {
                "evidence_id": evidence.id,
                "symbol": evidence.symbol,
                "source_type": evidence.source_type,
                "verification_status": evidence.verification_status,
            },
        )
        return evidence

    def list_research_evidence(self, goal_id: str) -> list[ResearchEvidence]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT payload FROM research_evidence WHERE goal_id = ? ORDER BY retrieved_at DESC",
                (goal_id,),
            ).fetchall()
        return [ResearchEvidence.model_validate_json(row["payload"]) for row in rows]

    def _research_evidence_counts(self, goal_ids: list[str]) -> dict[str, int]:
        if not goal_ids:
            return {}
        placeholders = ",".join("?" for _ in goal_ids)
        with self.connect() as conn:
            rows = conn.execute(
                f"SELECT goal_id, COUNT(*) AS count FROM research_evidence WHERE goal_id IN ({placeholders}) GROUP BY goal_id",
                tuple(goal_ids),
            ).fetchall()
        return {row["goal_id"]: int(row["count"]) for row in rows}

    def create_run_card(self, run_card: ResearchRunCard) -> ResearchRunCard:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO research_run_cards(id, run_type, status, symbol, started_at, completed_at, payload)
                VALUES(?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_card.id,
                    run_card.run_type.value,
                    run_card.status.value,
                    run_card.symbol,
                    run_card.started_at.isoformat(),
                    run_card.completed_at.isoformat() if run_card.completed_at else None,
                    self._dump(run_card),
                ),
            )
        self.audit(
            "run_card_started",
            "run_card",
            run_card.id,
            {"run_type": run_card.run_type.value, "symbol": run_card.symbol, "status": run_card.status.value},
        )
        return run_card

    def update_run_card(self, run_card: ResearchRunCard, event_type: str = "run_card_updated") -> ResearchRunCard:
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE research_run_cards
                SET run_type = ?, status = ?, symbol = ?, started_at = ?, completed_at = ?, payload = ?
                WHERE id = ?
                """,
                (
                    run_card.run_type.value,
                    run_card.status.value,
                    run_card.symbol,
                    run_card.started_at.isoformat(),
                    run_card.completed_at.isoformat() if run_card.completed_at else None,
                    self._dump(run_card),
                    run_card.id,
                ),
            )
        self.audit(
            event_type,
            "run_card",
            run_card.id,
            {"run_type": run_card.run_type.value, "symbol": run_card.symbol, "status": run_card.status.value},
        )
        return self.get_run_card(run_card.id) or run_card

    def get_run_card(self, run_card_id: str) -> ResearchRunCard | None:
        with self.connect() as conn:
            row = conn.execute("SELECT payload FROM research_run_cards WHERE id = ?", (run_card_id,)).fetchone()
        return ResearchRunCard.model_validate_json(row["payload"]) if row else None

    def list_run_cards(
        self,
        *,
        run_type: RunCardType | None = None,
        status: RunCardStatus | None = None,
        symbol: str | None = None,
        limit: int = 50,
    ) -> list[ResearchRunCard]:
        clauses: list[str] = []
        args: list[Any] = []
        if run_type:
            clauses.append("run_type = ?")
            args.append(run_type.value)
        if status:
            clauses.append("status = ?")
            args.append(status.value)
        if symbol:
            clauses.append("symbol = ?")
            args.append(symbol.upper())
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        query = f"SELECT payload FROM research_run_cards {where} ORDER BY started_at DESC LIMIT ?"
        args.append(limit)
        with self.connect() as conn:
            rows = conn.execute(query, tuple(args)).fetchall()
        return [ResearchRunCard.model_validate_json(row["payload"]) for row in rows]

    def create_market_regime_snapshot(self, snapshot: MarketRegimeSnapshot) -> MarketRegimeSnapshot:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO market_regime_snapshots(id, created_at, risk_appetite, proposal_bias, payload)
                VALUES(?, ?, ?, ?, ?)
                """,
                (
                    snapshot.id,
                    snapshot.created_at.isoformat(),
                    snapshot.risk_appetite.value,
                    snapshot.proposal_bias.value,
                    self._dump(snapshot),
                ),
            )
        self.audit(
            "market_regime_snapshot_created",
            "market_regime",
            snapshot.id,
            {
                "risk_appetite": snapshot.risk_appetite.value,
                "proposal_bias": snapshot.proposal_bias.value,
                "run_card_id": snapshot.run_card_id,
            },
        )
        return snapshot

    def get_market_regime_snapshot(self, snapshot_id: str) -> MarketRegimeSnapshot | None:
        with self.connect() as conn:
            row = conn.execute("SELECT payload FROM market_regime_snapshots WHERE id = ?", (snapshot_id,)).fetchone()
        return MarketRegimeSnapshot.model_validate_json(row["payload"]) if row else None

    def list_market_regime_snapshots(self, *, limit: int = 20) -> list[MarketRegimeSnapshot]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT payload FROM market_regime_snapshots ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [MarketRegimeSnapshot.model_validate_json(row["payload"]) for row in rows]

    def get_latest_market_regime_snapshot(self) -> MarketRegimeSnapshot | None:
        snapshots = self.list_market_regime_snapshots(limit=1)
        return snapshots[0] if snapshots else None

    def create_hypothesis(self, item: ResearchHypothesis) -> ResearchHypothesis:
        stored = item.model_copy(update={"links": []})
        self._insert_payload(
            "research_hypotheses",
            ["id", "status", "updated_at"],
            [stored.id, stored.status.value, stored.updated_at.isoformat()],
            stored,
            audit_event="research_hypothesis_created",
            entity_type="research_hypothesis",
            entity_id=stored.id,
            audit_payload={"status": stored.status.value, "symbols": stored.symbols},
        )
        return self.get_hypothesis(stored.id) or item

    def update_hypothesis(self, item: ResearchHypothesis, event_type: str = "research_hypothesis_updated") -> ResearchHypothesis:
        stored = item.model_copy(update={"links": []})
        self._update_payload(
            "research_hypotheses",
            "id",
            stored.id,
            ["status", "updated_at"],
            [stored.status.value, stored.updated_at.isoformat()],
            stored,
        )
        self.audit(event_type, "research_hypothesis", stored.id, {"status": stored.status.value})
        return self.get_hypothesis(stored.id) or item

    def get_hypothesis(self, hypothesis_id: str) -> ResearchHypothesis | None:
        item = self._get_payload("research_hypotheses", ResearchHypothesis, "id", hypothesis_id)
        if item:
            item.links = self.list_hypothesis_links(hypothesis_id)
        return item

    def list_hypotheses(
        self,
        *,
        status: HypothesisStatus | None = None,
        symbol: str | None = None,
        limit: int = 50,
    ) -> list[ResearchHypothesis]:
        clauses: list[str] = []
        args: list[Any] = []
        if status:
            clauses.append("status = ?")
            args.append(status.value)
        items = self._list_payloads(
            "research_hypotheses",
            ResearchHypothesis,
            where=" AND ".join(clauses),
            args=tuple(args),
            order_by="updated_at DESC",
            limit=limit,
        )
        if symbol:
            ticker = symbol.upper()
            items = [item for item in items if ticker in item.symbols]
        for item in items:
            item.links = self.list_hypothesis_links(item.id)
        return items

    def add_hypothesis_link(self, item: HypothesisLink) -> HypothesisLink:
        if not self.get_hypothesis(item.hypothesis_id):
            raise ValueError(f"hypothesis not found: {item.hypothesis_id}")
        self._insert_payload(
            "hypothesis_links",
            ["id", "hypothesis_id", "linked_type", "linked_id", "created_at"],
            [item.id, item.hypothesis_id, item.linked_type.value, item.linked_id, item.created_at.isoformat()],
            item,
            audit_event="hypothesis_link_created",
            entity_type="research_hypothesis",
            entity_id=item.hypothesis_id,
            audit_payload={"linked_type": item.linked_type.value, "linked_id": item.linked_id},
        )
        return item

    def list_hypothesis_links(
        self,
        hypothesis_id: str | None = None,
        *,
        linked_type: HypothesisLinkType | None = None,
        limit: int = 100,
    ) -> list[HypothesisLink]:
        clauses: list[str] = []
        args: list[Any] = []
        if hypothesis_id:
            clauses.append("hypothesis_id = ?")
            args.append(hypothesis_id)
        if linked_type:
            clauses.append("linked_type = ?")
            args.append(linked_type.value)
        return self._list_payloads(
            "hypothesis_links",
            HypothesisLink,
            where=" AND ".join(clauses),
            args=tuple(args),
            order_by="created_at DESC",
            limit=limit,
        )

    def upsert_portfolio_target(self, item: PortfolioTarget) -> PortfolioTarget:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO portfolio_targets(id, asset_class, payload) VALUES(?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET asset_class=excluded.asset_class, payload=excluded.payload
                """,
                (item.id, item.asset_class, self._dump(item)),
            )
        self.audit("portfolio_target_upserted", "portfolio_target", item.id, {"asset_class": item.asset_class})
        return item

    def list_portfolio_targets(self, limit: int = 100) -> list[PortfolioTarget]:
        return self._list_payloads("portfolio_targets", PortfolioTarget, order_by="asset_class ASC", limit=limit)

    def add_accounting_transactions(self, items: list[AccountingTransaction]) -> list[AccountingTransaction]:
        inserted: list[AccountingTransaction] = []
        with self.connect() as conn:
            for item in items:
                cursor = conn.execute(
                    """
                    INSERT OR IGNORE INTO accounting_transactions(
                        id, account_id, symbol, transaction_type, occurred_at, row_hash, payload
                    )
                    VALUES(?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        item.id,
                        item.account_id,
                        item.symbol,
                        item.transaction_type.value,
                        item.occurred_at.isoformat(),
                        item.row_hash,
                        self._dump(item),
                    ),
                )
                if cursor.rowcount:
                    inserted.append(item)
        if items:
            self.audit(
                "accounting_transactions_imported",
                "accounting_transaction",
                "batch",
                {"submitted_count": len(items), "inserted_count": len(inserted)},
            )
        return inserted

    def create_accounting_transaction(self, item: AccountingTransaction) -> AccountingTransaction:
        inserted = self.add_accounting_transactions([item])
        if inserted:
            return inserted[0]
        existing = self.get_accounting_transaction_by_hash(item.row_hash)
        return existing or item

    def get_accounting_transaction_by_hash(self, row_hash: str) -> AccountingTransaction | None:
        return self._get_payload("accounting_transactions", AccountingTransaction, "row_hash", row_hash)

    def list_accounting_transactions(
        self,
        *,
        account_id: str | None = None,
        symbol: str | None = None,
        transaction_type: AccountingTransactionType | None = None,
        limit: int = 1000,
        ascending: bool = False,
    ) -> list[AccountingTransaction]:
        clauses: list[str] = []
        args: list[Any] = []
        if account_id:
            clauses.append("account_id = ?")
            args.append(account_id.upper())
        if symbol:
            clauses.append("symbol = ?")
            args.append(symbol.upper())
        if transaction_type:
            clauses.append("transaction_type = ?")
            args.append(transaction_type.value)
        order = "ASC" if ascending else "DESC"
        return self._list_payloads(
            "accounting_transactions",
            AccountingTransaction,
            where=" AND ".join(clauses),
            args=tuple(args),
            order_by=f"occurred_at {order}, id {order}",
            limit=limit,
        )

    def replace_accounting_tax_lots(self, items: list[AccountingTaxLot]) -> list[AccountingTaxLot]:
        with self.connect() as conn:
            conn.execute("DELETE FROM accounting_tax_lots")
            for item in items:
                conn.execute(
                    """
                    INSERT INTO accounting_tax_lots(id, account_id, symbol, status, opened_at, payload)
                    VALUES(?, ?, ?, ?, ?, ?)
                    """,
                    (
                        item.id,
                        item.account_id,
                        item.symbol,
                        item.status.value,
                        item.opened_at.isoformat(),
                        self._dump(item),
                    ),
                )
        self.audit("accounting_tax_lots_rebuilt", "accounting_tax_lot", "fifo", {"lot_count": len(items)})
        return items

    def list_accounting_tax_lots(
        self,
        *,
        account_id: str | None = None,
        symbol: str | None = None,
        status: TaxLotStatus | None = None,
        limit: int = 1000,
    ) -> list[AccountingTaxLot]:
        clauses: list[str] = []
        args: list[Any] = []
        if account_id:
            clauses.append("account_id = ?")
            args.append(account_id.upper())
        if symbol:
            clauses.append("symbol = ?")
            args.append(symbol.upper())
        if status:
            clauses.append("status = ?")
            args.append(status.value)
        return self._list_payloads(
            "accounting_tax_lots",
            AccountingTaxLot,
            where=" AND ".join(clauses),
            args=tuple(args),
            order_by="opened_at ASC, id ASC",
            limit=limit,
        )

    def create_accounting_snapshot(self, item: AccountingSnapshot) -> AccountingSnapshot:
        self._insert_payload(
            "accounting_snapshots",
            ["id", "as_of"],
            [item.id, item.as_of.isoformat()],
            item,
            audit_event="accounting_snapshot_created",
            entity_type="accounting_snapshot",
            entity_id=item.id,
            audit_payload={
                "transaction_count": item.transaction_count,
                "open_lot_count": item.open_lot_count,
                "run_card_id": item.run_card_id,
            },
        )
        return item

    def list_accounting_snapshots(self, *, limit: int = 20) -> list[AccountingSnapshot]:
        return self._list_payloads("accounting_snapshots", AccountingSnapshot, order_by="as_of DESC", limit=limit)

    def get_latest_accounting_snapshot(self) -> AccountingSnapshot | None:
        items = self.list_accounting_snapshots(limit=1)
        return items[0] if items else None

    def get_investor_policy_statement(self, policy_id: str = "default") -> InvestorPolicyStatement | None:
        return self._get_payload("investor_policy_statements", InvestorPolicyStatement, "id", policy_id)

    def upsert_investor_policy_statement(self, item: InvestorPolicyStatement) -> InvestorPolicyStatement:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO investor_policy_statements(id, version, updated_at, payload) VALUES(?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    version=excluded.version,
                    updated_at=excluded.updated_at,
                    payload=excluded.payload
                """,
                (item.id, item.version, item.updated_at.isoformat(), self._dump(item)),
            )
        self.audit(
            "investor_policy_statement_upserted",
            "investor_policy_statement",
            item.id,
            {"version": item.version, "source_profile_version": item.source_profile_version},
        )
        return item

    def upsert_symbol_classification(self, item: SymbolClassification) -> SymbolClassification:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO symbol_classifications(symbol, asset_class, payload) VALUES(?, ?, ?)
                ON CONFLICT(symbol) DO UPDATE SET asset_class=excluded.asset_class, payload=excluded.payload
                """,
                (item.symbol, item.asset_class, self._dump(item)),
            )
        self.audit("symbol_classification_upserted", "symbol_classification", item.symbol, {"asset_class": item.asset_class})
        return item

    def get_symbol_classification(self, symbol: str) -> SymbolClassification | None:
        return self._get_payload("symbol_classifications", SymbolClassification, "symbol", symbol.upper())

    def list_symbol_classifications(self, limit: int = 500) -> list[SymbolClassification]:
        return self._list_payloads("symbol_classifications", SymbolClassification, order_by="symbol ASC", limit=limit)

    def create_portfolio_risk_snapshot(self, item: PortfolioRiskSnapshot) -> PortfolioRiskSnapshot:
        self._insert_payload(
            "portfolio_risk_snapshots",
            ["id", "as_of"],
            [item.id, item.as_of.isoformat()],
            item,
            audit_event="portfolio_risk_snapshot_created",
            entity_type="portfolio_risk",
            entity_id=item.id,
            audit_payload={"run_card_id": item.run_card_id, "top_5_weight": item.top_5_weight},
        )
        return item

    def get_portfolio_risk_snapshot(self, snapshot_id: str) -> PortfolioRiskSnapshot | None:
        return self._get_payload("portfolio_risk_snapshots", PortfolioRiskSnapshot, "id", snapshot_id)

    def list_portfolio_risk_snapshots(self, limit: int = 20) -> list[PortfolioRiskSnapshot]:
        return self._list_payloads("portfolio_risk_snapshots", PortfolioRiskSnapshot, order_by="as_of DESC", limit=limit)

    def create_rebalance_review(self, review: RebalanceReview, candidates: list[RebalanceCandidate]) -> RebalanceReview:
        stored = review.model_copy(update={"candidates": []})
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO rebalance_reviews(id, as_of, payload) VALUES(?, ?, ?)",
                (stored.id, stored.as_of.isoformat(), self._dump(stored)),
            )
            for candidate in candidates:
                conn.execute(
                    "INSERT INTO rebalance_candidates(id, review_id, symbol, status, payload) VALUES(?, ?, ?, ?, ?)",
                    (candidate.id, candidate.review_id, candidate.symbol, candidate.status.value, self._dump(candidate)),
                )
        self.audit(
            "rebalance_review_created",
            "rebalance_review",
            review.id,
            {"candidate_count": len(candidates), "action_bias": review.action_bias.value},
        )
        return self.get_rebalance_review(review.id) or review

    def get_rebalance_review(self, review_id: str) -> RebalanceReview | None:
        item = self._get_payload("rebalance_reviews", RebalanceReview, "id", review_id)
        if item:
            item.candidates = self.list_rebalance_candidates(review_id=review_id)
        return item

    def list_rebalance_reviews(self, limit: int = 20) -> list[RebalanceReview]:
        items = self._list_payloads("rebalance_reviews", RebalanceReview, order_by="as_of DESC", limit=limit)
        for item in items:
            item.candidates = self.list_rebalance_candidates(review_id=item.id)
        return items

    def update_rebalance_candidate(self, item: RebalanceCandidate) -> RebalanceCandidate:
        self._update_payload(
            "rebalance_candidates",
            "id",
            item.id,
            ["review_id", "symbol", "status"],
            [item.review_id, item.symbol, item.status.value],
            item,
        )
        self.audit("rebalance_candidate_updated", "rebalance_candidate", item.id, {"status": item.status.value})
        return item

    def get_rebalance_candidate(self, candidate_id: str) -> RebalanceCandidate | None:
        return self._get_payload("rebalance_candidates", RebalanceCandidate, "id", candidate_id)

    def list_rebalance_candidates(
        self,
        *,
        review_id: str | None = None,
        status: RebalanceCandidateStatus | None = None,
        limit: int = 100,
    ) -> list[RebalanceCandidate]:
        clauses: list[str] = []
        args: list[Any] = []
        if review_id:
            clauses.append("review_id = ?")
            args.append(review_id)
        if status:
            clauses.append("status = ?")
            args.append(status.value)
        return self._list_payloads(
            "rebalance_candidates",
            RebalanceCandidate,
            where=" AND ".join(clauses),
            args=tuple(args),
            order_by="id ASC",
            limit=limit,
        )

    def create_earnings_preview(self, item: EarningsPreview) -> EarningsPreview:
        self._insert_payload(
            "earnings_previews",
            ["id", "symbol", "catalyst_id", "created_at"],
            [item.id, item.symbol, item.catalyst_id, item.created_at.isoformat()],
            item,
            audit_event="earnings_preview_created",
            entity_type="earnings_preview",
            entity_id=item.id,
            audit_payload={"symbol": item.symbol, "catalyst_id": item.catalyst_id},
        )
        return item

    def get_earnings_preview(self, preview_id: str) -> EarningsPreview | None:
        return self._get_payload("earnings_previews", EarningsPreview, "id", preview_id)

    def list_earnings_previews(self, *, symbol: str | None = None, catalyst_id: str | None = None, limit: int = 50) -> list[EarningsPreview]:
        clauses: list[str] = []
        args: list[Any] = []
        if symbol:
            clauses.append("symbol = ?")
            args.append(symbol.upper())
        if catalyst_id:
            clauses.append("catalyst_id = ?")
            args.append(catalyst_id)
        return self._list_payloads(
            "earnings_previews",
            EarningsPreview,
            where=" AND ".join(clauses),
            args=tuple(args),
            order_by="created_at DESC",
            limit=limit,
        )

    def create_quote_history_import(self, item: QuoteHistoryImport, bars: list[PriceBar]) -> QuoteHistoryImport:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO quote_history_imports(id, symbol, input_hash, dataset_hash, imported_at, payload)
                VALUES(?, ?, ?, ?, ?, ?)
                """,
                (item.id, item.symbol, item.input_hash, item.dataset_hash, item.imported_at.isoformat(), self._dump(item)),
            )
            for bar in bars:
                conn.execute(
                    """
                    INSERT OR IGNORE INTO price_bars(id, import_id, symbol, ts, row_hash, payload)
                    VALUES(?, ?, ?, ?, ?, ?)
                    """,
                    (bar.id, bar.import_id, bar.symbol, bar.ts.isoformat(), bar.row_hash, self._dump(bar)),
                )
        self.audit(
            "quote_history_import_created",
            "quote_history_import",
            item.id,
            {"symbol": item.symbol, "row_count": len(bars), "run_card_id": item.run_card_id},
        )
        return item

    def list_quote_history_imports(self, *, symbol: str | None = None, limit: int = 50) -> list[QuoteHistoryImport]:
        where = "symbol = ?" if symbol else ""
        args: tuple[Any, ...] = (symbol.upper(),) if symbol else ()
        return self._list_payloads(
            "quote_history_imports",
            QuoteHistoryImport,
            where=where,
            args=args,
            order_by="imported_at DESC",
            limit=limit,
        )

    def list_price_bars(
        self,
        *,
        symbol: str | None = None,
        start: str | None = None,
        end: str | None = None,
        limit: int = 1000,
        ascending: bool = True,
    ) -> list[PriceBar]:
        clauses: list[str] = []
        args: list[Any] = []
        if symbol:
            clauses.append("symbol = ?")
            args.append(symbol.upper())
        if start:
            clauses.append("ts >= ?")
            args.append(start)
        if end:
            clauses.append("ts <= ?")
            args.append(end)
        order = "ASC" if ascending else "DESC"
        return self._list_payloads(
            "price_bars",
            PriceBar,
            where=" AND ".join(clauses),
            args=tuple(args),
            order_by=f"ts {order}",
            limit=limit,
        )

    def create_external_backtest_import(self, item: ExternalBacktestImport) -> ExternalBacktestImport:
        self._insert_payload(
            "external_backtest_imports",
            ["id", "run_card_hash", "validation_status", "created_at"],
            [item.id, item.run_card_hash, item.validation_status.value, item.created_at.isoformat()],
            item,
            audit_event="external_backtest_import_created",
            entity_type="external_backtest_import",
            entity_id=item.id,
            audit_payload={"source": item.source.value, "strategy_name": item.strategy_name},
        )
        return item

    def get_external_backtest_import(self, import_id: str) -> ExternalBacktestImport | None:
        return self._get_payload("external_backtest_imports", ExternalBacktestImport, "id", import_id)

    def list_external_backtest_imports(
        self,
        *,
        validation_status: ExternalBacktestValidationStatus | None = None,
        limit: int = 50,
    ) -> list[ExternalBacktestImport]:
        where = "validation_status = ?" if validation_status else ""
        args: tuple[Any, ...] = (validation_status.value,) if validation_status else ()
        return self._list_payloads(
            "external_backtest_imports",
            ExternalBacktestImport,
            where=where,
            args=args,
            order_by="created_at DESC",
            limit=limit,
        )

    def upsert_data_schema(self, item: DataSchema) -> DataSchema:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO data_schemas(id, name, version, payload) VALUES(?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET name=excluded.name, version=excluded.version, payload=excluded.payload
                """,
                (item.id, item.name, item.version, self._dump(item)),
            )
        self.audit("data_schema_upserted", "data_schema", item.id, {"name": item.name, "version": item.version})
        return item

    def list_data_schemas(self, limit: int = 100) -> list[DataSchema]:
        return self._list_payloads("data_schemas", DataSchema, order_by="name ASC, version ASC", limit=limit)

    def create_data_import(self, item: DataImport) -> DataImport:
        self._insert_payload(
            "data_imports",
            ["id", "file_hash", "schema_name", "imported_at"],
            [item.id, item.file_hash, item.schema_name, item.imported_at.isoformat()],
            item,
            audit_event="data_import_created",
            entity_type="data_import",
            entity_id=item.id,
            audit_payload={"schema_name": item.schema_name, "row_count": item.row_count},
        )
        return item

    def get_data_import(self, import_id: str) -> DataImport | None:
        return self._get_payload("data_imports", DataImport, "id", import_id)

    def list_data_imports(self, *, schema_name: str | None = None, limit: int = 50) -> list[DataImport]:
        where = "schema_name = ?" if schema_name else ""
        args: tuple[Any, ...] = (schema_name,) if schema_name else ()
        return self._list_payloads("data_imports", DataImport, where=where, args=args, order_by="imported_at DESC", limit=limit)

    def create_daily_brief(self, item: DailyBrief) -> DailyBrief:
        self._insert_payload(
            "daily_briefs",
            ["id", "date", "brief_type", "created_at"],
            [item.id, item.date, item.brief_type.value, item.created_at.isoformat()],
            item,
            audit_event="daily_brief_created",
            entity_type="daily_brief",
            entity_id=item.id,
            audit_payload={"brief_type": item.brief_type.value, "run_card_id": item.run_card_id},
        )
        return item

    def get_daily_brief(self, brief_id: str) -> DailyBrief | None:
        return self._get_payload("daily_briefs", DailyBrief, "id", brief_id)

    def list_daily_briefs(self, limit: int = 50) -> list[DailyBrief]:
        return self._list_payloads("daily_briefs", DailyBrief, order_by="created_at DESC", limit=limit)

    def create_advisor_question(self, item: AdvisorQuestion) -> AdvisorQuestion:
        self._insert_payload(
            "advisor_questions",
            [
                "id",
                "user_question",
                "symbol",
                "original_symbol",
                "resolved_symbol",
                "symbol_resolution_status",
                "answer_summary",
                "recommendation_type",
                "created_at",
            ],
            [
                item.id,
                item.user_question,
                item.symbol,
                item.original_symbol,
                item.resolved_symbol,
                item.symbol_resolution_status.value,
                item.answer_summary,
                item.recommendation_type.value,
                item.created_at.isoformat(),
            ],
            item,
            audit_event="advisor_question_answered",
            entity_type="advisor_question",
            entity_id=item.id,
            audit_payload={
                "symbol": item.symbol,
                "original_symbol": item.original_symbol,
                "resolved_symbol": item.resolved_symbol,
                "symbol_resolution_status": item.symbol_resolution_status.value,
                "recommendation_type": item.recommendation_type.value,
                "run_card_id": item.run_card_id,
            },
        )
        return item

    def list_advisor_questions(self, *, symbol: str | None = None, limit: int = 50) -> list[AdvisorQuestion]:
        where = "symbol = ?" if symbol else ""
        args: tuple[Any, ...] = (symbol.upper(),) if symbol else ()
        return self._list_payloads(
            "advisor_questions",
            AdvisorQuestion,
            where=where,
            args=args,
            order_by="created_at DESC",
            limit=limit,
        )

    def create_advisor_recommendation(self, item: AdvisorRecommendation) -> AdvisorRecommendation:
        self._insert_payload(
            "advisor_recommendations",
            ["id", "source_type", "source_id", "symbol", "recommendation_type", "created_at"],
            [
                item.id,
                item.source_type.value,
                item.source_id,
                item.symbol,
                item.recommendation_type.value,
                item.created_at.isoformat(),
            ],
            item,
            audit_event="advisor_recommendation_created",
            entity_type="advisor_recommendation",
            entity_id=item.id,
            audit_payload={
                "source_type": item.source_type.value,
                "source_id": item.source_id,
                "symbol": item.symbol,
                "recommendation_type": item.recommendation_type.value,
            },
        )
        return item

    def list_advisor_recommendations(
        self,
        *,
        recommendation_type: AdvisorSeverity | None = None,
        symbol: str | None = None,
        limit: int = 50,
    ) -> list[AdvisorRecommendation]:
        clauses: list[str] = []
        args: list[Any] = []
        if recommendation_type:
            clauses.append("recommendation_type = ?")
            args.append(recommendation_type.value)
        if symbol:
            clauses.append("symbol = ?")
            args.append(symbol.upper())
        return self._list_payloads(
            "advisor_recommendations",
            AdvisorRecommendation,
            where=" AND ".join(clauses),
            args=tuple(args),
            order_by="created_at DESC",
            limit=limit,
        )

    def get_advisor_profile(self, profile_id: str = "default") -> AdvisorProfile | None:
        return self._get_payload("advisor_profiles", AdvisorProfile, "id", profile_id)

    def upsert_advisor_profile(self, item: AdvisorProfile) -> AdvisorProfile:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO advisor_profiles(id, version, updated_at, payload) VALUES(?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    version=excluded.version,
                    updated_at=excluded.updated_at,
                    payload=excluded.payload
                """,
                (item.id, item.version, item.updated_at.isoformat(), self._dump(item)),
            )
        self.audit(
            "advisor_profile_upserted",
            "advisor_profile",
            item.id,
            {"version": item.version, "source_update_id": item.source_update_id},
        )
        return item

    def create_advisor_profile_update(self, item: AdvisorProfileUpdate) -> AdvisorProfileUpdate:
        self._insert_payload(
            "advisor_profile_updates",
            ["id", "status", "created_at"],
            [item.id, item.status.value, item.created_at.isoformat()],
            item,
            audit_event="advisor_profile_update_suggested",
            entity_type="advisor_profile_update",
            entity_id=item.id,
            audit_payload={
                "status": item.status.value,
                "proposed_by": item.proposed_by,
                "source_question_id": item.source_question_id,
            },
        )
        return item

    def get_advisor_profile_update(self, update_id: str) -> AdvisorProfileUpdate | None:
        return self._get_payload("advisor_profile_updates", AdvisorProfileUpdate, "id", update_id)

    def update_advisor_profile_update(self, item: AdvisorProfileUpdate) -> AdvisorProfileUpdate:
        self._update_payload(
            "advisor_profile_updates",
            "id",
            item.id,
            ["status"],
            [item.status.value],
            item,
        )
        self.audit(
            "advisor_profile_update_changed",
            "advisor_profile_update",
            item.id,
            {
                "status": item.status.value,
                "confirmed_by": item.confirmed_by,
                "applied_profile_version": item.applied_profile_version,
            },
        )
        return item

    def list_advisor_profile_updates(
        self,
        *,
        status: AdvisorProfileUpdateStatus | None = None,
        limit: int = 20,
    ) -> list[AdvisorProfileUpdate]:
        where = "status = ?" if status else ""
        args: tuple[Any, ...] = (status.value,) if status else ()
        return self._list_payloads(
            "advisor_profile_updates",
            AdvisorProfileUpdate,
            where=where,
            args=args,
            order_by="created_at DESC",
            limit=limit,
        )

    def create_opportunity_radar_run(self, item: OpportunityRadarRun) -> OpportunityRadarRun:
        self._insert_payload(
            "opportunity_radar_runs",
            ["id", "run_type", "created_at"],
            [item.id, item.run_type, item.created_at.isoformat()],
            item,
            audit_event="opportunity_radar_run_created",
            entity_type="opportunity_radar_run",
            entity_id=item.id,
            audit_payload={
                "run_type": item.run_type,
                "run_card_id": item.run_card_id,
                "card_count": len(item.cards),
            },
        )
        for card in item.cards:
            self.create_opportunity_card(card)
        return item

    def get_opportunity_radar_run(self, run_id: str) -> OpportunityRadarRun | None:
        run = self._get_payload("opportunity_radar_runs", OpportunityRadarRun, "id", run_id)
        if not run:
            return None
        return run.model_copy(update={"cards": self.list_opportunity_cards(run_id=run.id, limit=100)})

    def list_opportunity_radar_runs(self, *, limit: int = 20) -> list[OpportunityRadarRun]:
        runs = self._list_payloads(
            "opportunity_radar_runs",
            OpportunityRadarRun,
            order_by="created_at DESC",
            limit=limit,
        )
        return [run.model_copy(update={"cards": self.list_opportunity_cards(run_id=run.id, limit=100)}) for run in runs]

    def create_opportunity_card(self, item: OpportunityCard) -> OpportunityCard:
        self._insert_payload(
            "opportunity_cards",
            ["id", "run_id", "rank", "recommendation_type", "created_at"],
            [item.id, item.run_id, item.rank, item.recommendation_type.value, item.created_at.isoformat()],
            item,
            audit_event="opportunity_card_created",
            entity_type="opportunity_card",
            entity_id=item.id,
            audit_payload={
                "run_id": item.run_id,
                "rank": item.rank,
                "recommendation_type": item.recommendation_type.value,
                "symbols": item.symbols,
            },
        )
        return item

    def list_opportunity_cards(
        self,
        *,
        run_id: str | None = None,
        recommendation_type: OpportunityRecommendationType | None = None,
        limit: int = 50,
    ) -> list[OpportunityCard]:
        clauses: list[str] = []
        args: list[Any] = []
        if run_id:
            clauses.append("run_id = ?")
            args.append(run_id)
        if recommendation_type:
            clauses.append("recommendation_type = ?")
            args.append(recommendation_type.value)
        return self._list_payloads(
            "opportunity_cards",
            OpportunityCard,
            where=" AND ".join(clauses),
            args=tuple(args),
            order_by="rank ASC, created_at DESC",
            limit=limit,
        )

    def create_signal_run(self, item: SignalRun) -> SignalRun:
        stored_run = item.model_copy(update={"signals": []})
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO signal_runs(id, source, horizon, created_at, payload)
                VALUES(?, ?, ?, ?, ?)
                """,
                (
                    stored_run.id,
                    stored_run.source.value,
                    stored_run.horizon.value,
                    stored_run.created_at.isoformat(),
                    self._dump(stored_run),
                ),
            )
            for signal in item.signals:
                conn.execute(
                    """
                    INSERT INTO signals(id, run_id, symbol, side, status, score, created_at, expires_at, payload)
                    VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        signal.id,
                        signal.run_id,
                        signal.symbol,
                        signal.side.value,
                        signal.status.value,
                        signal.score,
                        signal.created_at.isoformat(),
                        signal.expires_at.isoformat(),
                        self._dump(signal),
                    ),
                )
        self.audit(
            "signal_run_created",
            "signal_run",
            item.id,
            {
                "source": item.source.value,
                "horizon": item.horizon.value,
                "signal_count": len(item.signals),
                "run_card_id": item.run_card_id,
            },
        )
        return self.get_signal_run(item.id) or item

    def get_signal_run(self, run_id: str) -> SignalRun | None:
        run = self._get_payload("signal_runs", SignalRun, "id", run_id)
        if not run:
            return None
        return run.model_copy(update={"signals": self.list_signals(run_id=run.id, limit=200)})

    def list_signal_runs(self, *, limit: int = 20) -> list[SignalRun]:
        runs = self._list_payloads("signal_runs", SignalRun, order_by="created_at DESC", limit=limit)
        return [run.model_copy(update={"signals": self.list_signals(run_id=run.id, limit=200)}) for run in runs]

    def get_latest_signal_run(self) -> SignalRun | None:
        runs = self.list_signal_runs(limit=1)
        return runs[0] if runs else None

    def get_signal(self, signal_id: str) -> Signal | None:
        return self._get_payload("signals", Signal, "id", signal_id)

    def update_signal(self, item: Signal, event_type: str = "signal_updated") -> Signal:
        self._update_payload(
            "signals",
            "id",
            item.id,
            ["run_id", "symbol", "side", "status", "score", "created_at", "expires_at"],
            [
                item.run_id,
                item.symbol,
                item.side.value,
                item.status.value,
                item.score,
                item.created_at.isoformat(),
                item.expires_at.isoformat(),
            ],
            item,
        )
        self.audit(
            event_type,
            "signal",
            item.id,
            {"symbol": item.symbol, "side": item.side.value, "status": item.status.value, "proposal_id": item.proposal_id},
        )
        return item

    def upsert_signal_outcome_rows(self, rows: list[SignalOutcomeRow]) -> None:
        if not rows:
            return
        with self.connect() as conn:
            for row in rows:
                conn.execute(
                    """
                    INSERT INTO signal_outcome_rows(
                        signal_id, side, blocked_action, window, window_type, entry_bar_ts, target_bar_ts,
                        raw_return_pct, directional_return_pct, raw_excess_return_pct, directional_excess_return_pct,
                        hit_direction, evaluated_at, max_drawdown_pct, max_favorable_excursion_pct,
                        max_adverse_upside_pct, max_favorable_downside_pct, score, readiness_score,
                        blocking_reasons, payload
                    )
                    VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(signal_id, window, window_type) DO UPDATE SET
                        side=excluded.side,
                        blocked_action=excluded.blocked_action,
                        entry_bar_ts=excluded.entry_bar_ts,
                        target_bar_ts=excluded.target_bar_ts,
                        raw_return_pct=excluded.raw_return_pct,
                        directional_return_pct=excluded.directional_return_pct,
                        raw_excess_return_pct=excluded.raw_excess_return_pct,
                        directional_excess_return_pct=excluded.directional_excess_return_pct,
                        hit_direction=excluded.hit_direction,
                        evaluated_at=excluded.evaluated_at,
                        max_drawdown_pct=excluded.max_drawdown_pct,
                        max_favorable_excursion_pct=excluded.max_favorable_excursion_pct,
                        max_adverse_upside_pct=excluded.max_adverse_upside_pct,
                        max_favorable_downside_pct=excluded.max_favorable_downside_pct,
                        score=excluded.score,
                        readiness_score=excluded.readiness_score,
                        blocking_reasons=excluded.blocking_reasons,
                        payload=excluded.payload
                    """,
                    (
                        row.signal_id,
                        row.side.value,
                        row.blocked_action,
                        row.window,
                        row.window_type,
                        row.entry_bar_ts.isoformat(),
                        row.target_bar_ts.isoformat(),
                        row.raw_return_pct,
                        row.directional_return_pct,
                        row.raw_excess_return_pct,
                        row.directional_excess_return_pct,
                        1 if row.hit_direction else 0,
                        row.evaluated_at.isoformat(),
                        row.max_drawdown_pct,
                        row.max_favorable_excursion_pct,
                        row.max_adverse_upside_pct,
                        row.max_favorable_downside_pct,
                        row.score,
                        row.readiness_score,
                        json.dumps(row.blocking_reasons, default=str),
                        self._dump(row),
                    ),
                )

    def list_signal_outcome_rows(self, *, limit: int = 1000, signal_id: str | None = None) -> list[SignalOutcomeRow]:
        clauses: list[str] = []
        args: list[Any] = []
        if signal_id:
            clauses.append("signal_id = ?")
            args.append(signal_id)
        return self._list_payloads(
            "signal_outcome_rows",
            SignalOutcomeRow,
            where=" AND ".join(clauses),
            args=tuple(args),
            order_by="evaluated_at DESC",
            limit=limit,
        )

    def upsert_investor_framework_profile(self, item: InvestorFrameworkProfile) -> InvestorFrameworkProfile:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO investor_framework_profiles(framework_key, enabled, weight, updated_at, payload)
                VALUES(?, ?, ?, ?, ?)
                ON CONFLICT(framework_key) DO UPDATE SET
                    enabled=excluded.enabled,
                    weight=excluded.weight,
                    updated_at=excluded.updated_at,
                    payload=excluded.payload
                """,
                (item.framework_key, 1 if item.enabled else 0, item.weight, item.updated_at.isoformat(), self._dump(item)),
            )
        return item

    def list_investor_framework_profiles(self, *, enabled: bool | None = None) -> list[InvestorFrameworkProfile]:
        where = ""
        args: tuple[Any, ...] = ()
        if enabled is not None:
            where = "enabled = ?"
            args = (1 if enabled else 0,)
        return self._list_payloads(
            "investor_framework_profiles",
            InvestorFrameworkProfile,
            where=where,
            args=args,
            order_by="framework_key ASC",
            limit=100,
        )

    def create_investor_committee_run(self, item: InvestorCommitteeRun) -> InvestorCommitteeRun:
        run_without_votes = item.model_copy(update={"votes": []})
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO investor_committee_runs(id, signal_id, symbol, final_stance, created_at, payload)
                VALUES(?, ?, ?, ?, ?, ?)
                """,
                (
                    run_without_votes.id,
                    run_without_votes.signal_id,
                    run_without_votes.symbol,
                    run_without_votes.final_stance,
                    run_without_votes.created_at.isoformat(),
                    self._dump(run_without_votes),
                ),
            )
            for vote in item.votes:
                conn.execute(
                    """
                    INSERT INTO investor_committee_votes(id, run_id, signal_id, framework_key, stance, created_at, payload)
                    VALUES(?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        vote.id,
                        vote.run_id,
                        vote.signal_id,
                        vote.framework_key,
                        vote.stance.value,
                        vote.created_at.isoformat(),
                        self._dump(vote),
                    ),
                )
        self.audit(
            "investor_committee_run_created",
            "investor_committee_run",
            item.id,
            {
                "signal_id": item.signal_id,
                "symbol": item.symbol,
                "final_stance": item.final_stance,
                "committee_adjusted_score": item.committee_adjusted_score,
                "committee_blocked": item.committee_blocked,
            },
        )
        return self.get_investor_committee_run(item.id) or item

    def get_investor_committee_run(self, run_id: str) -> InvestorCommitteeRun | None:
        run = self._get_payload("investor_committee_runs", InvestorCommitteeRun, "id", run_id)
        if not run:
            return None
        return run.model_copy(update={"votes": self.list_investor_committee_votes(run_id=run.id)})

    def list_investor_committee_runs(
        self,
        *,
        signal_id: str | None = None,
        limit: int = 20,
    ) -> list[InvestorCommitteeRun]:
        where = "signal_id = ?" if signal_id else ""
        args: tuple[Any, ...] = (signal_id,) if signal_id else ()
        runs = self._list_payloads(
            "investor_committee_runs",
            InvestorCommitteeRun,
            where=where,
            args=args,
            order_by="created_at DESC",
            limit=limit,
        )
        return [run.model_copy(update={"votes": self.list_investor_committee_votes(run_id=run.id)}) for run in runs]

    def get_latest_investor_committee_run(self) -> InvestorCommitteeRun | None:
        runs = self.list_investor_committee_runs(limit=1)
        return runs[0] if runs else None

    def list_investor_committee_votes(self, *, run_id: str | None = None, limit: int = 100) -> list[InvestorCommitteeVote]:
        where = "run_id = ?" if run_id else ""
        args: tuple[Any, ...] = (run_id,) if run_id else ()
        return self._list_payloads(
            "investor_committee_votes",
            InvestorCommitteeVote,
            where=where,
            args=args,
            order_by="framework_key ASC",
            limit=limit,
        )

    def create_paper_advice_run(self, item: PaperAdviceRun) -> PaperAdviceRun:
        run_without_items = item.model_copy(update={"items": []})
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO paper_advice_runs(id, signal_run_id, readiness_score, created_at, payload)
                VALUES(?, ?, ?, ?, ?)
                """,
                (
                    run_without_items.id,
                    run_without_items.signal_run_id,
                    run_without_items.readiness_score,
                    run_without_items.created_at.isoformat(),
                    self._dump(run_without_items),
                ),
            )
            for advice_item in item.items:
                conn.execute(
                    """
                    INSERT INTO paper_advice_items(
                        id, run_id, signal_id, committee_run_id, symbol, final_status, created_at, payload
                    )
                    VALUES(?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        advice_item.id,
                        advice_item.run_id,
                        advice_item.signal_id,
                        advice_item.committee_run_id,
                        advice_item.symbol,
                        advice_item.final_status.value,
                        advice_item.created_at.isoformat(),
                        self._dump(advice_item),
                    ),
                )
        self.audit(
            "paper_advice_run_created",
            "paper_advice_run",
            item.id,
            {
                "signal_run_id": item.signal_run_id,
                "readiness_score": item.readiness_score,
                "item_count": len(item.items),
                "status_counts": item.metrics.get("status_counts", {}),
            },
        )
        return self.get_paper_advice_run(item.id) or item

    def get_paper_advice_run(self, run_id: str) -> PaperAdviceRun | None:
        run = self._get_payload("paper_advice_runs", PaperAdviceRun, "id", run_id)
        if not run:
            return None
        return run.model_copy(update={"items": self.list_paper_advice_items(run_id=run.id, limit=200)})

    def list_paper_advice_runs(self, *, limit: int = 20) -> list[PaperAdviceRun]:
        runs = self._list_payloads("paper_advice_runs", PaperAdviceRun, order_by="created_at DESC", limit=limit)
        return [run.model_copy(update={"items": self.list_paper_advice_items(run_id=run.id, limit=200)}) for run in runs]

    def get_latest_paper_advice_run(self) -> PaperAdviceRun | None:
        runs = self.list_paper_advice_runs(limit=1)
        return runs[0] if runs else None

    def list_paper_advice_items(self, *, run_id: str | None = None, limit: int = 100) -> list[PaperAdviceItem]:
        where = "run_id = ?" if run_id else ""
        args: tuple[Any, ...] = (run_id,) if run_id else ()
        return self._list_payloads(
            "paper_advice_items",
            PaperAdviceItem,
            where=where,
            args=args,
            order_by="created_at DESC",
            limit=limit,
        )

    def list_signals(
        self,
        *,
        run_id: str | None = None,
        status: SignalStatus | None = None,
        side: SignalSide | None = None,
        symbol: str | None = None,
        limit: int = 50,
    ) -> list[Signal]:
        clauses: list[str] = []
        args: list[Any] = []
        if run_id:
            clauses.append("run_id = ?")
            args.append(run_id)
        if status:
            clauses.append("status = ?")
            args.append(status.value)
        if side:
            clauses.append("side = ?")
            args.append(side.value)
        if symbol:
            clauses.append("symbol = ?")
            args.append(symbol.upper())
        return self._list_payloads(
            "signals",
            Signal,
            where=" AND ".join(clauses),
            args=tuple(args),
            order_by="created_at DESC",
            limit=limit,
        )

    def create_advisor_pulse(self, item: AdvisorPulse) -> AdvisorPulse:
        self._insert_payload(
            "advisor_pulses",
            ["id", "pulse_type", "severity", "created_at"],
            [item.id, item.pulse_type, item.severity.value, item.created_at.isoformat()],
            item,
            audit_event="advisor_pulse_created",
            entity_type="advisor_pulse",
            entity_id=item.id,
            audit_payload={
                "pulse_type": item.pulse_type,
                "severity": item.severity.value,
                "should_notify": item.should_notify,
                "run_card_id": item.run_card_id,
            },
        )
        for recommendation in item.recommendations:
            self.create_advisor_recommendation(recommendation)
        return item

    def list_advisor_pulses(
        self,
        *,
        severity: AdvisorPulseSeverity | None = None,
        limit: int = 50,
    ) -> list[AdvisorPulse]:
        where = "severity = ?" if severity else ""
        args: tuple[Any, ...] = (severity.value,) if severity else ()
        return self._list_payloads(
            "advisor_pulses",
            AdvisorPulse,
            where=where,
            args=args,
            order_by="created_at DESC",
            limit=limit,
        )

    def create_advisor_brief(self, item: AdvisorFullBrief) -> AdvisorFullBrief:
        self._insert_payload(
            "advisor_briefs",
            ["id", "brief_type", "market_session_date", "created_at"],
            [item.id, item.brief_type.value, item.market_session_date, item.created_at.isoformat()],
            item,
            audit_event="advisor_brief_created",
            entity_type="advisor_brief",
            entity_id=item.id,
            audit_payload={
                "brief_type": item.brief_type.value,
                "market_session_date": item.market_session_date,
                "run_card_id": item.run_card_id,
            },
        )
        for recommendation in item.recommendations:
            self.create_advisor_recommendation(recommendation)
        return item

    def list_advisor_briefs(self, *, brief_type: str | None = None, limit: int = 50) -> list[AdvisorFullBrief]:
        where = "brief_type = ?" if brief_type else ""
        args: tuple[Any, ...] = (brief_type,) if brief_type else ()
        return self._list_payloads(
            "advisor_briefs",
            AdvisorFullBrief,
            where=where,
            args=args,
            order_by="created_at DESC",
            limit=limit,
        )

    def get_latest_advisor_brief(self, *, brief_type: str | None = None) -> AdvisorFullBrief | None:
        briefs = self.list_advisor_briefs(brief_type=brief_type, limit=1)
        return briefs[0] if briefs else None

    def create_peer_group(self, item: PeerGroup) -> PeerGroup:
        self._insert_payload(
            "peer_groups",
            ["id", "name", "sector", "created_at"],
            [item.id, item.name, item.sector, item.created_at.isoformat()],
            item,
            audit_event="peer_group_created",
            entity_type="peer_group",
            entity_id=item.id,
            audit_payload={"sector": item.sector, "symbols": item.symbols},
        )
        return item

    def list_peer_groups(self, *, sector: str | None = None, limit: int = 50) -> list[PeerGroup]:
        where = "sector = ?" if sector else ""
        args: tuple[Any, ...] = (sector,) if sector else ()
        return self._list_payloads("peer_groups", PeerGroup, where=where, args=args, order_by="created_at DESC", limit=limit)

    def create_correlation_snapshot(self, item: CorrelationSnapshot) -> CorrelationSnapshot:
        self._insert_payload(
            "correlation_snapshots",
            ["id", "created_at"],
            [item.id, item.created_at.isoformat()],
            item,
            audit_event="correlation_snapshot_created",
            entity_type="correlation_snapshot",
            entity_id=item.id,
            audit_payload={"symbols": item.symbols, "run_card_id": item.run_card_id},
        )
        return item

    def get_correlation_snapshot(self, snapshot_id: str) -> CorrelationSnapshot | None:
        return self._get_payload("correlation_snapshots", CorrelationSnapshot, "id", snapshot_id)

    def list_correlation_snapshots(self, limit: int = 50) -> list[CorrelationSnapshot]:
        return self._list_payloads("correlation_snapshots", CorrelationSnapshot, order_by="created_at DESC", limit=limit)

    def create_sector_snapshot(self, item: SectorSnapshot) -> SectorSnapshot:
        self._insert_payload(
            "sector_snapshots",
            ["id", "sector", "created_at"],
            [item.id, item.sector, item.created_at.isoformat()],
            item,
            audit_event="sector_snapshot_created",
            entity_type="sector_snapshot",
            entity_id=item.id,
            audit_payload={"sector": item.sector, "run_card_id": item.run_card_id},
        )
        return item

    def get_sector_snapshot(self, snapshot_id: str) -> SectorSnapshot | None:
        return self._get_payload("sector_snapshots", SectorSnapshot, "id", snapshot_id)

    def list_sector_snapshots(self, *, sector: str | None = None, limit: int = 50) -> list[SectorSnapshot]:
        where = "sector = ?" if sector else ""
        args: tuple[Any, ...] = (sector,) if sector else ()
        return self._list_payloads("sector_snapshots", SectorSnapshot, where=where, args=args, order_by="created_at DESC", limit=limit)

    def create_options_snapshot(self, item: OptionsSnapshot) -> OptionsSnapshot:
        self._insert_payload(
            "options_snapshots",
            ["id", "symbol", "expiry", "created_at"],
            [item.id, item.symbol, item.expiry, item.created_at.isoformat()],
            item,
            audit_event="options_snapshot_created",
            entity_type="options_snapshot",
            entity_id=item.id,
            audit_payload={"symbol": item.symbol, "implied_move_pct": item.implied_move_pct},
        )
        return item

    def list_options_snapshots(self, *, symbol: str | None = None, limit: int = 50) -> list[OptionsSnapshot]:
        where = "symbol = ?" if symbol else ""
        args: tuple[Any, ...] = (symbol.upper(),) if symbol else ()
        return self._list_payloads("options_snapshots", OptionsSnapshot, where=where, args=args, order_by="created_at DESC", limit=limit)

    def create_dividend_review(self, item: DividendReview) -> DividendReview:
        self._insert_payload(
            "dividend_reviews",
            ["id", "symbol", "created_at"],
            [item.id, item.symbol, item.created_at.isoformat()],
            item,
            audit_event="dividend_review_created",
            entity_type="dividend_review",
            entity_id=item.id,
            audit_payload={"symbol": item.symbol, "run_card_id": item.run_card_id},
        )
        return item

    def list_dividend_reviews(self, *, symbol: str | None = None, limit: int = 50) -> list[DividendReview]:
        where = "symbol = ?" if symbol else ""
        args: tuple[Any, ...] = (symbol.upper(),) if symbol else ()
        return self._list_payloads("dividend_reviews", DividendReview, where=where, args=args, order_by="created_at DESC", limit=limit)

    def create_idea_screen(self, screen: IdeaScreen, candidates: list[IdeaCandidate]) -> IdeaScreen:
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO idea_screens(id, created_at, payload) VALUES(?, ?, ?)",
                (screen.id, screen.created_at.isoformat(), self._dump(screen)),
            )
            for candidate in candidates:
                conn.execute(
                    "INSERT INTO idea_candidates(id, symbol, status, created_at, payload) VALUES(?, ?, ?, ?, ?)",
                    (candidate.id, candidate.symbol, candidate.status.value, candidate.created_at.isoformat(), self._dump(candidate)),
                )
        self.audit("idea_screen_created", "idea_screen", screen.id, {"candidate_count": len(candidates)})
        return screen

    def create_idea_candidate(self, item: IdeaCandidate) -> IdeaCandidate:
        self._insert_payload(
            "idea_candidates",
            ["id", "symbol", "status", "created_at"],
            [item.id, item.symbol, item.status.value, item.created_at.isoformat()],
            item,
            audit_event="idea_candidate_created",
            entity_type="idea_candidate",
            entity_id=item.id,
            audit_payload={"symbol": item.symbol, "status": item.status.value},
        )
        return item

    def update_idea_candidate(self, item: IdeaCandidate) -> IdeaCandidate:
        self._update_payload(
            "idea_candidates",
            "id",
            item.id,
            ["symbol", "status", "created_at"],
            [item.symbol, item.status.value, item.created_at.isoformat()],
            item,
        )
        self.audit("idea_candidate_updated", "idea_candidate", item.id, {"status": item.status.value})
        return item

    def get_idea_candidate(self, candidate_id: str) -> IdeaCandidate | None:
        return self._get_payload("idea_candidates", IdeaCandidate, "id", candidate_id)

    def list_idea_candidates(
        self,
        *,
        status: IdeaCandidateStatus | None = None,
        symbol: str | None = None,
        limit: int = 50,
    ) -> list[IdeaCandidate]:
        clauses: list[str] = []
        args: list[Any] = []
        if status:
            clauses.append("status = ?")
            args.append(status.value)
        if symbol:
            clauses.append("symbol = ?")
            args.append(symbol.upper())
        return self._list_payloads(
            "idea_candidates",
            IdeaCandidate,
            where=" AND ".join(clauses),
            args=tuple(args),
            order_by="created_at DESC",
            limit=limit,
        )

    def create_committee_review(self, item: CommitteeReview) -> CommitteeReview:
        self._insert_payload(
            "committee_reviews",
            ["id", "created_at"],
            [item.id, item.created_at.isoformat()],
            item,
            audit_event="committee_review_created",
            entity_type="committee_review",
            entity_id=item.id,
            audit_payload={"conclusion": item.conclusion.value, "run_card_id": item.run_card_id},
        )
        return item

    def get_committee_review(self, review_id: str) -> CommitteeReview | None:
        return self._get_payload("committee_reviews", CommitteeReview, "id", review_id)

    def list_committee_reviews(self, limit: int = 50) -> list[CommitteeReview]:
        return self._list_payloads("committee_reviews", CommitteeReview, order_by="created_at DESC", limit=limit)

    def create_data_quality_report(self, item: DataQualityReport) -> DataQualityReport:
        self._insert_payload(
            "data_quality_reports",
            ["id", "target_type", "created_at"],
            [item.id, item.target_type.value, item.created_at.isoformat()],
            item,
            audit_event="data_quality_report_created",
            entity_type="data_quality_report",
            entity_id=item.id,
            audit_payload={"target_type": item.target_type.value, "run_card_id": item.run_card_id},
        )
        return item

    def get_data_quality_report(self, report_id: str) -> DataQualityReport | None:
        return self._get_payload("data_quality_reports", DataQualityReport, "id", report_id)

    def list_data_quality_reports(
        self,
        *,
        target_type: DataQualityTargetType | None = None,
        limit: int = 50,
    ) -> list[DataQualityReport]:
        where = "target_type = ?" if target_type else ""
        args: tuple[Any, ...] = (target_type.value,) if target_type else ()
        return self._list_payloads(
            "data_quality_reports",
            DataQualityReport,
            where=where,
            args=args,
            order_by="created_at DESC",
            limit=limit,
        )

    def get_trade_import(self, import_id: str) -> TradeImport | None:
        with self.connect() as conn:
            row = conn.execute("SELECT payload FROM trade_imports WHERE id = ?", (import_id,)).fetchone()
        return TradeImport.model_validate_json(row["payload"]) if row else None

    def get_trade_import_by_hash(self, file_hash: str) -> TradeImport | None:
        with self.connect() as conn:
            row = conn.execute("SELECT payload FROM trade_imports WHERE file_hash = ?", (file_hash,)).fetchone()
        return TradeImport.model_validate_json(row["payload"]) if row else None

    def create_trade_import(self, item: TradeImport) -> TradeImport:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO trade_imports(id, source, file_hash, imported_at, payload)
                VALUES(?, ?, ?, ?, ?)
                """,
                (
                    item.id,
                    item.source.value,
                    item.file_hash,
                    item.imported_at.isoformat(),
                    self._dump(item),
                ),
            )
        self.audit(
            "trade_journal_import_created",
            "trade_import",
            item.id,
            {"source": item.source.value, "row_count": item.row_count, "run_card_id": item.run_card_id},
        )
        return item

    def list_trade_imports(
        self,
        *,
        source: TradeJournalSource | None = None,
        limit: int = 50,
    ) -> list[TradeImport]:
        clauses: list[str] = []
        args: list[Any] = []
        if source:
            clauses.append("source = ?")
            args.append(source.value)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        query = f"SELECT payload FROM trade_imports {where} ORDER BY imported_at DESC LIMIT ?"
        args.append(limit)
        with self.connect() as conn:
            rows = conn.execute(query, tuple(args)).fetchall()
        return [TradeImport.model_validate_json(row["payload"]) for row in rows]

    def add_trade_fills(self, fills: list[TradeFill]) -> list[TradeFill]:
        inserted: list[TradeFill] = []
        with self.connect() as conn:
            for fill in fills:
                cursor = conn.execute(
                    """
                    INSERT OR IGNORE INTO trade_fills(id, import_id, symbol, side, traded_at, raw_row_hash, payload)
                    VALUES(?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        fill.id,
                        fill.import_id,
                        fill.symbol,
                        fill.side.value,
                        fill.traded_at.isoformat(),
                        fill.raw_row_hash,
                        self._dump(fill),
                    ),
                )
                if cursor.rowcount:
                    inserted.append(fill)
        if fills:
            self.audit(
                "trade_fills_imported",
                "trade_import",
                fills[0].import_id,
                {"submitted_count": len(fills), "inserted_count": len(inserted)},
            )
        return inserted

    def list_trade_fills(
        self,
        *,
        symbol: str | None = None,
        side: TradeFillSide | None = None,
        limit: int = 500,
        ascending: bool = False,
    ) -> list[TradeFill]:
        clauses: list[str] = []
        args: list[Any] = []
        if symbol:
            clauses.append("symbol = ?")
            args.append(symbol.upper())
        if side:
            clauses.append("side = ?")
            args.append(side.value)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        order = "ASC" if ascending else "DESC"
        query = f"SELECT payload FROM trade_fills {where} ORDER BY traded_at {order}, id {order} LIMIT ?"
        args.append(limit)
        with self.connect() as conn:
            rows = conn.execute(query, tuple(args)).fetchall()
        return [TradeFill.model_validate_json(row["payload"]) for row in rows]

    def replace_trade_roundtrips(self, roundtrips: list[TradeRoundTrip]) -> list[TradeRoundTrip]:
        with self.connect() as conn:
            conn.execute("DELETE FROM trade_roundtrips")
            for roundtrip in roundtrips:
                conn.execute(
                    """
                    INSERT INTO trade_roundtrips(id, import_id, symbol, opened_at, closed_at, payload)
                    VALUES(?, ?, ?, ?, ?, ?)
                    """,
                    (
                        roundtrip.id,
                        roundtrip.import_id,
                        roundtrip.symbol,
                        roundtrip.opened_at.isoformat(),
                        roundtrip.closed_at.isoformat(),
                        self._dump(roundtrip),
                    ),
                )
        self.audit(
            "trade_roundtrips_rebuilt",
            "trade_roundtrip",
            "fifo",
            {"roundtrip_count": len(roundtrips), "pairing_method": "fifo"},
        )
        return roundtrips

    def list_trade_roundtrips(self, *, symbol: str | None = None, limit: int = 500) -> list[TradeRoundTrip]:
        clauses: list[str] = []
        args: list[Any] = []
        if symbol:
            clauses.append("symbol = ?")
            args.append(symbol.upper())
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        query = f"SELECT payload FROM trade_roundtrips {where} ORDER BY closed_at DESC LIMIT ?"
        args.append(limit)
        with self.connect() as conn:
            rows = conn.execute(query, tuple(args)).fetchall()
        return [TradeRoundTrip.model_validate_json(row["payload"]) for row in rows]

    def create_behavior_report(self, report: BehaviorReport) -> BehaviorReport:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO behavior_reports(id, period_start, period_end, created_at, payload)
                VALUES(?, ?, ?, ?, ?)
                """,
                (
                    report.id,
                    report.period_start.isoformat() if report.period_start else None,
                    report.period_end.isoformat() if report.period_end else None,
                    report.created_at.isoformat(),
                    self._dump(report),
                ),
            )
        self.audit(
            "behavior_report_created",
            "behavior_report",
            report.id,
            {
                "total_trades": report.total_trades,
                "total_roundtrips": report.total_roundtrips,
                "run_card_id": report.run_card_id,
            },
        )
        return report

    def get_behavior_report(self, report_id: str) -> BehaviorReport | None:
        with self.connect() as conn:
            row = conn.execute("SELECT payload FROM behavior_reports WHERE id = ?", (report_id,)).fetchone()
        return BehaviorReport.model_validate_json(row["payload"]) if row else None

    def list_behavior_reports(
        self,
        *,
        symbol: str | None = None,
        limit: int = 50,
    ) -> list[BehaviorReport]:
        query = "SELECT payload FROM behavior_reports ORDER BY created_at DESC LIMIT ?"
        with self.connect() as conn:
            rows = conn.execute(query, (limit,)).fetchall()
        reports = [BehaviorReport.model_validate_json(row["payload"]) for row in rows]
        if symbol:
            symbol = symbol.upper()
            reports = [report for report in reports if symbol in report.symbols]
        return reports

    def create_shadow_strategy(self, strategy: ShadowStrategy) -> ShadowStrategy:
        stored_strategy = strategy.model_copy(update={"rules": []})
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO shadow_strategies(id, source_behavior_report_id, status, created_at, updated_at, payload)
                VALUES(?, ?, ?, ?, ?, ?)
                """,
                (
                    stored_strategy.id,
                    stored_strategy.source_behavior_report_id,
                    stored_strategy.status.value,
                    stored_strategy.created_at.isoformat(),
                    stored_strategy.updated_at.isoformat(),
                    self._dump(stored_strategy),
                ),
            )
            for rule in strategy.rules:
                conn.execute(
                    """
                    INSERT INTO shadow_rules(id, strategy_id, rule_type, created_at, payload)
                    VALUES(?, ?, ?, ?, ?)
                    """,
                    (rule.id, strategy.id, rule.rule_type.value, rule.created_at.isoformat(), self._dump(rule)),
                )
        self.audit(
            "shadow_strategy_created",
            "shadow_strategy",
            strategy.id,
            {
                "source_behavior_report_id": strategy.source_behavior_report_id,
                "status": strategy.status.value,
                "rule_count": len(strategy.rules),
                "run_card_id": strategy.run_card_id,
            },
        )
        return self.get_shadow_strategy(strategy.id) or strategy

    def update_shadow_strategy(
        self,
        strategy: ShadowStrategy,
        event_type: str = "shadow_strategy_updated",
    ) -> ShadowStrategy:
        stored_strategy = strategy.model_copy(update={"rules": []})
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE shadow_strategies
                SET source_behavior_report_id = ?, status = ?, updated_at = ?, payload = ?
                WHERE id = ?
                """,
                (
                    stored_strategy.source_behavior_report_id,
                    stored_strategy.status.value,
                    stored_strategy.updated_at.isoformat(),
                    self._dump(stored_strategy),
                    stored_strategy.id,
                ),
            )
        self.audit(
            event_type,
            "shadow_strategy",
            strategy.id,
            {"status": strategy.status.value, "human_confirmed": strategy.human_confirmed},
        )
        return self.get_shadow_strategy(strategy.id) or strategy

    def get_shadow_strategy(self, strategy_id: str) -> ShadowStrategy | None:
        with self.connect() as conn:
            row = conn.execute("SELECT payload FROM shadow_strategies WHERE id = ?", (strategy_id,)).fetchone()
        if not row:
            return None
        strategy = ShadowStrategy.model_validate_json(row["payload"])
        strategy.rules = self.list_shadow_rules(strategy.id)
        return strategy

    def list_shadow_strategies(
        self,
        *,
        status: ShadowStrategyStatus | None = None,
        limit: int = 50,
    ) -> list[ShadowStrategy]:
        clauses: list[str] = []
        args: list[Any] = []
        if status:
            clauses.append("status = ?")
            args.append(status.value)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        query = f"SELECT payload FROM shadow_strategies {where} ORDER BY updated_at DESC LIMIT ?"
        args.append(limit)
        with self.connect() as conn:
            rows = conn.execute(query, tuple(args)).fetchall()
        strategies = [ShadowStrategy.model_validate_json(row["payload"]) for row in rows]
        for strategy in strategies:
            strategy.rules = self.list_shadow_rules(strategy.id)
        return strategies

    def list_shadow_rules(self, strategy_id: str) -> list[ShadowRule]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT payload FROM shadow_rules WHERE strategy_id = ? ORDER BY created_at ASC, id ASC",
                (strategy_id,),
            ).fetchall()
        return [ShadowRule.model_validate_json(row["payload"]) for row in rows]

    def create_shadow_report(self, report: ShadowReport, events: list[ShadowEvent]) -> ShadowReport:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO shadow_reports(id, strategy_id, behavior_report_id, created_at, payload)
                VALUES(?, ?, ?, ?, ?)
                """,
                (
                    report.id,
                    report.strategy_id,
                    report.behavior_report_id,
                    report.created_at.isoformat(),
                    self._dump(report),
                ),
            )
            for event in events:
                conn.execute(
                    """
                    INSERT INTO shadow_events(id, shadow_report_id, symbol, event_type, created_at, payload)
                    VALUES(?, ?, ?, ?, ?, ?)
                    """,
                    (
                        event.id,
                        event.shadow_report_id,
                        event.symbol,
                        event.event_type.value,
                        event.created_at.isoformat(),
                        self._dump(event),
                    ),
                )
        self.audit(
            "shadow_report_created",
            "shadow_report",
            report.id,
            {
                "strategy_id": report.strategy_id,
                "behavior_report_id": report.behavior_report_id,
                "event_count": len(events),
                "run_card_id": report.run_card_id,
            },
        )
        return report

    def get_shadow_report(self, report_id: str) -> ShadowReport | None:
        with self.connect() as conn:
            row = conn.execute("SELECT payload FROM shadow_reports WHERE id = ?", (report_id,)).fetchone()
        return ShadowReport.model_validate_json(row["payload"]) if row else None

    def list_shadow_reports(
        self,
        *,
        strategy_id: str | None = None,
        limit: int = 50,
    ) -> list[ShadowReport]:
        clauses: list[str] = []
        args: list[Any] = []
        if strategy_id:
            clauses.append("strategy_id = ?")
            args.append(strategy_id)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        query = f"SELECT payload FROM shadow_reports {where} ORDER BY created_at DESC LIMIT ?"
        args.append(limit)
        with self.connect() as conn:
            rows = conn.execute(query, tuple(args)).fetchall()
        return [ShadowReport.model_validate_json(row["payload"]) for row in rows]

    def list_shadow_events(
        self,
        *,
        shadow_report_id: str | None = None,
        symbol: str | None = None,
        limit: int = 100,
    ) -> list[ShadowEvent]:
        clauses: list[str] = []
        args: list[Any] = []
        if shadow_report_id:
            clauses.append("shadow_report_id = ?")
            args.append(shadow_report_id)
        if symbol:
            clauses.append("symbol = ?")
            args.append(symbol.upper())
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        query = f"SELECT payload FROM shadow_events {where} ORDER BY created_at DESC LIMIT ?"
        args.append(limit)
        with self.connect() as conn:
            rows = conn.execute(query, tuple(args)).fetchall()
        return [ShadowEvent.model_validate_json(row["payload"]) for row in rows]

    def create_thesis(self, thesis: Thesis) -> Thesis:
        stored_thesis = thesis.model_copy(update={"updates": []})
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO theses(id, symbol, side, status, updated_at, payload)
                VALUES(?, ?, ?, ?, ?, ?)
                """,
                (
                    stored_thesis.id,
                    stored_thesis.symbol,
                    stored_thesis.side.value,
                    stored_thesis.status.value,
                    stored_thesis.updated_at.isoformat(),
                    self._dump(stored_thesis),
                ),
            )
            for pillar in stored_thesis.pillars:
                conn.execute(
                    """
                    INSERT INTO thesis_pillars(id, thesis_id, status, payload)
                    VALUES(?, ?, ?, ?)
                    """,
                    (pillar.id, pillar.thesis_id, pillar.status.value, self._dump(pillar)),
                )
            for risk in stored_thesis.risks:
                conn.execute(
                    """
                    INSERT INTO thesis_risks(id, thesis_id, status, payload)
                    VALUES(?, ?, ?, ?)
                    """,
                    (risk.id, risk.thesis_id, risk.status.value, self._dump(risk)),
                )
        self.audit(
            "thesis_created",
            "thesis",
            thesis.id,
            {"symbol": thesis.symbol, "status": thesis.status.value, "conviction": thesis.conviction.value},
        )
        return self.get_thesis(thesis.id) or thesis

    def update_thesis(self, thesis: Thesis, event_type: str = "thesis_updated") -> Thesis:
        stored_thesis = thesis.model_copy(update={"updates": []})
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE theses
                SET symbol = ?, side = ?, status = ?, updated_at = ?, payload = ?
                WHERE id = ?
                """,
                (
                    stored_thesis.symbol,
                    stored_thesis.side.value,
                    stored_thesis.status.value,
                    stored_thesis.updated_at.isoformat(),
                    self._dump(stored_thesis),
                    stored_thesis.id,
                ),
            )
        self.audit(event_type, "thesis", thesis.id, {"symbol": thesis.symbol, "status": thesis.status.value})
        return self.get_thesis(thesis.id) or thesis

    def add_thesis_update(self, thesis: Thesis, update: ThesisUpdate) -> Thesis:
        stored_thesis = thesis.model_copy(update={"updates": []})
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO thesis_updates(id, thesis_id, research_goal_id, impact, created_at, payload)
                VALUES(?, ?, ?, ?, ?, ?)
                """,
                (
                    update.id,
                    update.thesis_id,
                    update.research_goal_id,
                    update.impact.value,
                    update.created_at.isoformat(),
                    self._dump(update),
                ),
            )
            conn.execute(
                """
                UPDATE theses
                SET symbol = ?, side = ?, status = ?, updated_at = ?, payload = ?
                WHERE id = ?
                """,
                (
                    stored_thesis.symbol,
                    stored_thesis.side.value,
                    stored_thesis.status.value,
                    stored_thesis.updated_at.isoformat(),
                    self._dump(stored_thesis),
                    stored_thesis.id,
                ),
            )
        self.audit(
            "thesis_update_added",
            "thesis",
            thesis.id,
            {"impact": update.impact.value, "research_goal_id": update.research_goal_id},
        )
        return self.get_thesis(thesis.id) or thesis

    def get_thesis(self, thesis_id: str) -> Thesis | None:
        with self.connect() as conn:
            row = conn.execute("SELECT payload FROM theses WHERE id = ?", (thesis_id,)).fetchone()
        if not row:
            return None
        thesis = Thesis.model_validate_json(row["payload"])
        thesis.pillars = self.list_thesis_pillars(thesis.id)
        thesis.risks = self.list_thesis_risks(thesis.id)
        thesis.updates = self.list_thesis_updates(thesis.id)
        return thesis

    def list_theses(
        self,
        status: ThesisStatus | None = None,
        *,
        symbol: str | None = None,
        limit: int = 50,
    ) -> list[Thesis]:
        clauses: list[str] = []
        args: list[Any] = []
        if status:
            clauses.append("status = ?")
            args.append(status.value)
        if symbol:
            clauses.append("symbol = ?")
            args.append(symbol.upper())
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        query = f"SELECT payload FROM theses {where} ORDER BY updated_at DESC LIMIT ?"
        args.append(limit)
        with self.connect() as conn:
            rows = conn.execute(query, tuple(args)).fetchall()
        theses = [Thesis.model_validate_json(row["payload"]) for row in rows]
        for thesis in theses:
            thesis.pillars = self.list_thesis_pillars(thesis.id)
            thesis.risks = self.list_thesis_risks(thesis.id)
            thesis.updates = self.list_thesis_updates(thesis.id)
        return theses

    def get_active_thesis_for_symbol(self, symbol: str) -> Thesis | None:
        candidates = [
            thesis
            for thesis in self.list_theses(status=ThesisStatus.ACTIVE, symbol=symbol, limit=5)
            if thesis.human_confirmed
        ]
        return candidates[0] if candidates else None

    def list_thesis_pillars(self, thesis_id: str) -> list[ThesisPillar]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT payload FROM thesis_pillars WHERE thesis_id = ? ORDER BY id",
                (thesis_id,),
            ).fetchall()
        return [ThesisPillar.model_validate_json(row["payload"]) for row in rows]

    def list_thesis_risks(self, thesis_id: str) -> list[ThesisRisk]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT payload FROM thesis_risks WHERE thesis_id = ? ORDER BY id",
                (thesis_id,),
            ).fetchall()
        return [ThesisRisk.model_validate_json(row["payload"]) for row in rows]

    def list_thesis_updates(self, thesis_id: str) -> list[ThesisUpdate]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT payload FROM thesis_updates WHERE thesis_id = ? ORDER BY created_at DESC",
                (thesis_id,),
            ).fetchall()
        return [ThesisUpdate.model_validate_json(row["payload"]) for row in rows]

    def create_catalyst(self, catalyst: Catalyst) -> Catalyst:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO catalysts(id, symbol, event_type, status, event_date, expected_impact, payload)
                VALUES(?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    catalyst.id,
                    catalyst.symbol,
                    catalyst.event_type.value,
                    catalyst.status.value,
                    catalyst.event_date.isoformat(),
                    catalyst.expected_impact.value,
                    self._dump(catalyst),
                ),
            )
        self.audit(
            "catalyst_created",
            "catalyst",
            catalyst.id,
            {
                "symbol": catalyst.symbol,
                "event_type": catalyst.event_type.value,
                "expected_impact": catalyst.expected_impact.value,
                "verification_status": catalyst.verification_status.value,
            },
        )
        return catalyst

    def update_catalyst(self, catalyst: Catalyst, event_type: str = "catalyst_updated") -> Catalyst:
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE catalysts
                SET symbol = ?, event_type = ?, status = ?, event_date = ?, expected_impact = ?, payload = ?
                WHERE id = ?
                """,
                (
                    catalyst.symbol,
                    catalyst.event_type.value,
                    catalyst.status.value,
                    catalyst.event_date.isoformat(),
                    catalyst.expected_impact.value,
                    self._dump(catalyst),
                    catalyst.id,
                ),
            )
        self.audit(event_type, "catalyst", catalyst.id, {"symbol": catalyst.symbol, "status": catalyst.status.value})
        return self.get_catalyst(catalyst.id) or catalyst

    def get_catalyst(self, catalyst_id: str) -> Catalyst | None:
        with self.connect() as conn:
            row = conn.execute("SELECT payload FROM catalysts WHERE id = ?", (catalyst_id,)).fetchone()
        return Catalyst.model_validate_json(row["payload"]) if row else None

    def list_catalysts(
        self,
        status: CatalystStatus | None = None,
        *,
        symbol: str | None = None,
        limit: int = 50,
    ) -> list[Catalyst]:
        clauses: list[str] = []
        args: list[Any] = []
        if status:
            clauses.append("status = ?")
            args.append(status.value)
        if symbol:
            clauses.append("symbol = ?")
            args.append(symbol.upper())
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        query = f"SELECT payload FROM catalysts {where} ORDER BY event_date ASC LIMIT ?"
        args.append(limit)
        with self.connect() as conn:
            rows = conn.execute(query, tuple(args)).fetchall()
        return [Catalyst.model_validate_json(row["payload"]) for row in rows]

    def create_catalyst_review(self, review: CatalystReview) -> CatalystReview:
        if not self.get_catalyst(review.catalyst_id):
            raise ValueError(f"catalyst not found: {review.catalyst_id}")
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO catalyst_reviews(id, catalyst_id, research_goal_id, thesis_delta, created_at, payload)
                VALUES(?, ?, ?, ?, ?, ?)
                """,
                (
                    review.id,
                    review.catalyst_id,
                    review.research_goal_id,
                    review.thesis_delta.value,
                    review.created_at.isoformat(),
                    self._dump(review),
                ),
            )
        self.audit(
            "catalyst_review_created",
            "catalyst",
            review.catalyst_id,
            {"review_id": review.id, "thesis_delta": review.thesis_delta.value},
        )
        return review

    def list_catalyst_reviews(self, catalyst_id: str) -> list[CatalystReview]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT payload FROM catalyst_reviews WHERE catalyst_id = ? ORDER BY created_at DESC",
                (catalyst_id,),
            ).fetchall()
        return [CatalystReview.model_validate_json(row["payload"]) for row in rows]

    def create_earnings_review(self, review: EarningsReview) -> EarningsReview:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO earnings_reviews(id, symbol, catalyst_id, research_goal_id, thesis_delta, created_at, payload)
                VALUES(?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    review.id,
                    review.symbol,
                    review.catalyst_id,
                    review.research_goal_id,
                    review.thesis_delta.value,
                    review.created_at.isoformat(),
                    self._dump(review),
                ),
            )
        self.audit(
            "earnings_review_created",
            "earnings_review",
            review.id,
            {
                "symbol": review.symbol,
                "catalyst_id": review.catalyst_id,
                "research_goal_id": review.research_goal_id,
                "thesis_delta": review.thesis_delta.value,
            },
        )
        return review

    def get_earnings_review(self, review_id: str) -> EarningsReview | None:
        with self.connect() as conn:
            row = conn.execute("SELECT payload FROM earnings_reviews WHERE id = ?", (review_id,)).fetchone()
        return EarningsReview.model_validate_json(row["payload"]) if row else None

    def list_earnings_reviews(self, *, symbol: str | None = None, limit: int = 50) -> list[EarningsReview]:
        clauses: list[str] = []
        args: list[Any] = []
        if symbol:
            clauses.append("symbol = ?")
            args.append(symbol.upper())
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        query = f"SELECT payload FROM earnings_reviews {where} ORDER BY created_at DESC LIMIT ?"
        args.append(limit)
        with self.connect() as conn:
            rows = conn.execute(query, tuple(args)).fetchall()
        return [EarningsReview.model_validate_json(row["payload"]) for row in rows]

    def create_proposal(self, proposal: Proposal) -> Proposal:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO proposals(id, status, symbol, side, created_at, expires_at, payload)
                VALUES(?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    proposal.id,
                    proposal.status.value,
                    proposal.symbol,
                    proposal.side.value,
                    proposal.created_at.isoformat(),
                    proposal.expires_at.isoformat(),
                    self._dump(proposal),
                ),
            )
        self.audit("proposal_created", "proposal", proposal.id, {"status": proposal.status.value})
        return proposal

    def update_proposal(self, proposal: Proposal, event_type: str = "proposal_updated") -> Proposal:
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE proposals
                SET status = ?, symbol = ?, side = ?, expires_at = ?, payload = ?
                WHERE id = ?
                """,
                (
                    proposal.status.value,
                    proposal.symbol,
                    proposal.side.value,
                    proposal.expires_at.isoformat(),
                    self._dump(proposal),
                    proposal.id,
                ),
            )
        self.audit(event_type, "proposal", proposal.id, {"status": proposal.status.value})
        return proposal

    def get_proposal(self, proposal_id: str) -> Proposal | None:
        with self.connect() as conn:
            row = conn.execute("SELECT status, payload FROM proposals WHERE id = ?", (proposal_id,)).fetchone()
        return self._proposal_from_row(row) if row else None

    def list_proposals(self, status: ProposalStatus | None = None, limit: int = 100) -> list[Proposal]:
        if status:
            query = "SELECT status, payload FROM proposals WHERE status = ? ORDER BY created_at DESC LIMIT ?"
            args: tuple[Any, ...] = (status.value, limit)
        else:
            query = "SELECT status, payload FROM proposals ORDER BY created_at DESC LIMIT ?"
            args = (limit,)
        with self.connect() as conn:
            rows = conn.execute(query, args).fetchall()
        return [proposal for row in rows if (proposal := self._proposal_from_row(row)) is not None]

    def pending_for_symbol(self, symbol: str, side: str | None = None) -> list[Proposal]:
        query = "SELECT status, payload FROM proposals WHERE status = ? AND symbol = ?"
        args: tuple[Any, ...] = (ProposalStatus.PENDING.value, symbol.upper())
        if side:
            query += " AND side = ?"
            args = (*args, side.upper())
        with self.connect() as conn:
            rows = conn.execute(query, args).fetchall()
        return [proposal for row in rows if (proposal := self._proposal_from_row(row)) is not None]

    def proposal_status_mismatches(self, limit: int = 20) -> dict[str, Any]:
        mismatches: list[dict[str, Any]] = []
        with self.connect() as conn:
            rows = conn.execute("SELECT id, status, symbol, created_at, payload FROM proposals ORDER BY created_at DESC").fetchall()
        for row in rows:
            try:
                proposal = Proposal.model_validate_json(row["payload"])
            except Exception as exc:  # pragma: no cover - corrupt payload diagnostic
                mismatches.append(
                    {
                        "id": row["id"],
                        "symbol": row["symbol"],
                        "table_status": row["status"],
                        "payload_status": "unreadable",
                        "created_at": row["created_at"],
                        "error": str(exc),
                    }
                )
                continue
            table_status = str(row["status"])
            payload_status = proposal.status.value
            if table_status != payload_status:
                mismatches.append(
                    {
                        "id": row["id"],
                        "symbol": row["symbol"],
                        "table_status": table_status,
                        "payload_status": payload_status,
                        "created_at": row["created_at"],
                    }
                )
        return {"count": len(mismatches), "examples": mismatches[:limit]}

    def _proposal_from_row(self, row: sqlite3.Row | None) -> Proposal | None:
        if row is None:
            return None
        proposal = Proposal.model_validate_json(row["payload"])
        try:
            table_status = ProposalStatus(str(row["status"]))
        except (KeyError, ValueError):
            return proposal
        if proposal.status != table_status:
            return proposal.model_copy(update={"status": table_status})
        return proposal

    def create_sqlite_backup(self, label: str = "manual") -> Path:
        timestamp = utc_now().astimezone(timezone.utc).strftime("%Y%m%d_%H%M%S")
        safe_label = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "-" for ch in label).strip("-") or "manual"
        backup_dir = self.db_path.parent / "backups"
        backup_dir.mkdir(parents=True, exist_ok=True)
        backup_path = backup_dir / f"{self.db_path.stem}-{timestamp}-{safe_label}{self.db_path.suffix or '.db'}"
        with self.connect() as source, sqlite3.connect(backup_path) as target:
            source.backup(target)
        self.audit("sqlite_backup_created", "database", str(self.db_path), {"backup_path": str(backup_path), "label": label})
        return backup_path

    def create_execution(self, execution: ExecutionRecord) -> ExecutionRecord:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO executions(id, proposal_id, status, created_at, payload)
                VALUES(?, ?, ?, ?, ?)
                """,
                (
                    execution.id,
                    execution.proposal_id,
                    execution.status,
                    execution.created_at.isoformat(),
                    self._dump(execution),
                ),
            )
        self.audit("paper_execution_recorded", "execution", execution.id, {"proposal_id": execution.proposal_id})
        return execution

    def list_executions(self, proposal_id: str | None = None) -> list[ExecutionRecord]:
        if proposal_id:
            query = "SELECT payload FROM executions WHERE proposal_id = ? ORDER BY created_at DESC"
            args: tuple[Any, ...] = (proposal_id,)
        else:
            query = "SELECT payload FROM executions ORDER BY created_at DESC"
            args = ()
        with self.connect() as conn:
            rows = conn.execute(query, args).fetchall()
        return [ExecutionRecord.model_validate_json(row["payload"]) for row in rows]

    def audit(self, event_type: str, entity_type: str, entity_id: str, payload: dict[str, Any]) -> None:
        event = AuditEvent(
            event_type=event_type,
            entity_type=entity_type,
            entity_id=entity_id,
            payload=payload,
        )
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO audit_events(event_type, entity_type, entity_id, created_at, payload)
                VALUES(?, ?, ?, ?, ?)
                """,
                (
                    event.event_type,
                    event.entity_type,
                    event.entity_id,
                    event.created_at.isoformat(),
                    json.dumps(event.payload, default=str),
                ),
            )

    def list_audit_events(self, limit: int = 100, event_type: str | None = None) -> list[dict[str, Any]]:
        if event_type:
            query = "SELECT * FROM audit_events WHERE event_type = ? ORDER BY id DESC LIMIT ?"
            args: tuple[Any, ...] = (event_type, limit)
        else:
            query = "SELECT * FROM audit_events ORDER BY id DESC LIMIT ?"
            args = (limit,)
        with self.connect() as conn:
            rows = conn.execute(query, args).fetchall()
        return [dict(row) for row in rows]
