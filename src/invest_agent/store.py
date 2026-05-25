from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from .models import (
    AuditEvent,
    ExecutionRecord,
    FundamentalSnapshot,
    NewsItem,
    PortfolioSnapshot,
    Proposal,
    ProposalStatus,
    Quote,
    ResearchEvidence,
    ResearchGoal,
    ResearchGoalStatus,
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
                """
            )

    @staticmethod
    def _dump(model: Any) -> str:
        return model.model_dump_json()

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
