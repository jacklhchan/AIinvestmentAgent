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
    MARKET_REGIME = "market_regime"
    HYPOTHESIS_REVIEW = "hypothesis_review"
    PORTFOLIO_RISK = "portfolio_risk"
    REBALANCE_REVIEW = "rebalance_review"
    EARNINGS_PREVIEW = "earnings_preview"
    QUOTE_HISTORY_IMPORT = "quote_history_import"
    EXTERNAL_BACKTEST_IMPORT = "external_backtest_import"
    DATA_IMPORT = "data_import"
    DAILY_BRIEF = "daily_brief"
    CORRELATION_SNAPSHOT = "correlation_snapshot"
    SECTOR_SNAPSHOT = "sector_snapshot"
    OPTIONS_SNAPSHOT = "options_snapshot"
    DIVIDEND_REVIEW = "dividend_review"
    IDEA_SCREEN = "idea_screen"
    COMMITTEE_REVIEW = "committee_review"
    SKILL_VALIDATION = "skill_validation"
    DATA_QUALITY_REPORT = "data_quality_report"
    TRADE_JOURNAL_IMPORT = "trade_journal_import"
    BEHAVIOR_REPORT = "behavior_report"
    SHADOW_STRATEGY_EXTRACT = "shadow_strategy_extract"
    SHADOW_REPORT = "shadow_report"
    SAFE_AUTONOMY_CYCLE = "safe_autonomy_cycle"
    PROPOSAL_DRAFT = "proposal_draft"
    SIGNAL_RUN = "signal_run"
    ADVISOR_QUESTION = "advisor_question"
    ADVISOR_PULSE = "advisor_pulse"
    ADVISOR_BRIEF = "advisor_brief"
    OPPORTUNITY_RADAR = "opportunity_radar"
    ACCOUNTING_REBUILD = "accounting_rebuild"
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


class ShadowStrategyStatus(StrEnum):
    DRAFT = "draft"
    ACTIVE = "active"
    ARCHIVED = "archived"


class ShadowRuleType(StrEnum):
    ENTRY = "entry"
    EXIT = "exit"
    SIZING = "sizing"
    COOLDOWN = "cooldown"
    CATALYST = "catalyst"
    THESIS = "thesis"
    STOP_LOSS = "stop_loss"
    TAKE_PROFIT = "take_profit"


class ShadowEventType(StrEnum):
    RULE_FOLLOWED = "rule_followed"
    RULE_VIOLATION = "rule_violation"
    EARLY_EXIT = "early_exit"
    LATE_EXIT = "late_exit"
    MISSED_ENTRY = "missed_entry"
    OVERSIZED_TRADE = "oversized_trade"
    IGNORED_CATALYST = "ignored_catalyst"
    THESIS_MISMATCH = "thesis_mismatch"
    POST_EVENT_REVIEW_MISSING = "post_event_review_missing"
    CONTRADICTED_EARNINGS_REVIEW = "contradicted_earnings_review"


class AdvisorSeverity(StrEnum):
    INFO = "info"
    WATCH = "watch"
    ACTION = "action"
    BLOCKED = "blocked"


