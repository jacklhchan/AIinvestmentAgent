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


class ResearchGoalStatus(StrEnum):
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    INSUFFICIENT = "INSUFFICIENT"
    REJECTED = "REJECTED"


class ResearchClaimStatus(StrEnum):
    OPEN = "OPEN"
    SUPPORTED = "SUPPORTED"
    CONTRADICTED = "CONTRADICTED"
    NEUTRAL = "NEUTRAL"


class ResearchCriterionStatus(StrEnum):
    PENDING = "PENDING"
    SATISFIED = "SATISFIED"
    INSUFFICIENT = "INSUFFICIENT"
    WAIVED = "WAIVED"


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


class ResearchClaim(BaseModel):
    id: str = Field(default_factory=lambda: new_id("claim"))
    goal_id: str = ""
    claim_type: str = "thesis"
    text: str
    status: ResearchClaimStatus = ResearchClaimStatus.OPEN


class ResearchCriterion(BaseModel):
    id: str = Field(default_factory=lambda: new_id("crit"))
    goal_id: str = ""
    text: str
    required: bool = True
    freshness_requirement: str = ""
    status: ResearchCriterionStatus = ResearchCriterionStatus.PENDING


class ResearchEvidence(BaseModel):
    id: str = Field(default_factory=lambda: new_id("evid"))
    goal_id: str
    symbol: str | None = None
    source_type: str
    source_uri: str | None = None
    text: str
    data_as_of: datetime | None = None
    retrieved_at: datetime = Field(default_factory=utc_now)
    freshness_status: str = "unknown"
    verification_status: str = "unverified"
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    caveat: str = ""
    contradicts_claim_ids: list[str] = Field(default_factory=list)

    @field_validator("symbol")
    @classmethod
    def normalize_optional_symbol(cls, value: str | None) -> str | None:
        return value.strip().upper() if value else None


class ResearchGoal(BaseModel):
    id: str = Field(default_factory=lambda: new_id("goal"))
    symbol: str | None = None
    objective: str
    protocol: str = "evidence-ledger-v1"
    risk_tier: str = "research-only"
    status: ResearchGoalStatus = ResearchGoalStatus.ACTIVE
    token_budget: int | None = Field(default=None, gt=0)
    turn_budget: int | None = Field(default=None, gt=0)
    created_at: datetime = Field(default_factory=utc_now)
    completed_at: datetime | None = None
    claims: list[ResearchClaim] = Field(default_factory=list)
    criteria: list[ResearchCriterion] = Field(default_factory=list)
    evidence: list[ResearchEvidence] = Field(default_factory=list)
    evidence_count: int = 0
    summary: str = ""

    @field_validator("symbol")
    @classmethod
    def normalize_goal_symbol(cls, value: str | None) -> str | None:
        return value.strip().upper() if value else None


class ResearchGoalCreate(BaseModel):
    symbol: str | None = None
    objective: str = Field(min_length=8)
    protocol: str = "evidence-ledger-v1"
    risk_tier: str = "research-only"
    token_budget: int | None = Field(default=None, gt=0)
    turn_budget: int | None = Field(default=None, gt=0)
    claims: list[str] = Field(default_factory=list)
    criteria: list[str] = Field(default_factory=list)

    @field_validator("symbol")
    @classmethod
    def normalize_create_symbol(cls, value: str | None) -> str | None:
        return value.strip().upper() if value else None


class ResearchEvidenceCreate(BaseModel):
    goal_id: str
    symbol: str | None = None
    source_type: str = Field(min_length=2)
    source_uri: str | None = None
    text: str = Field(min_length=3)
    data_as_of: datetime | None = None
    freshness_status: str = "unknown"
    verification_status: str = "unverified"
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    caveat: str = ""
    contradicts_claim_ids: list[str] = Field(default_factory=list)

    @field_validator("symbol")
    @classmethod
    def normalize_evidence_symbol(cls, value: str | None) -> str | None:
        return value.strip().upper() if value else None


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
    research_goal_id: str | None = None
    evidence_gate_passed: bool = False
    evidence_gate_reasons: list[str] = Field(default_factory=list)
    research_evidence_count: int = 0


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
