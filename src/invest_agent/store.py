from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from .models import (
    AuditEvent,
    BehaviorReport,
    Catalyst,
    CatalystReview,
    CatalystStatus,
    EarningsReview,
    ExecutionRecord,
    FundamentalSnapshot,
    MarketRegimeSnapshot,
    NewsItem,
    PortfolioSnapshot,
    Proposal,
    ProposalStatus,
    Quote,
    ResearchEvidence,
    ResearchGoal,
    ResearchGoalStatus,
    ResearchRunCard,
    RunCardStatus,
    RunCardType,
    ShadowEvent,
    ShadowReport,
    ShadowRule,
    ShadowStrategy,
    ShadowStrategyStatus,
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
                """
            )
            self._ensure_column(conn, "shadow_rules", "created_at", "TEXT")

    @staticmethod
    def _dump(model: Any) -> str:
        return model.model_dump_json()

    @staticmethod
    def _ensure_column(conn: sqlite3.Connection, table: str, column: str, definition: str) -> None:
        columns = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
        if column not in columns:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

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
            row = conn.execute("SELECT payload FROM proposals WHERE id = ?", (proposal_id,)).fetchone()
        return Proposal.model_validate_json(row["payload"]) if row else None

    def list_proposals(self, status: ProposalStatus | None = None, limit: int = 100) -> list[Proposal]:
        if status:
            query = "SELECT payload FROM proposals WHERE status = ? ORDER BY created_at DESC LIMIT ?"
            args: tuple[Any, ...] = (status.value, limit)
        else:
            query = "SELECT payload FROM proposals ORDER BY created_at DESC LIMIT ?"
            args = (limit,)
        with self.connect() as conn:
            rows = conn.execute(query, args).fetchall()
        return [Proposal.model_validate_json(row["payload"]) for row in rows]

    def pending_for_symbol(self, symbol: str, side: str | None = None) -> list[Proposal]:
        query = "SELECT payload FROM proposals WHERE status = ? AND symbol = ?"
        args: tuple[Any, ...] = (ProposalStatus.PENDING.value, symbol.upper())
        if side:
            query += " AND side = ?"
            args = (*args, side.upper())
        with self.connect() as conn:
            rows = conn.execute(query, args).fetchall()
        return [Proposal.model_validate_json(row["payload"]) for row in rows]

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