class AdvisorConfidence(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class AdvisorPulseSeverity(StrEnum):
    SILENT = "silent"
    INFO = "info"
    WATCH = "watch"
    URGENT = "urgent"


class AdvisorSourceType(StrEnum):
    QUESTION = "question"
    PULSE = "pulse"
    BRIEF = "brief"


class SymbolResolutionStatus(StrEnum):
    RESOLVED = "resolved"
    UNKNOWN = "unknown"
    PRIVATE_COMPANY = "private_company"
    PORTFOLIO_SCOPE = "portfolio_scope"
    NO_SYMBOL = "no_symbol"


class AdvisorRiskProfile(StrEnum):
    CONSERVATIVE = "conservative"
    MODERATE_CONSERVATIVE = "moderate_conservative"
    MODERATE = "moderate"
    GROWTH = "growth"
    AGGRESSIVE = "aggressive"


class AdvisorProfileUpdateStatus(StrEnum):
    PENDING = "pending"
    CONFIRMED = "confirmed"
    REJECTED = "rejected"


class AccountingTransactionType(StrEnum):
    BUY = "buy"
    SELL = "sell"
    DIVIDEND = "dividend"
    FEE = "fee"
    TAX_WITHHOLDING = "tax_withholding"
    CASH_DEPOSIT = "cash_deposit"
    CASH_WITHDRAWAL = "cash_withdrawal"
    INTEREST = "interest"
    TRANSFER_IN = "transfer_in"
    TRANSFER_OUT = "transfer_out"
    CORPORATE_ACTION = "corporate_action"
    SPLIT = "split"


class TaxLotStatus(StrEnum):
    OPEN = "open"
    CLOSED = "closed"


class OpportunityRecommendationType(StrEnum):
    WATCH = "watch"
    RESEARCH = "research"
    BLOCKED = "blocked"
    AVOID = "avoid"
    ACTION_CANDIDATE = "action_candidate"


class SignalSide(StrEnum):
    BUY_SIGNAL = "BUY_SIGNAL"
    SELL_SIGNAL = "SELL_SIGNAL"
    ADD_SIGNAL = "ADD_SIGNAL"
    REDUCE_SIGNAL = "REDUCE_SIGNAL"
    HOLD = "HOLD"
    WATCH = "WATCH"
    BLOCKED = "BLOCKED"
    AVOID = "AVOID"


class SignalHorizon(StrEnum):
    INTRADAY = "intraday"
    SWING = "swing"
    POSITION = "position"
    LONG_TERM = "long_term"


class SignalStrength(StrEnum):
    WEAK = "weak"
    MEDIUM = "medium"
    STRONG = "strong"


class SignalStatus(StrEnum):
    ACTIVE = "active"
    EXPIRED = "expired"
    PROMOTED = "promoted"
    REJECTED = "rejected"
    INVALIDATED = "invalidated"


class SignalSource(StrEnum):
    AUTONOMY = "autonomy"
    DASHBOARD = "dashboard"
    CLI = "cli"
    API = "api"
    MANUAL_RUN = "manual_run"


class OpportunityCategory(StrEnum):
    CORE_ETF = "core_etf"
    SECTOR_ROTATION = "sector_rotation"
    THEME = "theme"
    SINGLE_STOCK = "single_stock"
    DEFENSIVE = "defensive"
    CASH_LIKE = "cash_like"
    AVOID = "avoid"


class AdvisorFullBriefType(StrEnum):
    PRE_MARKET = "pre_market"
    POST_CLOSE = "post_close"


class RiskAppetite(StrEnum):
    RISK_ON = "risk_on"
    NEUTRAL = "neutral"
    RISK_OFF = "risk_off"


class GrowthPressure(StrEnum):
    SUPPORTIVE = "supportive"
    MIXED = "mixed"
    PRESSURED = "pressured"


class RatesPressure(StrEnum):
    FALLING_YIELDS = "falling_yields"
    NEUTRAL = "neutral"
    RISING_YIELDS = "rising_yields"


class VolatilityRegime(StrEnum):
    CALM = "calm"
    ELEVATED = "elevated"
    STRESSED = "stressed"


class InflationPressure(StrEnum):
    BENIGN = "benign"
    MIXED = "mixed"
    OIL_GOLD_PRESSURE = "oil_gold_pressure"


class ProposalBias(StrEnum):
    NORMAL = "normal"
    CAUTION = "caution"
    DEFENSIVE_ONLY = "defensive_only"


class HypothesisScope(StrEnum):
    SYMBOL = "symbol"
    SECTOR = "sector"
    PORTFOLIO = "portfolio"
    MACRO = "macro"
    BEHAVIOR = "behavior"
    STRATEGY = "strategy"


class HypothesisStatus(StrEnum):
    DRAFT = "draft"
    TESTING = "testing"
    SUPPORTED = "supported"
    WEAKENED = "weakened"
    REJECTED = "rejected"
    ARCHIVED = "archived"


class HypothesisLinkType(StrEnum):
    RUN_CARD = "run_card"
    RESEARCH_GOAL = "research_goal"
    THESIS = "thesis"
    CATALYST = "catalyst"
    EARNINGS_REVIEW = "earnings_review"
    BEHAVIOR_REPORT = "behavior_report"
    SHADOW_REPORT = "shadow_report"
    MARKET_REGIME = "market_regime"


class PortfolioActionBias(StrEnum):
    NO_CHANGE = "no_change"
    WATCH_ONLY = "watch_only"
    RESEARCH_NEEDED = "research_needed"
    CANDIDATE_REVIEW = "candidate_review"


class RebalanceAction(StrEnum):
    BUY = "buy"
    SELL = "sell"
    TRIM = "trim"
    ADD = "add"
    HOLD = "hold"


class RebalanceCandidateStatus(StrEnum):
    CANDIDATE = "candidate"
    RESEARCHING = "researching"
    REJECTED = "rejected"
    PROMOTED_TO_RESEARCH_GOAL = "promoted_to_research_goal"


class QuoteHistorySource(StrEnum):
    FUTU_HISTORY_KLINE = "futu_history_kline"
    MANUAL_CSV = "manual_csv"
    FUTURE_IMPORT = "future_import"


class PriceBarConfidence(StrEnum):
    EXACT_BAR = "exact_bar"
    NEXT_AVAILABLE_BAR = "next_available_bar"
    PREVIOUS_AVAILABLE_BAR = "previous_available_bar"
    UNAVAILABLE = "unavailable"


class ExternalBacktestSource(StrEnum):
    VIBE_TRADING = "vibe_trading"
    MANUAL = "manual"
    OTHER = "other"


class ExternalBacktestValidationStatus(StrEnum):
    IMPORTED = "imported"
    VALIDATED = "validated"
    REJECTED = "rejected"


class DailyBriefType(StrEnum):
    MORNING = "morning"
    CLOSE = "close"
    WEEKLY = "weekly"


class IdeaDirection(StrEnum):
    LONG = "long"
    SHORT = "short"
    NEUTRAL_WATCH = "neutral_watch"


class IdeaCandidateStatus(StrEnum):
    INBOX = "inbox"
    RESEARCHING = "researching"
    REJECTED = "rejected"
    PROMOTED_TO_THESIS = "promoted_to_thesis"


class CommitteeConclusion(StrEnum):
    RESEARCH_MORE = "research_more"
    ELIGIBLE_FOR_PROPOSAL = "eligible_for_proposal"
    REJECT = "reject"
    WATCH_ONLY = "watch_only"
    INFO_ONLY = "info_only"
    WATCH = "watch"
    RESEARCH_NEEDED = "research_needed"
    ELIGIBLE_FOR_PROPOSAL_REVIEW = "eligible_for_proposal_review"
    BLOCKED = "blocked"


class CommitteeReviewType(StrEnum):
    INVESTMENT_COMMITTEE = "investment_committee"
    RISK_COMMITTEE = "risk_committee"
    MACRO_COMMITTEE = "macro_committee"
    EARNINGS_COMMITTEE = "earnings_committee"


class CommitteeReviewStatus(StrEnum):
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class CommitteeMemberRole(StrEnum):
    BULL_ANALYST = "bull_analyst"
    BEAR_ANALYST = "bear_analyst"
    RISK_MANAGER = "risk_manager"
    PORTFOLIO_MANAGER = "portfolio_manager"
    EVIDENCE_AUDITOR = "evidence_auditor"
    EXECUTION_SKEPTIC = "execution_skeptic"


class CommitteeFindingType(StrEnum):
    BULL_CASE = "bull_case"
    BEAR_CASE = "bear_case"
    RISK = "risk"
    MISSING_EVIDENCE = "missing_evidence"
    PORTFOLIO_FIT = "portfolio_fit"
    ENTRY_QUALITY = "entry_quality"
    BEHAVIOR_WARNING = "behavior_warning"


class CommitteeFindingSeverity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    BLOCKING = "blocking"


class DataQualityTargetType(StrEnum):
    FUNDAMENTALS = "fundamentals"
    PRICE_BARS = "price_bars"
    TRADE_JOURNAL = "trade_journal"
    CATALYSTS = "catalysts"
    EARNINGS_REVIEW = "earnings_review"
    RUN_CARDS = "run_cards"
    ALL = "all"


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
    previous_close: float | None = None
    change_pct: float | None = None
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


class MarketContextItem(BaseModel):
    symbol: str
    role: str
    label: str
    has_quote: bool = False
    last_price: float | None = None
    previous_close: float | None = None
    change_pct: float | None = None
    quote_source: str | None = None
    quote_updated_at: datetime | None = None
    news_count: int = 0
    latest_news_title: str | None = None
    latest_news_source: str | None = None
    latest_news_at: datetime | None = None


class MarketContextSnapshot(BaseModel):
    generated_at: datetime = Field(default_factory=utc_now)
    symbols: list[str] = Field(default_factory=list)
    items: list[MarketContextItem] = Field(default_factory=list)
    coverage_summary: dict[str, Any] = Field(default_factory=dict)
    risk_notes: list[str] = Field(default_factory=list)


class MarketRegimeSnapshot(BaseModel):
    id: str = Field(default_factory=lambda: new_id("regime"))
    created_at: datetime = Field(default_factory=utc_now)
    symbols: list[str] = Field(default_factory=list)
    quote_coverage: int = 0
    news_coverage: int = 0
    risk_appetite: RiskAppetite = RiskAppetite.NEUTRAL
    growth_pressure: GrowthPressure = GrowthPressure.MIXED
    rates_pressure: RatesPressure = RatesPressure.NEUTRAL
    volatility_regime: VolatilityRegime = VolatilityRegime.ELEVATED
    inflation_pressure: InflationPressure = InflationPressure.MIXED
    proposal_bias: ProposalBias = ProposalBias.CAUTION
    summary: str = ""
    warnings: list[str] = Field(default_factory=list)
    drivers: list[str] = Field(default_factory=list)
    metrics: dict[str, Any] = Field(default_factory=dict)
    input_hash: str = ""
    run_card_id: str | None = None


class HypothesisLink(BaseModel):
    id: str = Field(default_factory=lambda: new_id("hyplink"))
    hypothesis_id: str
    linked_type: HypothesisLinkType
    linked_id: str
    evidence_hash: str = ""
    created_at: datetime = Field(default_factory=utc_now)


class ResearchHypothesis(BaseModel):
    id: str = Field(default_factory=lambda: new_id("hyp"))
    title: str = Field(min_length=3)
    statement: str = Field(min_length=8)
    scope: HypothesisScope = HypothesisScope.SYMBOL
    symbols: list[str] = Field(default_factory=list)
    status: HypothesisStatus = HypothesisStatus.DRAFT
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    created_via: CreatedVia = CreatedVia.REST
    created_by: CreatedBy = CreatedBy.HUMAN
    human_confirmed: bool = False
    invalidation_note: str = ""
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
    links: list[HypothesisLink] = Field(default_factory=list)

    @field_validator("symbols")
    @classmethod
    def normalize_hypothesis_symbols(cls, value: list[str]) -> list[str]:
        return [item.strip().upper() for item in value if item and item.strip()]


class HypothesisCreate(BaseModel):
    title: str = Field(min_length=3)
    statement: str = Field(min_length=8)
    scope: HypothesisScope = HypothesisScope.SYMBOL
    symbols: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    created_via: CreatedVia = CreatedVia.REST
    created_by: CreatedBy = CreatedBy.HUMAN
    human_confirmed: bool = False

    @field_validator("symbols")
    @classmethod
    def normalize_create_hypothesis_symbols(cls, value: list[str]) -> list[str]:
        return [item.strip().upper() for item in value if item and item.strip()]


class HypothesisLinkCreate(BaseModel):
    linked_type: HypothesisLinkType
    linked_id: str
    evidence_hash: str = ""


class HypothesisInvalidateRequest(BaseModel):
    invalidation_note: str = Field(min_length=3)


class PortfolioTarget(BaseModel):
    id: str = Field(default_factory=lambda: new_id("ptgt"))
    asset_class: str
    target_weight: float = Field(ge=0.0, le=1.0)
    min_weight: float = Field(default=0.0, ge=0.0, le=1.0)
    max_weight: float = Field(default=1.0, ge=0.0, le=1.0)
    created_at: datetime = Field(default_factory=utc_now)


class SymbolClassification(BaseModel):
    symbol: str
    asset_class: str = "equity"
    sector: str = "unknown"
    region: str = "US"
    style: str = "unknown"
    risk_bucket: str = "medium"
    updated_at: datetime = Field(default_factory=utc_now)

    @field_validator("symbol")
    @classmethod
    def normalize_classification_symbol(cls, value: str) -> str:
        return value.strip().upper()


class PortfolioRiskSnapshot(BaseModel):
    id: str = Field(default_factory=lambda: new_id("prisk"))
    as_of: datetime = Field(default_factory=utc_now)
    total_value: float = 0.0
    cash_weight: float = 0.0
    top_5_weight: float = 0.0
    sector_exposure: dict[str, float] = Field(default_factory=dict)
    asset_class_exposure: dict[str, float] = Field(default_factory=dict)
    concentration_warnings: list[str] = Field(default_factory=list)
    drift: dict[str, Any] = Field(default_factory=dict)
    regime_context: dict[str, Any] = Field(default_factory=dict)
    run_card_id: str | None = None


class RebalanceCandidate(BaseModel):
    id: str = Field(default_factory=lambda: new_id("rbcand"))
    review_id: str
    symbol: str
    action: RebalanceAction = RebalanceAction.HOLD
    reason: str
    status: RebalanceCandidateStatus = RebalanceCandidateStatus.CANDIDATE
    linked_research_goal_id: str | None = None

    @field_validator("symbol")
    @classmethod
    def normalize_rebalance_symbol(cls, value: str) -> str:
        return value.strip().upper()


class RebalanceReview(BaseModel):
    id: str = Field(default_factory=lambda: new_id("rbrev"))
    as_of: datetime = Field(default_factory=utc_now)
    portfolio_value: float = 0.0
    drift_summary: dict[str, Any] = Field(default_factory=dict)
    risk_notes: list[str] = Field(default_factory=list)
    action_bias: PortfolioActionBias = PortfolioActionBias.NO_CHANGE
    run_card_id: str | None = None
    candidates: list[RebalanceCandidate] = Field(default_factory=list)


class EarningsPreview(BaseModel):
    id: str = Field(default_factory=lambda: new_id("eprev"))
    symbol: str
    catalyst_id: str | None = None
    thesis_id: str | None = None
    period: str = "unknown"
    earnings_date: datetime | None = None
    source_summary: str = ""
    key_metrics: dict[str, Any] = Field(default_factory=dict)
    bull_case: dict[str, Any] = Field(default_factory=dict)
    base_case: dict[str, Any] = Field(default_factory=dict)
    bear_case: dict[str, Any] = Field(default_factory=dict)
    implied_move_pct: float | None = None
    what_to_watch: list[str] = Field(default_factory=list)
    evidence_hash: str = ""
    run_card_id: str | None = None
    created_at: datetime = Field(default_factory=utc_now)

    @field_validator("symbol")
    @classmethod
    def normalize_earnings_preview_symbol(cls, value: str) -> str:
        return value.strip().upper()


class EarningsPreviewRunRequest(BaseModel):
    symbol: str
    catalyst_id: str | None = None
    thesis_id: str | None = None
    period: str | None = None
    implied_move_pct: float | None = None

    @field_validator("symbol")
    @classmethod
    def normalize_earnings_preview_run_symbol(cls, value: str) -> str:
        return value.strip().upper()


class QuoteHistoryImport(BaseModel):
    id: str = Field(default_factory=lambda: new_id("qhimp"))
    source: QuoteHistorySource = QuoteHistorySource.MANUAL_CSV
    symbol: str
    broker_symbol: str | None = None
    start_date: datetime | None = None
    end_date: datetime | None = None
    ktype: str = "K_DAY"
    autype: str = "qfq"
    row_count: int = 0
    input_hash: str = ""
    dataset_hash: str = ""
    run_card_id: str | None = None
    imported_at: datetime = Field(default_factory=utc_now)

    @field_validator("symbol")
    @classmethod
    def normalize_quote_history_symbol(cls, value: str) -> str:
        return value.strip().upper()


class PriceBar(BaseModel):
    id: str = Field(default_factory=lambda: new_id("bar"))
    import_id: str
    symbol: str
    broker_symbol: str | None = None
    ts: datetime
    timezone: str = "America/New_York"
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0
    turnover: float | None = None
    ktype: str = "K_DAY"
    autype: str = "qfq"
    source: QuoteHistorySource = QuoteHistorySource.MANUAL_CSV
    raw: dict[str, Any] = Field(default_factory=dict)
    row_hash: str = ""

    @field_validator("symbol")
    @classmethod
    def normalize_price_bar_symbol(cls, value: str) -> str:
        return value.strip().upper()


class QuoteHistoryRefreshRequest(BaseModel):
    symbol: str
    path: str | None = None
    days: int = Field(default=365, gt=0, le=5000)
    ktype: str = "K_DAY"
    autype: str = "qfq"

    @field_validator("symbol")
    @classmethod
    def normalize_quote_refresh_symbol(cls, value: str) -> str:
        return value.strip().upper()


class ExternalBacktestImport(BaseModel):
    id: str = Field(default_factory=lambda: new_id("btimp"))
    source: ExternalBacktestSource = ExternalBacktestSource.MANUAL
    imported_run_card_path: str
    run_card_hash: str
    strategy_name: str = ""
    universe: list[str] = Field(default_factory=list)
    period_start: str | None = None
    period_end: str | None = None
    metrics: dict[str, Any] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
    validation_status: ExternalBacktestValidationStatus = ExternalBacktestValidationStatus.IMPORTED
    linked_hypothesis_id: str | None = None
    linked_research_goal_id: str | None = None
    file_hash: str = ""
    created_at: datetime = Field(default_factory=utc_now)


class BacktestImportRequest(BaseModel):
    path: str
    source: ExternalBacktestSource = ExternalBacktestSource.MANUAL
    linked_hypothesis_id: str | None = None
    linked_research_goal_id: str | None = None


class DataSchema(BaseModel):
    id: str = Field(default_factory=lambda: new_id("dschema"))
    name: str
    version: str = "v1"
    required_columns: list[str] = Field(default_factory=list)
    optional_columns: list[str] = Field(default_factory=list)
    canonical_mapping: dict[str, str] = Field(default_factory=dict)
    validation_rules: dict[str, Any] = Field(default_factory=dict)


class DataImport(BaseModel):
    id: str = Field(default_factory=lambda: new_id("dimp"))
    source_name: str
    file_hash: str
    file_type: str
    schema_name: str
    schema_version: str = "v1"
    row_count: int = 0
    dataset_hash: str = ""
    validation_warnings: list[str] = Field(default_factory=list)
    run_card_id: str | None = None
    imported_at: datetime = Field(default_factory=utc_now)


class DataImportRequest(BaseModel):
    schema_name: str
    path: str
    source_name: str = "local"


class DailyBrief(BaseModel):
    id: str = Field(default_factory=lambda: new_id("brief"))
    date: str
    brief_type: DailyBriefType = DailyBriefType.MORNING
    market_regime_snapshot_id: str | None = None
    advisor_brief_hash: str = ""
    blocked_items: list[dict[str, Any]] = Field(default_factory=list)
    action_items: list[dict[str, Any]] = Field(default_factory=list)
    watch_items: list[dict[str, Any]] = Field(default_factory=list)
    info_items: list[dict[str, Any]] = Field(default_factory=list)
    delivered_to: str | None = None
    delivered_at: datetime | None = None
    run_card_id: str | None = None
    created_at: datetime = Field(default_factory=utc_now)


class DailyBriefRunRequest(BaseModel):
    brief_type: DailyBriefType = DailyBriefType.MORNING
    delivered_to: str | None = None


class PeerGroup(BaseModel):
    id: str = Field(default_factory=lambda: new_id("peer"))
    name: str = Field(min_length=2)
    sector: str = "unknown"
    symbols: list[str] = Field(default_factory=list)
    theme: str = ""
    created_at: datetime = Field(default_factory=utc_now)

    @field_validator("symbols")
    @classmethod
    def normalize_peer_symbols(cls, value: list[str]) -> list[str]:
        return [item.strip().upper() for item in value if item and item.strip()]


class PeerGroupCreate(BaseModel):
    name: str = Field(min_length=2)
    sector: str = "unknown"
    symbols: list[str] = Field(default_factory=list)
    theme: str = ""

    @field_validator("symbols")
    @classmethod
    def normalize_peer_create_symbols(cls, value: list[str]) -> list[str]:
        return [item.strip().upper() for item in value if item and item.strip()]


class CorrelationSnapshot(BaseModel):
    id: str = Field(default_factory=lambda: new_id("corr"))
    symbols: list[str] = Field(default_factory=list)
    lookback_days: int = 90
    correlation_matrix: dict[str, dict[str, float]] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
    run_card_id: str | None = None
    created_at: datetime = Field(default_factory=utc_now)


class CorrelationRunRequest(BaseModel):
    symbols: list[str] = Field(default_factory=list)
    lookback_days: int = Field(default=90, gt=1, le=2000)

    @field_validator("symbols")
    @classmethod
    def normalize_corr_symbols(cls, value: list[str]) -> list[str]:
        return [item.strip().upper() for item in value if item and item.strip()]


class SectorSnapshot(BaseModel):
    id: str = Field(default_factory=lambda: new_id("sector"))
    sector: str
    leaders: list[str] = Field(default_factory=list)
    laggards: list[str] = Field(default_factory=list)
    valuation_context: dict[str, Any] = Field(default_factory=dict)
    risk_notes: list[str] = Field(default_factory=list)
    source_summary: str = ""
    run_card_id: str | None = None
    created_at: datetime = Field(default_factory=utc_now)


class SectorSnapshotRunRequest(BaseModel):
    sector: str
    symbols: list[str] = Field(default_factory=list)

    @field_validator("symbols")
    @classmethod
    def normalize_sector_symbols(cls, value: list[str]) -> list[str]:
        return [item.strip().upper() for item in value if item and item.strip()]


class OptionsSnapshot(BaseModel):
    id: str = Field(default_factory=lambda: new_id("opt"))
    symbol: str
    expiry: str
    atm_iv: float | None = None
    implied_move_pct: float | None = None
    put_call_ratio: float | None = None
    skew: float | None = None
    source: str = "manual"
    source_uri: str | None = None
    run_card_id: str | None = None
    created_at: datetime = Field(default_factory=utc_now)

    @field_validator("symbol")
    @classmethod
    def normalize_options_symbol(cls, value: str) -> str:
        return value.strip().upper()


class OptionsSnapshotCreate(BaseModel):
    symbol: str
    expiry: str
    atm_iv: float | None = None
    implied_move_pct: float | None = None
    put_call_ratio: float | None = None
    skew: float | None = None
    source: str = "manual"
    source_uri: str | None = None

    @field_validator("symbol")
    @classmethod
    def normalize_options_create_symbol(cls, value: str) -> str:
        return value.strip().upper()


class DividendReview(BaseModel):
    id: str = Field(default_factory=lambda: new_id("div"))
    symbol: str
    dividend_yield: float | None = None
    payout_ratio: float | None = None
    dividend_growth_3y: float | None = None
    fcf_coverage: float | None = None
    buyback_yield: float | None = None
    shareholder_yield: float | None = None
    yield_trap_warning: str = ""
    ex_dividend_date: str | None = None
    source_summary: str = ""
    evidence_hash: str = ""
    run_card_id: str | None = None
    created_at: datetime = Field(default_factory=utc_now)

    @field_validator("symbol")
    @classmethod
    def normalize_dividend_symbol(cls, value: str) -> str:
        return value.strip().upper()


class DividendReviewRunRequest(BaseModel):
    symbol: str
    dividend_yield: float | None = None
    payout_ratio: float | None = None
    dividend_growth_3y: float | None = None
    fcf_coverage: float | None = None
    buyback_yield: float | None = None
    ex_dividend_date: str | None = None
    thesis_id: str | None = None

    @field_validator("symbol")
    @classmethod
    def normalize_dividend_run_symbol(cls, value: str) -> str:
        return value.strip().upper()


class IdeaScreen(BaseModel):
    id: str = Field(default_factory=lambda: new_id("screen"))
    screen_type: str = "manual"
    criteria: dict[str, Any] = Field(default_factory=dict)
    universe: str = "watchlist"
    source_summary: str = ""
    run_card_id: str | None = None
    created_at: datetime = Field(default_factory=utc_now)


class IdeaCandidate(BaseModel):
    id: str = Field(default_factory=lambda: new_id("idea"))
    screen_id: str | None = None
    symbol: str
    direction: IdeaDirection = IdeaDirection.NEUTRAL_WATCH
    one_line_thesis: str
    score: float = 0.0
    risks: list[str] = Field(default_factory=list)
    next_research_step: str = ""
    status: IdeaCandidateStatus = IdeaCandidateStatus.INBOX
    linked_research_goal_id: str | None = None
    linked_thesis_id: str | None = None
    created_at: datetime = Field(default_factory=utc_now)

    @field_validator("symbol")
    @classmethod
    def normalize_idea_symbol(cls, value: str) -> str:
        return value.strip().upper()


class IdeaScreenRunRequest(BaseModel):
    screen_type: str = "manual"
    criteria: dict[str, Any] = Field(default_factory=dict)
    universe: str = "watchlist"
    symbols: list[str] = Field(default_factory=list)

    @field_validator("symbols")
    @classmethod
    def normalize_idea_symbols(cls, value: list[str]) -> list[str]:
        return [item.strip().upper() for item in value if item and item.strip()]


class IdeaCandidateCreate(BaseModel):
    symbol: str
    direction: IdeaDirection = IdeaDirection.NEUTRAL_WATCH
    one_line_thesis: str = Field(min_length=5)
    score: float = 0.0
    risks: list[str] = Field(default_factory=list)
    next_research_step: str = ""

    @field_validator("symbol")
    @classmethod
    def normalize_idea_create_symbol(cls, value: str) -> str:
        return value.strip().upper()


class CommitteeReview(BaseModel):
    id: str = Field(default_factory=lambda: new_id("committee"))
    topic: str
    symbols: list[str] = Field(default_factory=list)
    review_type: CommitteeReviewType = CommitteeReviewType.INVESTMENT_COMMITTEE
    status: CommitteeReviewStatus = CommitteeReviewStatus.COMPLETED
    proposal_id: str | None = None
    research_goal_id: str | None = None
    hypothesis_id: str | None = None
    bull_case: str = ""
    bear_case: str = ""
    risk_memo: str = ""
    missing_evidence: list[str] = Field(default_factory=list)
    conclusion: CommitteeConclusion = CommitteeConclusion.RESEARCH_MORE
    data_pack_json: dict[str, Any] = Field(default_factory=dict)
    data_pack_hash: str = ""
    output_hash: str = ""
    members_json: list[dict[str, Any]] = Field(default_factory=list)
    findings_json: list[dict[str, Any]] = Field(default_factory=list)
    created_via: CreatedVia = CreatedVia.SYSTEM
    run_card_id: str | None = None
    created_at: datetime = Field(default_factory=utc_now)
    completed_at: datetime | None = None

    @field_validator("symbols")
    @classmethod
    def normalize_committee_symbols(cls, value: list[str]) -> list[str]:
        return [item.strip().upper() for item in value if item and item.strip()]


class CommitteeReviewRunRequest(BaseModel):
    topic: str = Field(min_length=3)
    symbols: list[str] = Field(default_factory=list)
    review_type: CommitteeReviewType = CommitteeReviewType.INVESTMENT_COMMITTEE
    proposal_id: str | None = None
    research_goal_id: str | None = None
    hypothesis_id: str | None = None
    bull_case: str = ""
    bear_case: str = ""
    risk_memo: str = ""
    missing_evidence: list[str] = Field(default_factory=list)
    conclusion: CommitteeConclusion = CommitteeConclusion.RESEARCH_MORE
    created_via: CreatedVia = CreatedVia.SYSTEM
    hydrate_missing_data: bool = False
    hydration_max_symbols: int = Field(default=5, ge=0, le=20)

    @field_validator("symbols")
    @classmethod
    def normalize_committee_request_symbols(cls, value: list[str]) -> list[str]:
        return [item.strip().upper() for item in value if item and item.strip()]


class SkillValidationIssue(BaseModel):
    path: str
    message: str
    severity: str = "error"


class SkillValidationReport(BaseModel):
    id: str = Field(default_factory=lambda: new_id("skillval"))
    checked_count: int = 0
    issue_count: int = 0
    issues: list[SkillValidationIssue] = Field(default_factory=list)
    summary: str = ""
    run_card_id: str | None = None
    created_at: datetime = Field(default_factory=utc_now)


class DataQualityReport(BaseModel):
    id: str = Field(default_factory=lambda: new_id("dq"))
    target_type: DataQualityTargetType = DataQualityTargetType.ALL
    target_id: str | None = None
    missing_fields: list[dict[str, Any]] = Field(default_factory=list)
    stale_data: list[dict[str, Any]] = Field(default_factory=list)
    duplicate_rows: list[dict[str, Any]] = Field(default_factory=list)
    unit_mismatch: list[dict[str, Any]] = Field(default_factory=list)
    outliers: list[dict[str, Any]] = Field(default_factory=list)
    severity_counts: dict[str, int] = Field(default_factory=dict)
    summary: str = ""
    run_card_id: str | None = None
    created_at: datetime = Field(default_factory=utc_now)


class DataQualityRunRequest(BaseModel):
    target_type: DataQualityTargetType = DataQualityTargetType.ALL
    target_id: str | None = None


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
    earnings_preview_id: str | None = None
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


class ShadowRule(BaseModel):
    id: str = Field(default_factory=lambda: new_id("shrule"))
    strategy_id: str = ""
    rule_type: ShadowRuleType
    condition_json: dict[str, Any] = Field(default_factory=dict)
    action_json: dict[str, Any] = Field(default_factory=dict)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    support_count: int = Field(default=0, ge=0)
    violation_count: int = Field(default=0, ge=0)
    created_at: datetime = Field(default_factory=utc_now)


class ShadowStrategy(BaseModel):
    id: str = Field(default_factory=lambda: new_id("shadow"))
    name: str
    description: str = ""
    source_behavior_report_id: str
    extraction_method: str = "deterministic_v1"
    status: ShadowStrategyStatus = ShadowStrategyStatus.DRAFT
    created_via: CreatedVia = CreatedVia.CLI
    human_confirmed: bool = False
    confirmed_at: datetime | None = None
    confirmed_by: str | None = None
    run_card_id: str | None = None
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
    rules: list[ShadowRule] = Field(default_factory=list)


class ShadowReport(BaseModel):
    id: str = Field(default_factory=lambda: new_id("shrep"))
    strategy_id: str
    behavior_report_id: str
    period_start: datetime | None = None
    period_end: datetime | None = None
    total_evaluated_trades: int = 0
    rule_violation_count: int = 0
    early_exit_count: int = 0
    late_exit_count: int = 0
    missed_signal_count: int = 0
    counterfactual_pnl: float | None = None
    actual_pnl: float = 0.0
    delta_pnl: float | None = None
    counterfactual_coverage_ratio: float = 0.0
    events_with_price_count: int = 0
    events_without_price_count: int = 0
    total_delta_pnl: float | None = None
    price_dataset_hash: str = ""
    diagnostics: dict[str, Any] = Field(default_factory=dict)
    run_card_id: str | None = None
    created_at: datetime = Field(default_factory=utc_now)


class ShadowEvent(BaseModel):
    id: str = Field(default_factory=lambda: new_id("shev"))
    shadow_report_id: str
    symbol: str
    event_type: ShadowEventType
    actual_fill_ids: list[str] = Field(default_factory=list)
    roundtrip_id: str | None = None
    expected_action: dict[str, Any] = Field(default_factory=dict)
    actual_action: dict[str, Any] = Field(default_factory=dict)
    pnl_impact: float | None = None
    expected_exit_at: datetime | None = None
    expected_exit_price: float | None = None
    expected_exit_price_source: str | None = None
    expected_exit_price_confidence: PriceBarConfidence = PriceBarConfidence.UNAVAILABLE
    actual_exit_price: float | None = None
    actual_pnl: float | None = None
    counterfactual_pnl: float | None = None
    delta_pnl: float | None = None
    price_bar_id: str | None = None
    counterfactual_method: str = ""
    explanation: str = ""
    created_at: datetime = Field(default_factory=utc_now)

    @field_validator("symbol")
    @classmethod
    def normalize_shadow_event_symbol(cls, value: str) -> str:
        return value.strip().upper()


class ShadowStrategyExtractRequest(BaseModel):
    behavior_report_id: str
    name: str | None = None
    description: str | None = None


class ShadowStrategyConfirmRequest(BaseModel):
    human_confirmed: bool = True
    confirmed_by: str = "local-user"


class ShadowReportRunRequest(BaseModel):
    strategy_id: str
    behavior_report_id: str | None = None
    period_start: datetime | None = None
    period_end: datetime | None = None
    symbols: list[str] | None = None
    use_quote_history: bool = False

    @field_validator("symbols")
    @classmethod
    def normalize_shadow_symbols(cls, value: list[str] | None) -> list[str] | None:
        if not value:
            return None
        return [item.strip().upper() for item in value if item and item.strip()]


class AdvisorBriefRequest(BaseModel):
    run_light_analysis: bool = False
    max_items: int = Field(default=8, ge=1, le=20)


class AdvisorBriefItem(BaseModel):
    severity: AdvisorSeverity = AdvisorSeverity.INFO
    category: str
    title: str
    rationale: str
    next_action: str
    related_ids: list[str] = Field(default_factory=list)


class AdvisorBrief(BaseModel):
    generated_at: datetime = Field(default_factory=utc_now)
    headline: str
    risk_level: AdvisorSeverity = AdvisorSeverity.INFO
    paper_only: bool = True
    summary: list[str] = Field(default_factory=list)
    advice: list[AdvisorBriefItem] = Field(default_factory=list)
    automated_actions: list[str] = Field(default_factory=list)
    data_status: dict[str, Any] = Field(default_factory=dict)


class AdvisorQuestionRequest(BaseModel):
    question: str = Field(min_length=3)
    symbol: str | None = None
    style: str = "concise"

    @field_validator("question")
    @classmethod
    def normalize_advisor_question(cls, value: str) -> str:
        return value.strip()

    @field_validator("symbol")
    @classmethod
    def normalize_advisor_question_symbol(cls, value: str | None) -> str | None:
        return value.strip().upper() if value and value.strip() else None


class AdvisorProfile(BaseModel):
    id: str = "default"
    version: int = Field(default=1, ge=1)
    risk_profile: AdvisorRiskProfile = AdvisorRiskProfile.MODERATE
    max_single_stock_weight: float | None = Field(default=None, ge=0.0, le=1.0)
    max_tech_exposure: float | None = Field(default=None, ge=0.0, le=1.0)
    max_sector_exposure: float | None = Field(default=None, ge=0.0, le=1.0)
    min_cash_weight: float | None = Field(default=None, ge=0.0, le=1.0)
    prefer_core_etf: bool = False
    avoid_chasing_after_big_move: bool = False
    allow_options: bool | None = None
    allow_ipo_or_private: bool | None = None
    notes: list[str] = Field(default_factory=list)
    confirmed_by: str = "local-user"
    source_update_id: str | None = None
    updated_at: datetime = Field(default_factory=utc_now)


class InvestorPolicyStatement(BaseModel):
    id: str = "default"
    version: int = Field(default=1, ge=1)
    source_profile_version: int | None = None
    risk_profile: AdvisorRiskProfile = AdvisorRiskProfile.MODERATE
    investment_horizon: str = "medium_to_long_term"
    max_single_stock_weight: float | None = Field(default=None, ge=0.0, le=1.0)
    max_tech_exposure: float | None = Field(default=None, ge=0.0, le=1.0)
    max_sector_exposure: float | None = Field(default=None, ge=0.0, le=1.0)
    min_cash_weight: float | None = Field(default=None, ge=0.0, le=1.0)
    max_drawdown_tolerance: float | None = Field(default=None, ge=0.0, le=1.0)
    core_satellite_target: dict[str, float] = Field(default_factory=dict)
    target_allocations: dict[str, dict[str, float]] = Field(default_factory=dict)
    prohibited_assets: list[str] = Field(default_factory=list)
    review_cadence: str = "quarterly"
    notes: list[str] = Field(default_factory=list)
    confirmed_by: str = "local-user"
    updated_at: datetime = Field(default_factory=utc_now)


class AdvisorProfileUpdateRequest(BaseModel):
    risk_profile: AdvisorRiskProfile | None = None
    max_single_stock_weight: float | None = Field(default=None, ge=0.0, le=1.0)
    max_tech_exposure: float | None = Field(default=None, ge=0.0, le=1.0)
    max_sector_exposure: float | None = Field(default=None, ge=0.0, le=1.0)
    min_cash_weight: float | None = Field(default=None, ge=0.0, le=1.0)
    prefer_core_etf: bool | None = None
    avoid_chasing_after_big_move: bool | None = None
    allow_options: bool | None = None
    allow_ipo_or_private: bool | None = None
    notes: list[str] = Field(default_factory=list)
    rationale: str = Field(min_length=3)
    source_question_id: str | None = None
    proposed_by: str = "hermes"


class AdvisorProfileConfirmationRequest(BaseModel):
    confirmed: bool = True
    confirmed_by: str = "local-user"
    rejection_reason: str | None = None


class AdvisorProfileUpdate(BaseModel):
    id: str = Field(default_factory=lambda: new_id("advprofupd"))
    status: AdvisorProfileUpdateStatus = AdvisorProfileUpdateStatus.PENDING
    proposed_changes: dict[str, Any]
    rationale: str
    source_question_id: str | None = None
    proposed_by: str = "hermes"
    created_at: datetime = Field(default_factory=utc_now)
    confirmed_at: datetime | None = None
    confirmed_by: str | None = None
    rejection_reason: str | None = None
    applied_profile_version: int | None = None


class AccountingTransactionCreate(BaseModel):
    account_id: str = "default"
    transaction_type: AccountingTransactionType
    symbol: str | None = None
    quantity: float | None = Field(default=None, gt=0)
    price: float | None = Field(default=None, ge=0.0)
    gross_amount: float | None = None
    fees: float = Field(default=0.0, ge=0.0)
    taxes: float = Field(default=0.0, ge=0.0)
    net_cash_flow: float | None = None
    currency: str = "USD"
    occurred_at: datetime = Field(default_factory=utc_now)
    settled_at: datetime | None = None
    source: str = "manual"
    source_id: str | None = None
    raw: dict[str, Any] = Field(default_factory=dict)
    row_hash: str | None = None

    @field_validator("account_id", "currency")
    @classmethod
    def normalize_accounting_create_text(cls, value: str) -> str:
        return value.strip().upper() if value and value.strip() else "DEFAULT"

    @field_validator("symbol")
    @classmethod
    def normalize_accounting_create_symbol(cls, value: str | None) -> str | None:
        return value.strip().upper() if value and value.strip() else None


class AccountingTransaction(BaseModel):
    id: str = Field(default_factory=lambda: new_id("accttx"))
    account_id: str = "DEFAULT"
    transaction_type: AccountingTransactionType
    symbol: str | None = None
    quantity: float | None = Field(default=None, gt=0)
    price: float | None = Field(default=None, ge=0.0)
    gross_amount: float = 0.0
    fees: float = Field(default=0.0, ge=0.0)
    taxes: float = Field(default=0.0, ge=0.0)
    net_cash_flow: float = 0.0
    currency: str = "USD"
    occurred_at: datetime = Field(default_factory=utc_now)
    settled_at: datetime | None = None
    source: str = "manual"
    source_id: str | None = None
    raw: dict[str, Any] = Field(default_factory=dict)
    row_hash: str
    created_at: datetime = Field(default_factory=utc_now)

    @field_validator("account_id", "currency")
    @classmethod
    def normalize_accounting_text(cls, value: str) -> str:
        return value.strip().upper() if value and value.strip() else "DEFAULT"

    @field_validator("symbol")
    @classmethod
    def normalize_accounting_symbol(cls, value: str | None) -> str | None:
        return value.strip().upper() if value and value.strip() else None


class AccountingTaxLot(BaseModel):
    id: str = Field(default_factory=lambda: new_id("taxlot"))
    account_id: str = "DEFAULT"
    symbol: str
    source_transaction_id: str
    opened_at: datetime
    closed_at: datetime | None = None
    quantity_original: float = Field(gt=0)
    quantity_open: float = Field(default=0.0, ge=0.0)
    cost_basis_original: float = 0.0
    cost_basis_open: float = 0.0
    realized_pnl: float = 0.0
    currency: str = "USD"
    status: TaxLotStatus = TaxLotStatus.OPEN
    disposal_transaction_ids: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utc_now)

    @field_validator("account_id", "currency")
    @classmethod
    def normalize_tax_lot_text(cls, value: str) -> str:
        return value.strip().upper() if value and value.strip() else "DEFAULT"

    @field_validator("symbol")
    @classmethod
    def normalize_tax_lot_symbol(cls, value: str) -> str:
        return value.strip().upper()


