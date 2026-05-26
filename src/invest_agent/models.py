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


class CreatedVia(StrEnum):
    DASHBOARD = "dashboard"
    CLI = "cli"
    REST = "rest"
    MCP = "mcp"
    SYSTEM = "system"


class CreatedBy(StrEnum):
    HUMAN = "human"
    HERMES = "hermes"
    SCHEDULER = "scheduler"
    SYSTEM = "system"


class ThesisSide(StrEnum):
    LONG = "long"
    SHORT = "short"
    NEUTRAL_WATCH = "neutral_watch"


class ThesisStatus(StrEnum):
    ACTIVE = "active"
    WATCH = "watch"
    INVALIDATED = "invalidated"
    ARCHIVED = "archived"


class ThesisConviction(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class ThesisPillarStatus(StrEnum):
    ON_TRACK = "on_track"
    MIXED = "mixed"
    WEAKENING = "weakening"
    BROKEN = "broken"


class ThesisRiskStatus(StrEnum):
    OPEN = "open"
    TRIGGERED = "triggered"
    DISMISSED = "dismissed"


class ThesisImpact(StrEnum):
    STRENGTHENS = "strengthens"
    WEAKENS = "weakens"
    NEUTRAL = "neutral"
    INVALIDATES = "invalidates"


class ThesisActionBias(StrEnum):
    NO_CHANGE = "no_change"
    INCREASE = "increase"
    TRIM = "trim"
    EXIT = "exit"
    WATCH_ONLY = "watch_only"


class CatalystEventType(StrEnum):
    EARNINGS = "earnings"
    INVESTOR_DAY = "investor_day"
    ANALYST_DAY = "analyst_day"
    PRODUCT = "product"
    REGULATORY = "regulatory"
    CONFERENCE = "conference"
    MACRO = "macro"
    INDUSTRY_DATA = "industry_data"
    SHAREHOLDER_MEETING = "shareholder_meeting"
    OTHER = "other"


class CatalystTimeHint(StrEnum):
    PRE_MARKET = "pre_market"
    MARKET_HOURS = "market_hours"
    POST_MARKET = "post_market"
    UNKNOWN = "unknown"


class CatalystExpectedImpact(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class CatalystSourceType(StrEnum):
    SEC_EDGAR = "sec-edgar"
    COMPANY_IR = "company-ir"
    EXCHANGE_CALENDAR = "exchange-calendar"
    MACRO_CALENDAR = "macro-calendar"
    MANUAL = "manual"
    NEWS = "news"
    OTHER = "other"


class CatalystVerificationStatus(StrEnum):
    UNVERIFIED = "unverified"
    SOURCE_VERIFIED = "source_verified"
    HUMAN_VERIFIED = "human_verified"
    REJECTED = "rejected"


class CatalystStatus(StrEnum):
    UPCOMING = "upcoming"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    MISSED = "missed"


class CatalystThesisDelta(StrEnum):
    STRENGTHENS = "strengthens"
    WEAKENS = "weakens"
    NEUTRAL = "neutral"
    INVALIDATES = "invalidates"
    UNKNOWN = "unknown"


class CatalystActionBias(StrEnum):
    NO_CHANGE = "no_change"
    WATCH_ONLY = "watch_only"
    INCREASE = "increase"
    TRIM = "trim"
    EXIT = "exit"
    BLOCK_NEW_PROPOSAL = "block_new_proposal"


class CashflowQuality(StrEnum):
    HEALTHY = "healthy"
    MIXED = "mixed"
    WEAK = "weak"
    UNKNOWN = "unknown"


class GuidanceTone(StrEnum):
    POSITIVE = "positive"
    MIXED = "mixed"
    NEGATIVE = "negative"
    UNKNOWN = "unknown"


class RunCardType(StrEnum):
    EARNINGS_REVIEW = "earnings_review"
    CATALYST_REVIEW = "catalyst_review"
    EVENT_REPLAY = "event_replay"
    TRADE_JOURNAL_IMPORT = "trade_journal_import"
    BEHAVIOR_REPORT = "behavior_report"
    SAFE_AUTONOMY_CYCLE = "safe_autonomy_cycle"
    PROPOSAL_DRAFT = "proposal_draft"
    FUTURE_BACKTEST_IMPORT = "future_backtest_import"
    FUTURE_BEHAVIOR_REPORT = "future_behavior_report"


class RunCardStatus(StrEnum):
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class RunCardActor(StrEnum):
    SCHEDULER = "scheduler"
    CLI = "cli"
    DASHBOARD = "dashboard"
    MCP = "mcp"
    API = "api"
    SYSTEM = "system"


class RunCardTriggerSource(StrEnum):
    MANUAL = "manual"
    SCHEDULED = "scheduled"
    CATALYST_COMPLETED = "catalyst_completed"
    PROPOSAL_DRAFT = "proposal_draft"
    REPLAY = "replay"
    SMOKE = "smoke"
    SYSTEM = "system"


class TradeJournalSource(StrEnum):
    FUTU_CSV = "futu_csv"
    GENERIC_CSV = "generic_csv"


class TradeFillSide(StrEnum):
    BUY = "buy"
    SELL = "sell"


class BehaviorSeverity(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    UNKNOWN = "unknown"


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
    research_goal_id: str | None = None
    manual_override_reason: str | None = None
    thesis_id: str | None = None

    @field_validator("symbol")
    @classmethod
    def normalize_symbol(cls, value: str) -> str:
        return value.strip().upper()

    @field_validator("manual_override_reason")
    @classmethod
    def normalize_override_reason(cls, value: str | None) -> str | None:
        return value.strip() if value and value.strip() else None


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
    research_goal_id: str | None = None
    manual_override_reason: str | None = None
    evidence_hash: str = ""
    thesis_id: str | None = None

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
    source_verified: bool = False
    added_via: str = "system"
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    caveat: str = ""
    contradicts_claim_ids: list[str] = Field(default_factory=list)
    run_card_id: str | None = None

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
    source_verified: bool = False
    added_via: str = "local"
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    caveat: str = ""
    contradicts_claim_ids: list[str] = Field(default_factory=list)
    run_card_id: str | None = None

    @field_validator("symbol")
    @classmethod
    def normalize_evidence_symbol(cls, value: str | None) -> str | None:
        return value.strip().upper() if value else None


class ThesisPillarInput(BaseModel):
    text: str = Field(min_length=3)
    status: ThesisPillarStatus = ThesisPillarStatus.ON_TRACK


class ThesisRiskInput(BaseModel):
    text: str = Field(min_length=3)
    invalidation_condition: str = Field(min_length=3)
    status: ThesisRiskStatus = ThesisRiskStatus.OPEN


class ThesisPillar(BaseModel):
    id: str = Field(default_factory=lambda: new_id("pillar"))
    thesis_id: str = ""
    text: str
    status: ThesisPillarStatus = ThesisPillarStatus.ON_TRACK


class ThesisRisk(BaseModel):
    id: str = Field(default_factory=lambda: new_id("risk"))
    thesis_id: str = ""
    text: str
    invalidation_condition: str
    status: ThesisRiskStatus = ThesisRiskStatus.OPEN


class ThesisUpdate(BaseModel):
    id: str = Field(default_factory=lambda: new_id("thupd"))
    thesis_id: str
    research_goal_id: str | None = None
    evidence_hash: str = ""
    impact: ThesisImpact
    summary: str
    action_bias: ThesisActionBias = ThesisActionBias.NO_CHANGE
    created_at: datetime = Field(default_factory=utc_now)


class Thesis(BaseModel):
    id: str = Field(default_factory=lambda: new_id("thesis"))
    symbol: str
    side: ThesisSide = ThesisSide.LONG
    thesis_statement: str
    status: ThesisStatus = ThesisStatus.ACTIVE
    conviction: ThesisConviction = ThesisConviction.MEDIUM
    target_price: float | None = Field(default=None, gt=0)
    stop_loss_trigger: str = ""
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
    created_via: CreatedVia = CreatedVia.REST
    created_by: CreatedBy = CreatedBy.HUMAN
    human_confirmed: bool = True
    confirmed_at: datetime | None = Field(default_factory=utc_now)
    confirmed_by: str = "local-user"
    pillars: list[ThesisPillar] = Field(default_factory=list)
    risks: list[ThesisRisk] = Field(default_factory=list)
    updates: list[ThesisUpdate] = Field(default_factory=list)

    @field_validator("symbol")
    @classmethod
    def normalize_thesis_symbol(cls, value: str) -> str:
        return value.strip().upper()


class ThesisCreate(BaseModel):
    symbol: str
    side: ThesisSide = ThesisSide.LONG
    thesis_statement: str = Field(min_length=8)
    status: ThesisStatus = ThesisStatus.ACTIVE
    conviction: ThesisConviction = ThesisConviction.MEDIUM
    target_price: float | None = Field(default=None, gt=0)
    stop_loss_trigger: str = ""
    created_via: CreatedVia = CreatedVia.REST
    created_by: CreatedBy = CreatedBy.HUMAN
    human_confirmed: bool = True
    confirmed_by: str = "local-user"
    pillars: list[ThesisPillarInput] = Field(default_factory=list)
    risks: list[ThesisRiskInput] = Field(default_factory=list)

    @field_validator("symbol")
    @classmethod
    def normalize_create_thesis_symbol(cls, value: str) -> str:
        return value.strip().upper()


class ThesisUpdateCreate(BaseModel):
    research_goal_id: str | None = None
    evidence_hash: str | None = None
    impact: ThesisImpact
    summary: str = Field(min_length=3)
    action_bias: ThesisActionBias = ThesisActionBias.NO_CHANGE
    conviction: ThesisConviction | None = None


class Catalyst(BaseModel):
    id: str = Field(default_factory=lambda: new_id("cat"))
    symbol: str | None = None
    event_type: CatalystEventType = CatalystEventType.OTHER
    title: str = Field(min_length=3)
    description: str = ""
    event_date: datetime
    event_time_hint: CatalystTimeHint = CatalystTimeHint.UNKNOWN
    timezone: str = "America/New_York"
    expected_impact: CatalystExpectedImpact = CatalystExpectedImpact.MEDIUM
    source_uri: str | None = None
    source_type: CatalystSourceType = CatalystSourceType.MANUAL
    verification_status: CatalystVerificationStatus = CatalystVerificationStatus.UNVERIFIED
    source_verified: bool = False
    status: CatalystStatus = CatalystStatus.UPCOMING
    linked_thesis_id: str | None = None
    linked_research_goal_id: str | None = None
    actual_outcome_summary: str | None = None
    thesis_delta: CatalystThesisDelta = CatalystThesisDelta.UNKNOWN
    created_via: CreatedVia = CreatedVia.REST
    created_by: CreatedBy = CreatedBy.HUMAN
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)

    @field_validator("symbol")
    @classmethod
    def normalize_catalyst_symbol(cls, value: str | None) -> str | None:
        return value.strip().upper() if value else None


class CatalystCreate(BaseModel):
    symbol: str | None = None
    event_type: CatalystEventType = CatalystEventType.OTHER
    title: str = Field(min_length=3)
    description: str = ""
    event_date: datetime
    event_time_hint: CatalystTimeHint = CatalystTimeHint.UNKNOWN
    timezone: str = "America/New_York"
    expected_impact: CatalystExpectedImpact = CatalystExpectedImpact.MEDIUM
    source_uri: str | None = None
    source_type: CatalystSourceType = CatalystSourceType.MANUAL
    verification_status: CatalystVerificationStatus = CatalystVerificationStatus.UNVERIFIED
    source_verified: bool = False
    linked_thesis_id: str | None = None
    created_via: CreatedVia = CreatedVia.REST
    created_by: CreatedBy = CreatedBy.HUMAN

    @field_validator("symbol")
    @classmethod
    def normalize_create_catalyst_symbol(cls, value: str | None) -> str | None:
        return value.strip().upper() if value else None


class CatalystReview(BaseModel):
    id: str = Field(default_factory=lambda: new_id("catrev"))
    catalyst_id: str
    research_goal_id: str | None = None
    evidence_hash: str = ""
    actual_outcome_summary: str
    thesis_delta: CatalystThesisDelta = CatalystThesisDelta.UNKNOWN
    action_bias: CatalystActionBias = CatalystActionBias.NO_CHANGE
    run_card_id: str | None = None
    created_at: datetime = Field(default_factory=utc_now)


class CatalystReviewCreate(BaseModel):
    research_goal_id: str | None = None
    evidence_hash: str | None = None
    actual_outcome_summary: str = Field(min_length=3)
    thesis_delta: CatalystThesisDelta = CatalystThesisDelta.UNKNOWN
    action_bias: CatalystActionBias = CatalystActionBias.NO_CHANGE
    run_card_id: str | None = None


class CatalystCompleteRequest(BaseModel):
    actual_outcome_summary: str = Field(min_length=3)
    create_research_goal: bool = True


class EarningsReview(BaseModel):
    id: str = Field(default_factory=lambda: new_id("earn"))
    symbol: str
    period: str = "unknown"
    fiscal_year: int | None = None
    fiscal_quarter: str = ""
    release_date: datetime | None = None
    filing_date: datetime | None = None
    catalyst_id: str | None = None
    catalyst_review_id: str | None = None
    research_goal_id: str | None = None
    thesis_id: str | None = None
    revenue_yoy: float | None = None
    net_income_yoy: float | None = None
    operating_income_yoy: float | None = None
    operating_cash_flow_yoy: float | None = None
    diluted_eps_yoy: float | None = None
    cashflow_quality: CashflowQuality = CashflowQuality.UNKNOWN
    guidance_tone: GuidanceTone = GuidanceTone.UNKNOWN
    beat_miss_summary: str = ""
    source_summary: str = ""
    thesis_delta: CatalystThesisDelta = CatalystThesisDelta.UNKNOWN
    action_bias: CatalystActionBias = CatalystActionBias.NO_CHANGE
    evidence_hash: str = ""
    run_card_id: str | None = None
    score: int = 0
    warnings: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utc_now)

    @field_validator("symbol")
    @classmethod
    def normalize_earnings_review_symbol(cls, value: str) -> str:
        return value.strip().upper()


class EarningsReviewRunRequest(BaseModel):
    symbol: str
    catalyst_id: str | None = None
    research_goal_id: str | None = None
    thesis_id: str | None = None
    period: str | None = None
    refresh_fundamentals: bool = False

    @field_validator("symbol")
    @classmethod
    def normalize_earnings_run_symbol(cls, value: str) -> str:
        return value.strip().upper()


class EarningsReviewApplyRequest(BaseModel):
    thesis_id: str | None = None
    human_confirmed: bool = False


class ResearchRunCard(BaseModel):
    id: str = Field(default_factory=lambda: new_id("run"))
    schema_version: str = "run_card_v1"
    run_type: RunCardType
    status: RunCardStatus = RunCardStatus.RUNNING
    symbol: str | None = None
    title: str
    started_at: datetime = Field(default_factory=utc_now)
    completed_at: datetime | None = None
    duration_ms: int | None = None
    actor: RunCardActor = RunCardActor.SYSTEM
    trigger_source: RunCardTriggerSource = RunCardTriggerSource.SYSTEM
    code_version: str = "unknown"
    rule_version: str = ""
    input_hash: str = ""
    output_hash: str = ""
    dataset_hash: str = ""
    evidence_hash: str | None = None
    research_goal_id: str | None = None
    thesis_id: str | None = None
    catalyst_id: str | None = None
    catalyst_review_id: str | None = None
    earnings_review_id: str | None = None
    proposal_id: str | None = None
    metrics: dict[str, Any] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
    assumptions: dict[str, Any] = Field(default_factory=dict)
    outputs: dict[str, Any] = Field(default_factory=dict)
    artifacts: list[dict[str, Any]] = Field(default_factory=list)
    error: str = ""
    created_at: datetime = Field(default_factory=utc_now)

    @field_validator("symbol")
    @classmethod
    def normalize_run_card_symbol(cls, value: str | None) -> str | None:
        return value.strip().upper() if value else None


class TradeImport(BaseModel):
    id: str = Field(default_factory=lambda: new_id("imp"))
    source: TradeJournalSource = TradeJournalSource.GENERIC_CSV
    filename: str
    file_hash: str
    imported_at: datetime = Field(default_factory=utc_now)
    imported_by: RunCardActor = RunCardActor.CLI
    row_count: int = 0
    parse_warnings: list[str] = Field(default_factory=list)
    run_card_id: str | None = None


class TradeFill(BaseModel):
    id: str = Field(default_factory=lambda: new_id("fill"))
    import_id: str
    broker: str = "generic"
    broker_order_id: str | None = None
    broker_trade_id: str | None = None
    symbol: str
    broker_symbol: str | None = None
    side: TradeFillSide
    qty: float = Field(gt=0)
    price: float = Field(gt=0)
    fees: float = Field(default=0.0, ge=0.0)
    currency: str = "USD"
    market: str = ""
    traded_at: datetime
    raw_row_hash: str
    raw: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utc_now)

    @field_validator("symbol")
    @classmethod
    def normalize_trade_symbol(cls, value: str) -> str:
        return value.strip().upper()

    @field_validator("currency")
    @classmethod
    def normalize_currency(cls, value: str) -> str:
        return (value or "USD").strip().upper()

    @field_validator("market")
    @classmethod
    def normalize_market(cls, value: str) -> str:
        return (value or "").strip().upper()


