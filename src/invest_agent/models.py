from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def new_id(prefix: str) -> str:
    return f"{prefix}_{utc_now().strftime('%Y%m%d_%H%M%S')}_{uuid4().hex[:8]}"


class ProposalStatus(StrEnum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"
    RISK_REJECTED = "RISK_REJECTED"
    EXECUTED = "EXECUTED"


class Side(StrEnum):
    BUY = "BUY"
    SELL = "SELL"


class ExecutionMode(StrEnum):
    PAPER = "PAPER"
    LIVE = "LIVE"


class Position(BaseModel):
    symbol: str
    qty: float
    market_value: float
    avg_cost: float = 0.0
    last_price: float = 0.0
    unrealized_pl: float = 0.0


class PortfolioSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cash_usd: float = 0.0
    total_value_usd: float = 0.0
    positions: list[Position] = Field(default_factory=list)
    updated_at: datetime = Field(default_factory=utc_now)
    source: str = "demo"


class Quote(BaseModel):
    symbol: str
    last_price: float
    bid: float | None = None
    ask: float | None = None
    currency: str = "USD"
    updated_at: datetime = Field(default_factory=utc_now)
    source: str = "demo"


class NewsItem(BaseModel):
    id: str = Field(default_factory=lambda: new_id("news"))
    symbol: str | None = None
    title: str
    source: str = "demo"
    url: str | None = None
    published_at: datetime = Field(default_factory=utc_now)
    tags: list[str] = Field(default_factory=list)
    summary: str = ""


class RiskCheck(BaseModel):
    passed: bool
    reasons: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    metrics: dict[str, Any] = Field(default_factory=dict)


class ProposalCreate(BaseModel):
    symbol: str
    side: Side
    qty: int = Field(gt=0)
    limit_price: float = Field(gt=0)
    thesis: str = Field(min_length=8)
    trigger: str = Field(min_length=3)
    confidence: float = Field(ge=0.0, le=1.0)
    ttl_minutes: int | None = Field(default=None, gt=0, le=1440)
    max_slippage_bps: float | None = Field(default=None, gt=0, le=1000)
    evidence: list[str] = Field(default_factory=list)
    counter_evidence: list[str] = Field(default_factory=list)

    @field_validator("symbol")
    @classmethod
    def normalize_symbol(cls, value: str) -> str:
        return value.strip().upper()


class Proposal(BaseModel):
    id: str = Field(default_factory=lambda: new_id("prop"))
    symbol: str
    side: Side
    qty: int
    limit_price: float
    thesis: str
    trigger: str
    confidence: float
    evidence: list[str] = Field(default_factory=list)
    counter_evidence: list[str] = Field(default_factory=list)
    status: ProposalStatus = ProposalStatus.PENDING
    risk_check: RiskCheck
    created_at: datetime = Field(default_factory=utc_now)
    expires_at: datetime
    approved_at: datetime | None = None
    rejected_at: datetime | None = None
    rejection_reason: str | None = None
    approved_by: str | None = None
    max_slippage_bps: float = 30.0
    execution_mode: ExecutionMode = ExecutionMode.PAPER

    @property
    def notional_usd(self) -> float:
        return float(self.qty) * float(self.limit_price)


class NewsIngestResult(BaseModel):
    symbols: list[str] = Field(default_factory=list)
    total_count: int = 0
    stored_count: int = 0
    sources: dict[str, int] = Field(default_factory=dict)
    errors: list[str] = Field(default_factory=list)
    items: list[NewsItem] = Field(default_factory=list)


class FundamentalMetric(BaseModel):
    name: str
    label: str = ""
    concept: str = ""
    value: float | None = None
    unit: str = ""
    fiscal_year: int | None = None
    fiscal_period: str = ""
    end_date: str = ""
    form: str = ""
    filed_at: datetime | None = None
    frame: str | None = None
    yoy_change_pct: float | None = None
    source: str = "sec-companyfacts"


class FundamentalSnapshot(BaseModel):
    symbol: str
    cik: str
    entity_name: str = ""
    metrics: dict[str, FundamentalMetric] = Field(default_factory=dict)
    updated_at: datetime = Field(default_factory=utc_now)
    source: str = "sec-companyfacts"

    @field_validator("symbol")
    @classmethod
    def normalize_symbol(cls, value: str) -> str:
        return value.strip().upper()


class FundamentalsRefreshResult(BaseModel):
    symbols: list[str] = Field(default_factory=list)
    total_count: int = 0
    stored_count: int = 0
    errors: list[str] = Field(default_factory=list)
    snapshots: list[FundamentalSnapshot] = Field(default_factory=list)


class ProposalDraft(BaseModel):
    symbol: str
    side: Side
    qty: int
    limit_price: float
    confidence: float
    trigger: str
    thesis: str
    evidence: list[str] = Field(default_factory=list)
    counter_evidence: list[str] = Field(default_factory=list)
    score: int
    news_count: int
    source_news_ids: list[str] = Field(default_factory=list)


class DraftProposalResult(BaseModel):
    watchlist: list[str] = Field(default_factory=list)
    drafts: list[ProposalDraft] = Field(default_factory=list)
    created: list[Proposal] = Field(default_factory=list)
    skipped: list[str] = Field(default_factory=list)


class AutomationStepResult(BaseModel):
    name: str
    status: str
    started_at: datetime = Field(default_factory=utc_now)
    finished_at: datetime = Field(default_factory=utc_now)
    message: str = ""
    metrics: dict[str, Any] = Field(default_factory=dict)


class AutomationRunResult(BaseModel):
    mode: str = "once"
    started_at: datetime = Field(default_factory=utc_now)
    finished_at: datetime = Field(default_factory=utc_now)
    cycle_number: int = 1
    created_proposals: list[Proposal] = Field(default_factory=list)
    skipped: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    steps: list[AutomationStepResult] = Field(default_factory=list)


class EventReplayResult(BaseModel):
    path: str
    imported_counts: dict[str, int] = Field(default_factory=dict)
    exported_counts: dict[str, int] = Field(default_factory=dict)
    errors: list[str] = Field(default_factory=list)
    draft_result: DraftProposalResult | None = None


class ExecutionRecord(BaseModel):
    id: str = Field(default_factory=lambda: new_id("exec"))
    proposal_id: str
    symbol: str
    side: Side
    qty: int
    limit_price: float
    mode: ExecutionMode = ExecutionMode.PAPER
    status: str = "RECORDED"
    created_at: datetime = Field(default_factory=utc_now)
    broker_order_id: str | None = None
    notes: str = "Paper execution recorded locally. No live order was submitted."


class AuditEvent(BaseModel):
    event_type: str
    entity_type: str
    entity_id: str
    payload: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utc_now)