class AccountingPosition(BaseModel):
    account_id: str = "DEFAULT"
    symbol: str
    quantity: float = 0.0
    cost_basis: float = 0.0
    avg_cost: float = 0.0
    currency: str = "USD"


class AccountingSnapshot(BaseModel):
    id: str = Field(default_factory=lambda: new_id("acctsnap"))
    as_of: datetime = Field(default_factory=utc_now)
    transaction_count: int = 0
    open_lot_count: int = 0
    positions: list[AccountingPosition] = Field(default_factory=list)
    cash_by_currency: dict[str, float] = Field(default_factory=dict)
    realized_pnl_by_symbol: dict[str, float] = Field(default_factory=dict)
    dividend_income_by_symbol: dict[str, float] = Field(default_factory=dict)
    fees_by_currency: dict[str, float] = Field(default_factory=dict)
    tax_withheld_by_currency: dict[str, float] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
    run_card_id: str | None = None


class AdvisorRecommendation(BaseModel):
    id: str = Field(default_factory=lambda: new_id("adrec"))
    source_type: AdvisorSourceType
    source_id: str
    symbol: str | None = None
    recommendation_type: AdvisorSeverity = AdvisorSeverity.INFO
    title: str
    summary: str
    suggested_user_action: str
    confidence: AdvisorConfidence = AdvisorConfidence.MEDIUM
    reasons: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    linked_artifacts: list[dict[str, Any]] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utc_now)

    @field_validator("symbol")
    @classmethod
    def normalize_advisor_recommendation_symbol(cls, value: str | None) -> str | None:
        return value.strip().upper() if value and value.strip() else None