class TradeRoundTrip(BaseModel):
    id: str = Field(default_factory=lambda: new_id("rt"))
    import_id: str | None = None
    symbol: str
    opened_at: datetime
    closed_at: datetime
    qty: float = Field(gt=0)
    buy_price: float = Field(gt=0)
    sell_price: float = Field(gt=0)
    buy_fees: float = Field(default=0.0, ge=0.0)
    sell_fees: float = Field(default=0.0, ge=0.0)
    holding_days: float = Field(default=0.0, ge=0.0)
    realized_pnl: float = 0.0
    realized_pnl_pct: float = 0.0
    currency: str = "USD"
    pairing_method: str = "fifo"
    created_at: datetime = Field(default_factory=utc_now)

    @field_validator("symbol")
    @classmethod
    def normalize_roundtrip_symbol(cls, value: str) -> str:
        return value.strip().upper()

    @field_validator("currency")
    @classmethod
    def normalize_roundtrip_currency(cls, value: str) -> str:
        return (value or "USD").strip().upper()


class BehaviorDiagnostic(BaseModel):
    severity: BehaviorSeverity = BehaviorSeverity.UNKNOWN
    score: float = 0.0
    summary: str = ""
    metrics: dict[str, Any] = Field(default_factory=dict)


class BehaviorReport(BaseModel):
    id: str = Field(default_factory=lambda: new_id("beh"))
    period_start: datetime | None = None
    period_end: datetime | None = None
    symbols: list[str] = Field(default_factory=list)
    total_trades: int = 0
    total_roundtrips: int = 0
    win_rate: float = 0.0
    profit_loss_ratio: float = 0.0
    avg_holding_days: float = 0.0
    trade_frequency_per_week: float = 0.0
    total_realized_pnl: float = 0.0
    max_drawdown: float = 0.0
    top_symbols: dict[str, int] = Field(default_factory=dict)
    hourly_distribution: dict[str, int] = Field(default_factory=dict)
    market_distribution: dict[str, int] = Field(default_factory=dict)
    diagnostics: dict[str, BehaviorDiagnostic] = Field(default_factory=dict)
    run_card_id: str | None = None
    created_at: datetime = Field(default_factory=utc_now)

    @field_validator("symbols")
    @classmethod
    def normalize_report_symbols(cls, value: list[str]) -> list[str]:
        return [item.strip().upper() for item in value if item and item.strip()]


class TradeJournalImportRequest(BaseModel):
    path: str
    source: TradeJournalSource = TradeJournalSource.FUTU_CSV


class BehaviorReportRunRequest(BaseModel):
    period_start: datetime | None = None
    period_end: datetime | None = None
    symbols: list[str] | None = None

    @field_validator("symbols")
    @classmethod
    def normalize_run_symbols(cls, value: list[str] | None) -> list[str] | None:
        if not value:
            return None
        return [item.strip().upper() for item in value if item and item.strip()]


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
    thesis_id: str | None = None


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
    run_card_id: str | None = None


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