class AdvisorQuestion(BaseModel):
    id: str = Field(default_factory=lambda: new_id("advq"))
    user_question: str
    symbol: str | None = None
    original_symbol: str | None = None
    resolved_symbol: str | None = None
    symbol_resolution_status: SymbolResolutionStatus = SymbolResolutionStatus.NO_SYMBOL
    answer_summary: str
    recommendation_type: AdvisorSeverity = AdvisorSeverity.INFO
    confidence: AdvisorConfidence = AdvisorConfidence.MEDIUM
    run_card_id: str | None = None
    created_at: datetime = Field(default_factory=utc_now)

    @field_validator("symbol", "original_symbol", "resolved_symbol")
    @classmethod
    def normalize_advisor_question_record_symbol(cls, value: str | None) -> str | None:
        return value.strip().upper() if value and value.strip() else None


class AdvisorAnswer(BaseModel):
    question_id: str
    recommendation: AdvisorSeverity = AdvisorSeverity.INFO
    recommendation_type: AdvisorSeverity = AdvisorSeverity.INFO
    original_symbol: str | None = None
    resolved_symbol: str | None = None
    symbol_resolution_status: SymbolResolutionStatus = SymbolResolutionStatus.NO_SYMBOL
    conclusion: str
    summary: str
    confidence: AdvisorConfidence = AdvisorConfidence.MEDIUM
    suggested_user_action: str
    reasons: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    decision_required: bool = False
    details_available: bool = False
    linked_artifacts_json: list[dict[str, Any]] = Field(default_factory=list)
    provenance_json: dict[str, Any] = Field(default_factory=dict)
    opportunity_radar_run_id: str | None = None
    opportunity_cards_json: list[dict[str, Any]] = Field(default_factory=list)
    run_card_id: str | None = None
    paper_only: bool = True
    created_at: datetime = Field(default_factory=utc_now)

    @field_validator("original_symbol", "resolved_symbol")
    @classmethod
    def normalize_advisor_answer_symbol(cls, value: str | None) -> str | None:
        return value.strip().upper() if value and value.strip() else None


class AdvisorPulse(BaseModel):
    id: str = Field(default_factory=lambda: new_id("advpulse"))
    pulse_type: str = "hourly"
    severity: AdvisorPulseSeverity = AdvisorPulseSeverity.SILENT
    summary: str
    recommendations: list[AdvisorRecommendation] = Field(default_factory=list)
    should_notify: bool = False
    sent_to_user: bool = False
    run_card_id: str | None = None
    created_at: datetime = Field(default_factory=utc_now)


class AdvisorFullBrief(BaseModel):
    id: str = Field(default_factory=lambda: new_id("advbrief"))
    brief_type: AdvisorFullBriefType = AdvisorFullBriefType.PRE_MARKET
    market_session_date: str
    summary: str
    market_regime_snapshot_id: str | None = None
    recommendations: list[AdvisorRecommendation] = Field(default_factory=list)
    committee_review_ids_json: list[str] = Field(default_factory=list)
    run_card_id: str | None = None
    sent_to_user: bool = False
    schedule_context: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utc_now)


class OpportunityRadarRequest(BaseModel):
    question: str = "今晚市場有無值得留意的新機會？"
    run_type: str = "user_question"
    max_watch: int = Field(default=3, ge=1, le=6)
    max_blocked: int = Field(default=3, ge=1, le=6)

    @field_validator("question", "run_type")
    @classmethod
    def normalize_opportunity_request_text(cls, value: str) -> str:
        return value.strip()


class OpportunityCard(BaseModel):
    id: str = Field(default_factory=lambda: new_id("oppcard"))
    run_id: str
    rank: int = 0
    title: str
    category: OpportunityCategory = OpportunityCategory.THEME
    symbols: list[str] = Field(default_factory=list)
    recommendation_type: OpportunityRecommendationType = OpportunityRecommendationType.RESEARCH
    confidence: AdvisorConfidence = AdvisorConfidence.MEDIUM
    score: int = 0
    one_line: str
    reasons: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    evidence_layers: dict[str, list[str]] = Field(default_factory=dict)
    upgrade_conditions: list[str] = Field(default_factory=list)
    downgrade_conditions: list[str] = Field(default_factory=list)
    linked_artifacts: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utc_now)

    @field_validator("symbols")
    @classmethod
    def normalize_opportunity_symbols(cls, value: list[str]) -> list[str]:
        return [item.strip().upper() for item in value if item and item.strip()]


class OpportunityRadarRun(BaseModel):
    id: str = Field(default_factory=lambda: new_id("opprun"))
    question: str
    run_type: str = "user_question"
    market_regime_snapshot_id: str | None = None
    portfolio_risk_snapshot_id: str | None = None
    run_card_id: str | None = None
    summary: str
    cards: list[OpportunityCard] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utc_now)


class FundamentalsRefreshResult(BaseModel):
    symbols: list[str] = Field(default_factory=list)
    total_count: int = 0
    stored_count: int = 0
    errors: list[str] = Field(default_factory=list)
    snapshots: list[FundamentalSnapshot] = Field(default_factory=list)


class Signal(BaseModel):
    id: str = Field(default_factory=lambda: new_id("sig"))
    run_id: str
    symbol: str
    side: SignalSide = SignalSide.WATCH
    horizon: SignalHorizon = SignalHorizon.SWING
    score: int = Field(default=0, ge=0, le=100)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    strength: SignalStrength = SignalStrength.WEAK
    source: SignalSource = SignalSource.MANUAL_RUN
    status: SignalStatus = SignalStatus.ACTIVE
    feature_breakdown: dict[str, Any] = Field(default_factory=dict)
    evidence: list[str] = Field(default_factory=list)
    counter_evidence: list[str] = Field(default_factory=list)
    gates: dict[str, Any] = Field(default_factory=dict)
    proposal_id: str | None = None
    research_goal_id: str | None = None
    thesis_id: str | None = None
    signal_price: float | None = None
    suggested_qty: int = 0
    suggested_limit_price: float | None = None
    suggested_notional_usd: float = 0.0
    outcome_windows: dict[str, Any] = Field(default_factory=dict)
    signal_engine_version: str = ""
    feature_weight_version: str = ""
    threshold_profile: dict[str, Any] = Field(default_factory=dict)
    readiness_version: str = ""
    committee_profile_version: str = ""
    expires_at: datetime
    created_at: datetime = Field(default_factory=utc_now)
    rejected_at: datetime | None = None
    rejection_reason: str | None = None

    @field_validator("symbol")
    @classmethod
    def normalize_signal_symbol(cls, value: str) -> str:
        return value.strip().upper()


class SignalRun(BaseModel):
    id: str = Field(default_factory=lambda: new_id("sigrun"))
    source: SignalSource = SignalSource.MANUAL_RUN
    horizon: SignalHorizon = SignalHorizon.SWING
    universe: list[str] = Field(default_factory=list)
    summary: str = ""
    skipped: list[str] = Field(default_factory=list)
    metrics: dict[str, Any] = Field(default_factory=dict)
    run_card_id: str | None = None
    signals: list[Signal] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utc_now)

    @field_validator("universe")
    @classmethod
    def normalize_signal_universe(cls, value: list[str]) -> list[str]:
        return [item.strip().upper() for item in value if item and item.strip()]


class SignalRunRequest(BaseModel):
    symbols: list[str] | None = None
    horizon: SignalHorizon = SignalHorizon.SWING
    max_signals: int | None = Field(default=None, ge=1, le=50)
    source: SignalSource = SignalSource.MANUAL_RUN

    @field_validator("symbols")
    @classmethod
    def normalize_signal_request_symbols(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        return [item.strip().upper() for item in value if item and item.strip()]


class SignalRunResult(BaseModel):
    run: SignalRun
    signals: list[Signal] = Field(default_factory=list)
    skipped: list[str] = Field(default_factory=list)
    metrics: dict[str, Any] = Field(default_factory=dict)


class SignalRejectRequest(BaseModel):
    reason: str = "Rejected by user"


class SignalPromoteRequest(BaseModel):
    approved_by: str = "local-user"


class SignalOutcomeRow(BaseModel):
    signal_id: str
    side: SignalSide
    blocked_action: str | None = None
    window: str
    window_type: str = "trading_days"
    entry_bar_ts: datetime
    target_bar_ts: datetime
    raw_return_pct: float
    directional_return_pct: float
    raw_excess_return_pct: float | None = None
    directional_excess_return_pct: float | None = None
    hit_direction: bool
    evaluated_at: datetime = Field(default_factory=utc_now)
    max_drawdown_pct: float | None = None
    max_favorable_excursion_pct: float | None = None
    max_adverse_upside_pct: float | None = None
    max_favorable_downside_pct: float | None = None
    score: int | None = None
    readiness_score: float | None = None
    blocking_reasons: list[str] = Field(default_factory=list)


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
    draft_min_score: int = 0
    skipped_below_min_score: int = 0
    max_score_seen: int = 0


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
